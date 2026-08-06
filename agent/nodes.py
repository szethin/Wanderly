import time
import os
from dotenv import load_dotenv
from typing import cast
from datetime import datetime
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Import State, Prompts, and Schema
from agent.state import WanderlyState
from agent.prompts import PLANNER_PROMPT, GENERATOR_MODE_EDITOR, GENERATOR_MODE_INITIAL, GENERATOR_MODE_REFLECTION, REFLECTION_PROMPT
from models.schema import PlannerOutput, ReflectionOutput

# Import external tools
from tools.google_maps import search_google_maps, get_coordinates
from tools.weather import get_weather_forecast
from tools.tavily import search_travel_info


load_dotenv()

# Initialize LLM. Temperature 0 for Planner (needs logic), 0.7 for Generator (needs creativity).
llm_logic = ChatGoogleGenerativeAI(model="gemini-3.5-flash", temperature=0)
llm_creative = ChatGoogleGenerativeAI(model="gemini-3.5-flash", temperature=0.7)


def planner_node(state: WanderlyState) -> dict:
    """
    Node 1: The Brain. Analyzes user intent and decides which tools to call.
    Forces LLM to output structured JSON matching PlannerOutput.
    """
    print("🧠 [Planner Node] Breaking down goal and selecting tools...")
    start_time = time.time() # Start stopwatch

    # ChatPromptTemplate: Securely injects state variables into the prompt
    # Receives 6 state variables:
    # 1. Destination
    # 2. Duration
    # 3. Budget
    # 4. Style
    # 5. Constraints
    # 6. Special Requests
    prompt = ChatPromptTemplate.from_messages([
        ("system", PLANNER_PROMPT),
        ("user", "Destination: {destination}\nStart Date: {start_date}\nDuration: {duration} days\nBudget: RM {budget} (Malaysian Ringgit)\nStyle: {travel_style}\nConstraints: {constraints}\nSpecial Requests: {special_requests}\nUser Feedback: {user_feedback}")
    ])

    # .with_structured_output(): LangChain's native method to enforce output format in Pydantic schema
    chain = prompt | llm_logic.with_structured_output(PlannerOutput, include_raw=True) # include_raw=True allows us to access both the parsed Pydantic object AND the raw LLM message (for tokens)

    try:
        # Pass required state variables to format the prompt
        raw_output = cast(dict, chain.invoke({  # FIX: Cast the entire output to a 'dict' first, so the IDE knows we can use ["parsed"] and ["raw"]
            "destination": state.get("destination"),
            "start_date": state.get("start_date", "Unknown"),
            "duration": state.get("duration"),
            "budget": state.get("budget"),
            "travel_style": state.get("travel_style"),
            "constraints": state.get("constraints"),
            "special_requests": state.get("special_requests"),

            # Safely extract user_feedback from the global state. Default to empty string for initial generation.
            "user_feedback": state.get("user_feedback", ""),

            # Dynamically inject execution-time date to prevent long-running server state freeze
            "today_date": datetime.now().strftime("%Y-%m-%d")
        }))

        # Extract parsed object and raw message safely
        result = cast(PlannerOutput, raw_output["parsed"])
        raw_msg = raw_output["raw"]

        # Safely extract token count, defaulting to 0 if API hides it
        tokens = getattr(raw_msg, "usage_metadata", {}).get("total_tokens", 0) if hasattr(raw_msg, "usage_metadata") else 0

        print(f"   -> Reasoning: {result.planner_reasoning}")
        print(f"    -> Tools Selected: {result.required_tools}")
        if result.maps_query:
            print(f"    -> Crafted Map Query: '{result.maps_query}'")
        if result.search_query:
            print(f"    -> Crafted Search Query: '{result.search_query}'")
        if result.weather_query:
            print(f"    -> Crafted Weather Query: '{result.weather_query}'")

        execution_time = time.time() - start_time

        # Initialize the metrics dictionary inside the state
        current_metrics = state.get("metrics", {})
        current_metrics.update({
            "planner_time": execution_time,
            "planner_tokens": tokens
        })

        # Return dict to update State
        return {
            "planner_reasoning": result.planner_reasoning,
            "planner_plan": result.planner_plan,

            # 1. Active Variables (Mutable: will be overwritten by Reflection)
            "required_tools": result.required_tools,
            "maps_query": result.maps_query,
            "search_query": result.search_query,
            "weather_query": result.weather_query,

            # 2. UI Trace Variables (Immutable: strictly tracks Planner's original intent)
            "planner_initial_tools": result.required_tools,
            "planner_initial_maps_query": result.maps_query,
            "planner_initial_search_query": result.search_query,
            "planner_initial_weather_query": result.weather_query,

            "metrics": current_metrics # Save telemetry to state
        }

    except Exception as e:
        print(f"❌ [Planner Node] Failed to parse output: {e}")
        # Graceful fallback: Prevent crash by moving forward with no tools
        # Safely default the trace variables to corresponding empty types to prevent KeyError in UI rendering
        return {
            "planner_reasoning": "System encountered an error during planning. Executing safe fallback plan without external tools.",   # Provide a fallback reasoning so the UI still has a logical thought process to display
            "planner_plan": ["Fallback: Generate without tools"], 

            "required_tools": [], 
            "maps_query": "",
            "search_query": "",
            "weather_query": "",

            "planner_initial_tools": [],
            "planner_initial_maps_query": "",
            "planner_initial_search_query": "",
            "planner_initial_weather_query": "",
            
            "metrics": state.get("metrics", {})
        }


