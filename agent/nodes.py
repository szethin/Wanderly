import time
import os
from dotenv import load_dotenv
from typing import cast
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Import State, Prompts, and Schema
from agent.state import WanderlyState
from agent.prompts import PLANNER_PROMPT, GENERATOR_PROMPT
from models.schema import PlannerOutput

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
        ("user", "Destination: {destination}\nStart Date: {start_date}\nDuration: {duration} days\nBudget: {budget}\nStyle: {travel_style}\nConstraints: {constraints}\nSpecial Requests: {special_requests}")
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
        if result.search_query:
            print(f"    -> Crafted Search Query: '{result.search_query}'")
        if result.maps_query:
            print(f"    -> Crafted Map Query: '{result.maps_query}'")

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
            "required_tools": result.required_tools,
            "maps_query": result.maps_query,
            "search_query": result.search_query,
            "metrics": current_metrics # Save telemetry to state
        }

    except Exception as e:
        print(f"❌ [Planner Node] Failed to parse output: {e}")
        # Graceful fallback: Prevent crash by moving forward with no tools
        return {
            "planner_reasoning": "System encountered an error during planning. Executing safe fallback plan without external tools.",   # Provide a fallback reasoning so the UI still has a logical thought process to display
            "planner_plan": ["Fallback: Generate without tools"], 
            "required_tools": [], 
            "maps_query": "",
            "search_query": "",
            "metrics": state.get("metrics", {})
        }


def tool_executor_node(state: WanderlyState) -> dict:
    """
    Node 2: Deterministic Tool Execution. No LLM involved.
    Reads 'required_tools' and triggers actual Python tool functions.
    """
    print("⚙️ [Tool Executor Node] Executing dynamic tools...")

    tools_to_run = state.get("required_tools", [])
    destination = state.get("destination", "Unknown")
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

        # Update telemetry (tool time & tool call count)
        current_metrics.update({"maps_time": time.time() - t0, "maps_calls": 1})

    if "weather" in tools_to_run:
        print("   -> 🌤️ Calling OpenWeather...")
        # Weather tool call start time
        t0 = time.time()

        # Update tool call results
        updates["weather_result"] = get_weather_forecast(destination)

        # Update telemetry (tool time & tool call count)
        current_metrics.update({"weather_time": time.time() - t0, "weather_calls": 1})

    if "tavily" in tools_to_run:
        print("   -> 🔍 Calling Tavily Web Search...")
        # Tavily tool call start time
        t0 = time.time()

        # Update tool call results
        query = state.get("search_query", f"travel guide {destination}")
        updates["search_result"] = search_travel_info(query)

        # Update telemetry (tool time & tool call count)
        current_metrics.update({"tavily_time": time.time() - t0, "tavily_calls": 1})

    return updates


def generator_node(state: WanderlyState) -> dict:
    """
    Node 3: Final Synthesis. Reads all structured tool observations and drafts the itinerary.
    """
    print("✍️ [Generator Node] Synthesizing final itinerary...")
    start_time = time.time() # Start stopwatch

    prompt = ChatPromptTemplate.from_messages([
        ("system", GENERATOR_PROMPT),
        ("user", """
        User Profile:
        Destination: {destination} (Starting: {start_date} for {duration} days, Budget: {budget})
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

    # Extract raw content string and tokens manually
    final_output = response.content
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
