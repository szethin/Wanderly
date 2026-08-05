import time
import os
from dotenv import load_dotenv
from typing import cast
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Import State, Prompts, and Schema
from agent.state import WanderlyState
from agent.prompts import PLANNER_PROMPT, GENERATOR_PROMPT, REFLECTION_PROMPT
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
        ("user", "Destination: {destination}\nStart Date: {start_date}\nDuration: {duration} days\nBudget: RM {budget} (Malaysian Ringgit)\nStyle: {travel_style}\nConstraints: {constraints}\nSpecial Requests: {special_requests}")
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
            "special_requests": state.get("special_requests")
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

    # State update dictionary to accumulate tool execution results
    updates = {}

    if "maps" in tools_to_run:
        print("   -> 📍 Calling Google Maps...")
        # Map tool call start time
        t0 = time.time()

        # Update tool call results
        maps_query = state.get("maps_query", "attractions")
        updates["maps_result"] = search_google_maps(destination, query_type=maps_query)

        # Dynamically accumulate execution time and increment tool call count across loops
        current_metrics["maps_time"] = current_metrics.get("maps_time", 0.0) + (time.time() - t0)
        current_metrics["maps_calls"] = current_metrics.get("maps_calls", 0) + 1

    if "weather" in tools_to_run:
        print("   -> 🌤️ Calling OpenWeather...")
        # Weather tool call start time
        t0 = time.time()

        # Dynamic fallback: Use LLM-cleaned weather_query if available, else default to raw destination
        weather_query = state.get("weather_query") or destination
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
        updates["search_result"] = search_travel_info(query)

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
            
            "past_queries": updated_past_queries
        }

    # --- PROMPT INJECTION ---
    prompt = ChatPromptTemplate.from_messages([
        ("system", REFLECTION_PROMPT),
        ("user", """
        User Travel Plan Request: 
        Destination: {destination} ({duration} days, Budget: RM {budget} (Malaysian Ringgit))
        Style: {travel_style} | Constraints: {constraints} | Requests: {special_requests}

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
    Node 4: Final Synthesis. Reads all structured tool observations and drafts the itinerary.
    """
    print("✍️ [Generator Node] Synthesizing final itinerary...")
    start_time = time.time() # Start stopwatch

    prompt = ChatPromptTemplate.from_messages([
        ("system", GENERATOR_PROMPT),
        ("user", """
        User Profile:
        Destination: {destination} (Starting: {start_date} for {duration} days, Budget: RM {budget} (Malaysian Ringgit))
        Travel Style: {travel_style}
        Constraints: {constraints}
        Special Requests: {special_requests}
        
        Agent Plan: {planner_plan}
        
        --- Tool Observations ---
        Maps Data: {maps_result}
        Weather Data: {weather_result}
        Web Search Data: {search_result}
        -------------------------
        
        Generate the final itinerary now.
        """)
    ])

    # Removed StrOutputParser() so we can capture the raw AIMessage to read token counts
    chain = prompt | llm_creative

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
        "search_result": state.get("search_result", "No web data retrieved.")
    })

    # Extract raw content and tokens manually
    raw_content = response.content
    
    # FIX: Gemini's raw content without StrOutputParser is a list of block dicts e.g., [{'type': 'text', 'text': '...'}]
    # We must cleanly extract the actual string before storing it into the global state.
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
        "metrics": current_metrics
    }