def tool_executor_node(state: WanderlyState) -> dict:
    """
    Node 2: Deterministic Tool Execution. No LLM involved.
    Reads 'required_tools' and triggers actual Python tool functions.
    Accumulates tool call counts & execution times across iterative cycles.
    """
    print("⚙️ [Tool Executor Node] Executing dynamic tools...")

    tools_to_run = state.get("required_tools", [])
    destination = state.get("destination", "Unknown")

    # Retrieve existing metrics from the global state to prevent overwriting
    current_metrics = state.get("metrics", {})

    # Extract revision_count to dynamically control state accumulation
    revision_count = state.get("revision_count", 0)

    # State update dictionary to accumulate tool execution results
    updates = {}

    if "maps" in tools_to_run:
        print("   -> 📍 Calling Google Maps...")
        # Map tool call start time
        t0 = time.time()

        # Update tool call results
        maps_query = state.get("maps_query", "attractions")
        new_maps_result = search_google_maps(destination, query_type=maps_query)

        # ==========================================
        # SMART ACCUMULATION ENGINE
        # Only merge state lists if the system is currently under reflection loops
        # ==========================================
        if revision_count > 0:
            # Retrieve old maps state
            old_maps = state.get("maps_result") or {}

            # Ensure it's a dictionary to prevent AttributeError before calling .get()
            old_places = old_maps.get("places", []) if isinstance(old_maps, dict) else []
            new_places = new_maps_result.get("places", [])

            # Merge lists and filter duplicates based on place 'name' to optimize LLM token usage
            # Uses dictionary comprehension as an ordered, fast deduplication mechanism
            merged_places = {place["name"]: place for place in old_places + new_places if "name" in place}
            new_maps_result["places"] = list(merged_places.values())
            
            print(f"      [State] Accumulated Maps context: {len(new_maps_result['places'])} total places.")

        updates["maps_result"] = new_maps_result

        # Dynamically accumulate execution time and increment tool call count across loops
        current_metrics["maps_time"] = current_metrics.get("maps_time", 0.0) + (time.time() - t0)
        current_metrics["maps_calls"] = current_metrics.get("maps_calls", 0) + 1

    if "weather" in tools_to_run:
        print("   -> 🌤️ Calling OpenWeather...")
        # Weather tool call start time
        t0 = time.time()

        # Use LLM-cleaned weather_query if available, else default to raw destination
        weather_query = state.get("weather_query") or destination

        # Weather ALWAYS overwrites. Reflection only re-triggers weather to fix a 404 City Not Found error.
        updates["weather_result"] = get_weather_forecast(weather_query)

        # Dynamically accumulate execution time and increment tool call count across loops
        current_metrics["weather_time"] = current_metrics.get("weather_time", 0.0) + (time.time() -  t0)
        current_metrics["weather_calls"] = current_metrics.get("weather_calls", 0) + 1

    if "tavily" in tools_to_run:
        print("   -> 🔍 Calling Tavily Web Search...")
        # Tavily tool call start time
        t0 = time.time()

        # Update tool call results
        query = state.get("search_query", f"travel guide {destination}")
        new_search_result = search_travel_info(query)

        # ==========================================
        # SMART ACCUMULATION ENGINE
        # Only merge state lists if the system is currently under reflection loops
        # ==========================================
        if revision_count > 0:
            old_search = state.get("search_result") or {}
            old_results = old_search.get("results", []) if isinstance(old_search, dict) else []
            new_results = new_search_result.get("results", [])
            
            # Merge lists and deduplicate based on 'url' to optimize LLM context window
            merged_results = {snippet["url"]: snippet for snippet in old_results + new_results if "url" in snippet}
            new_search_result["results"] = list(merged_results.values())
            
            print(f"      [State] Accumulated Tavily context: {len(new_search_result['results'])} total snippets.")

        updates["search_result"] = new_search_result

        # Dynamically accumulate execution time and increment tool call count across loops
        current_metrics["tavily_time"] = current_metrics.get("tavily_time", 0.0) + (time.time() - t0)
        current_metrics["tavily_calls"] = current_metrics.get("tavily_calls", 0) + 1

    # Persist the properly aggregated metrics back into the state update dictionary
    updates["metrics"] = current_metrics

    return updates


def reflection_node(state: WanderlyState) -> dict:
    """
    Node 3 (V2): The Critic & Coach. Evaluates tool outputs and decides if re-planning is needed.
    """
    print("🧐 [Reflection Node] Evaluating tool results and constraints...")
    start_time = time.time()

    # Extract current state variables for checking
    revision_count = state.get("revision_count", 0)
    past_queries = state.get("past_queries", [])
    current_maps_query = state.get("maps_query", "")
    current_search_query = state.get("search_query", "")
    current_weather_query = state.get("weather_query", "")

    # --- MEMORY MANAGEMENT ---
    updated_past_queries = list(past_queries) # Create a copy to avoid mutating the original reference directly

    # Append the queries that were JUST executed into the past queries list to prevent LLM from reusing them
    if current_maps_query and current_maps_query not in updated_past_queries:
        updated_past_queries.append(current_maps_query)
    if current_search_query and current_search_query not in updated_past_queries:
        updated_past_queries.append(current_search_query)
    if current_weather_query and current_weather_query not in updated_past_queries:
        updated_past_queries.append(current_weather_query)

    # Ensure safe extraction of the array to avoid NoneType exceptions
    reflection_logs = state.get("reflection_logs", [])
    updated_logs = list(reflection_logs) # Create a shallow copy for pure functional state updates

    # --- HARD LOOP SAFEGUARD ---
    # Max 2 revisions. If we hit the limit, gracefully force the system to proceed to generation.
    if revision_count >= 1:
        print("⚠️ [Reflection Node] Max revision limit reached. Forcing generation fallback.")

        # Append a final system-level log entry to the audit trail
        fallback_log = {
            "loop": revision_count + 1, # offset for human readable UI display
            "critique": "⚠️ [Reflection Node]: Max revision limit reached. Forcing fallback to Generation phase.",
            "tools": [], 
            "maps_query": "", 
            "search_query": "", 
            "weather_query": ""
        }
        updated_logs.append(fallback_log)
 
        return {
            "need_more_info": False,
            
            "reflection_logs": updated_logs, # Return the complete audit trail array
            
            # FIX (Off-by-one Bug): Return the exact revision_count (2) instead of falsely incrementing to 3
            "revision_count": revision_count, 
            
            "past_queries": updated_past_queries,

            "metrics": state.get("metrics", {})
        }

    # --- PROMPT INJECTION ---
    prompt = ChatPromptTemplate.from_messages([
        ("system", REFLECTION_PROMPT),
        ("user", """
        User Travel Plan Request: 
        Destination: {destination} ({duration} days, Budget: RM {budget} (Malaysian Ringgit))
        Style: {travel_style} | Constraints: {constraints} | Requests: {special_requests}

        User Feedback (Latest Modification): {user_feedback}

        Past Failed Queries (DO NOT REUSE): {past_queries}

        --- Current Tool Observations ---
        Maps Data: {maps_result}
        Weather Data: {weather_result}
        Web Search Data: {search_result}
        ---------------------------------
        """)
    ])

    # Using llm_logic (temp=0) for strict, deterministic QA reasoning.
    # .with_structured_output(): LangChain's native method to enforce output format in Pydantic schema
    chain = prompt | llm_logic.with_structured_output(ReflectionOutput, include_raw=True) # include_raw=True allows us to access both the parsed Pydantic object AND the raw LLM message (for tokens)

    try:
        raw_output = cast(dict, chain.invoke({
            "destination": state.get("destination"),
            "duration": state.get("duration"),
            "budget": state.get("budget"),
            "travel_style": state.get("travel_style"),
            "constraints": state.get("constraints"),
            "special_requests": state.get("special_requests"),

            "user_feedback": state.get("user_feedback", ""),

            "past_queries": updated_past_queries,
            "maps_result": state.get("maps_result", "None"),
            "weather_result": state.get("weather_result", "None"),
            "search_result": state.get("search_result", "None")
        }))

        # Extract parsed object and raw message safely
        result = cast(ReflectionOutput, raw_output["parsed"])
        raw_msg = raw_output["raw"]

        # Safely extract token count, defaulting to 0 if API hides it
        tokens = getattr(raw_msg, "usage_metadata", {}).get("total_tokens", 0) if hasattr(raw_msg, "usage_metadata") else 0

        print(f"   -> Critique: {result.reflection_feedback}")
        print(f"   -> Needs More Info: {result.need_more_info}")

        # Update telemetry
        current_metrics = state.get("metrics", {})
        current_metrics.update({
            # Accumulate time and tokens in case of multiple reflections
            "reflection_time": current_metrics.get("reflection_time", 0) + (time.time() - start_time),
            "reflection_tokens": current_metrics.get("reflection_tokens", 0) + tokens
        })

        current_log = {
            "loop": revision_count + 1,
            "critique": result.reflection_feedback,
            "tools": result.required_tools,
            "maps_query": result.maps_query,
            "search_query": result.search_query,
            "weather_query": result.weather_query
        }

        updated_logs.append(current_log) # Event Sourcing: Append iteration state instead of overwriting

        # --- STATE UPDATE RETURN ---
        return {
            "need_more_info": result.need_more_info,
            "reflection_logs": updated_logs,            # Pass the appended list back to global state
            
            "required_tools": result.required_tools,    # Overwrites old tools if returning to Tool Executor
            "maps_query": result.maps_query,            # Overwrites with new optimized query
            "search_query": result.search_query,        # Overwrites with new optimized query
            "weather_query": result.weather_query,      # Overwrites with new optimized query
            
            "revision_count": revision_count + 1,       # Increment loop counter
            "past_queries": updated_past_queries,       # Save updated past queries list
            "metrics": current_metrics
        }

    except Exception as e:
        print(f"❌ [Reflection Node] Output parsing failed: {e}")

        # Graceful Fallback for Audit Trail
        reflection_logs = state.get("reflection_logs", [])
        updated_logs = list(reflection_logs)
        
        fallback_log = {
            "loop": revision_count + 1,
            "critique": f"❌ [System Error]: Reflection parsing failed ({e}). Forcing fallback to Generation phase.",
            "tools": [], "maps_query": "", "search_query": "", "weather_query": ""
        }
        updated_logs.append(fallback_log)

        return {
            "need_more_info": False,
            "reflection_logs": updated_logs,       # Return the appended array
            "revision_count": revision_count,      # Freeze the counter
            "past_queries": updated_past_queries,
            "metrics": state.get("metrics", {})
        }



def generator_node(state: WanderlyState) -> dict:
    """
    Node 4: Final Synthesis. Reads tool observations and drafts the itinerary.
    Utilizes Dynamic Prompt Routing to optimize LLM context limits based on execution history.
    """
    print("✍️ [Generator Node] Synthesizing final itinerary...")
    start_time = time.time() # Start stopwatch

    # Extract state variables for routing evaluation
    user_feedback = state.get("user_feedback", "")
    revision_count = state.get("revision_count", 0)
    reflection_logs = state.get("reflection_logs", [])


    # --- Data Parsing: Reflecton History Sanitization ---
    # Extract ONLY the critiques from the raw logs.
    if revision_count > 1 and reflection_logs:
        clean_reflection_history = "\n".join([f"- Reflection {log.get('loop')}: {log.get('critique')}" for log in reflection_logs])
    else:
        clean_reflection_history = "No reflection loops triggered. All tool data is original."


    # --- DYNAMIC PROMPT ROUTING ENGINE ---
    if user_feedback:
        print("   -> Operation Mode: Iterative Refinement")
        system_prompt = GENERATOR_MODE_EDITOR
    elif revision_count > 1:
        print("   -> Operation Mode: Reflection")
        system_prompt = GENERATOR_MODE_REFLECTION
    else:
        print("   -> Operation Mode: Initial Generation")
        system_prompt = GENERATOR_MODE_INITIAL


    # Construct template utilizing the dynamically selected system prompt
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("user", """
        User Profile:
        Destination: {destination} (Starting: {start_date} for {duration} days, Budget: RM {budget} (Malaysian Ringgit))
        Travel Style: {travel_style}
        Constraints: {constraints}
        Special Requests: {special_requests}

        User Feedback (Modification Request): {user_feedback}

        Reflection History: {reflection_history}
        
        Agent Plan: {planner_plan}
        
        --- Tool Observations ---
        Maps Data: {maps_result}
        Weather Data: {weather_result}
        Web Search Data: {search_result}
        -------------------------

        --- Existing Itinerary ---
        {final_itinerary}
        --------------------------
        
        Generate the final itinerary now.
        """)
    ])

    # Removed StrOutputParser() so we can capture the raw AIMessage to read token counts
    chain = prompt | llm_creative

    try: 
        response = chain.invoke({
            "destination": state.get("destination"),
            "start_date": state.get("start_date"),
            "duration": state.get("duration"),
            "budget": state.get("budget"),
            "travel_style": state.get("travel_style"),
            "constraints": state.get("constraints"),
            "special_requests": state.get("special_requests"),

            "planner_plan": state.get("planner_plan"),

            "maps_result": state.get("maps_result", "No map data retrieved."),
            "weather_result": state.get("weather_result", "No weather data retrieved."),
            "search_result": state.get("search_result", "No web data retrieved."),

            # Inject the context for editor mode
            "user_feedback": state.get("user_feedback", ""),
            "final_itinerary": state.get("final_itinerary", "No existing itinerary. This is the first generation."),

            # Inject the context for reflection mode
            "reflection_history": clean_reflection_history
        })

        # Extract raw content safely matching Gemini payload structures
        raw_content = response.content

        if isinstance(raw_content, list) and len(raw_content) > 0 and isinstance(raw_content[0], dict):
            final_output = raw_content[0].get("text", str(raw_content))
        else:
            final_output = str(raw_content) # Fallback for pure strings or unexpected formats

        # Safely extract telemetry tokens (completely unaffected by the content formatting above)
        tokens = getattr(response, "usage_metadata", {}).get("total_tokens", 0) if hasattr(response, "usage_metadata") else 0

        # Initialize the metrics dictionary inside the state
        current_metrics = state.get("metrics", {})
        current_metrics.update({
            "generator_time": time.time() - start_time,
            "generator_tokens": tokens
        })

        print("✅ [Generator Node] Itinerary generated successfully.")
        
        return {
            "final_itinerary": final_output,
            "metrics": current_metrics,
            "error_msg": "",    # Clear any previous error messages upon successful generation
        }

    except Exception as e:
        print(f"❌ [Generator Node] Generation failed: {e}")
        
        # Graceful Fallback: Return a polite error message, BUT prepend it to the existing itinerary
        # This prevents the crucial memory state of the actual travel plan from being permanently overwritten by an error string.
        fallback_msg = f"⚠️ **Agent Notification:** I encountered a system issue while writing your itinerary (Error: {str(e)}). This is usually due to API limits or network timeouts. Please wait a moment and try asking me again!\n\n---\n\n"
        
        return {
            "final_itinerary": state.get("final_itinerary", ""), 
            "error_msg": fallback_msg,  # Inject error into a separate, temporary channel
            "metrics": state.get("metrics", {})
        }