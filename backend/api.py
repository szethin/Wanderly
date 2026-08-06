from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, cast
import uvicorn
import time
import uuid   # Standard library for generating universally unique identifiers
from langchain_core.runnables import RunnableConfig   # LangChain's native type definition for execution configurations

# Import the state
from agent.state import WanderlyState

# Import the compiled graph
from agent.graph import wanderly_graph




# Initialize FastAPI application instance
app = FastAPI(title="Wanderly Agent API", version="1.0")

# Pydantic schema enforcing strict validation for incoming HTTP requests
class TripRequest(BaseModel):
    destination: str
    start_date: str
    duration: int
    budget: float
    travel_style: List[str]
    constraints: List[str]
    special_requests: Optional[str] = ""

    # Optional thread identifier to resume previous sessions
    thread_id: Optional[str] = ""

    # Optional free-form text containing iterative refinement instructions
    user_feedback: Optional[str] = ""


@app.post("/plan_trip")
async def plan_trip(request: TripRequest):
    """
    REST endpoint to trigger the LangGraph agentic workflow.
    Supports both initial itinerary generation & iterative refinement.
    """
    print(f"📥 [API] Received trip planning request for {request.destination} starting {request.start_date}")
    api_start_time = time.time()

    # --- Session Management ---
    # Generate a new random UUID if the clientt doesn't provide an existing thread_id
    active_thread_id = request.thread_id if request.thread_id else str(uuid.uuid4())

    # RunnableConfig: A LangChain native dictionary structure used to pass metadata to tools & checkpointers
    # Passing "thread_id" under "configurable" tells MemorySaver to fetch the correct historical state
    config: RunnableConfig = {
        "configurable": {
            "thread_id": active_thread_id
        }
    }

    # --- State Routing ---
    # Determine if this is a brand-new generation or a follow-up refinement
    if request.user_feedback:
        print(f"🔄 [API] Iterative refinement detected for thread {active_thread_id}")

        # LangGraph automatically merges this dictionary into the saved historical state.
        input_state = {
            # Inherit ALL sidebar settings to capture any UI slider/checkbox changes made during the chat turn
            "destination": request.destination,
            "start_date": request.start_date,
            "duration": request.duration,
            "budget": request.budget,
            "travel_style": request.travel_style,
            "constraints": request.constraints,
            "special_requests": request.special_requests,

            "user_feedback": request.user_feedback,
            
            # We MUST reset these safeguard variables for every new chat turn. 
            # Otherwise, the agent inherits loop limits from the previous interaction and immediately triggers fallbacks.
            "revision_count": 0,        
            "past_queries": [],         
            "reflection_logs": [],

            # Reset telemetry metrics to prevent wrong token accouting
            "metrics": {},
            "error_msg": ""  # Reset error state for the new turn       
        }

    else:
        print(f"🆕 [API] Initial generation detected for thread {active_thread_id}")

        # First-time run requires constructing the full comprehensive baseline state dictionary matching WanderlyState schema
        input_state = {
            # --- Input: User Travel Request ---
            "destination": request.destination,
            "start_date": request.start_date,
            "duration": request.duration,
            "budget": request.budget,
            "travel_style": request.travel_style,
            "constraints": request.constraints,
            "special_requests": request.special_requests,
            "user_feedback": "",

            "weather_query": request.destination,  # NEW: Initialize with raw user input, let Agent fix it if it fails

            # --- Initialize Reflection State Variables ---
            "reflection_logs": [],
            "need_more_info": False,
            "revision_count": 0,
            "past_queries": [],

            # --- Initialize Static Backup Variables ---
            "planner_initial_tools": [],
            "planner_initial_maps_query": "",
            "planner_initial_search_query": "",
            "planner_initial_weather_query": "",

            "metrics": {}, # Initialize empty metrics dictionary
            "error_msg": ""  # Reset error state for the new turn  
        }

    try:
        # Pass both the {dynamic input_state} & {memory configuration}
        # LangGraph automatically handles saving the state post-execution
        final_state = wanderly_graph.invoke(cast(WanderlyState, input_state), config=config)

        # Calculate Total System Latency
        total_time = time.time() - api_start_time
        metrics = final_state.get("metrics", {})

        # =====================================================
        # CONSOLIDATED TELEMETRY PRINT FOR V2 LOGGING
        # =====================================================
        print("\n" + "="*50)
        print("📊 WANDERLY METRICS REPORT (V3 Iterative Refinement)")
        print("="*50)
        print(f"⏱️  Total Latency: {total_time:.2f}s")
        print(f"   ├─ Planner Time:   {metrics.get('planner_time', 0):.2f}s")
        print(f"   ├─ Tools Time:     (Maps: {metrics.get('maps_time', 0):.2f}s | Weather: {metrics.get('weather_time', 0):.2f}s | Tavily: {metrics.get('tavily_time', 0):.2f}s)")
        print(f"   ├─ Reflection Time: {metrics.get('reflection_time', 0):.2f}s")
        print(f"   └─ Generator Time: {metrics.get('generator_time', 0):.2f}s")
        print("-" * 50)

        total_tokens = metrics.get('planner_tokens', 0) + metrics.get('reflection_tokens', 0) + metrics.get('generator_tokens', 0)
        print(f"🪙  Total Tokens:  {total_tokens}")
        print(f"   ├─ Planner:        {metrics.get('planner_tokens', 0)}")
        print(f"   ├─ Reflection:      {metrics.get('reflection_tokens', 0)}")
        print(f"   └─ Generator:      {metrics.get('generator_tokens', 0)}")
        
        print("-" * 50)
        print("🛠️  Tool Calls:")
        print(f"   ├─ Maps:    {metrics.get('maps_calls', 0)}")
        print(f"   ├─ Weather: {metrics.get('weather_calls', 0)}")
        print(f"   └─ Tavily:  {metrics.get('tavily_calls', 0)}")
        print("="*50 + "\n")

        # =====================================================
        # DYNAMIC PAYLOAD CONSTRUCTION (Decoupling State from UI)
        # =====================================================
        graph_itinerary = final_state.get("final_itinerary", "")
        graph_error = final_state.get("error_msg", "")

        # If an error exists, prepend it to the itinerary STRICTLY for the API response payload.
        # The LangGraph MemorySaver remains completely untouched and unpolluted.
        display_itinerary = f"{graph_error}\n\n---\n\n{graph_itinerary}" if graph_error else graph_itinerary

        # Extract essential outputs for the frontend
        return {
            "status": "success",
            "thread_id": active_thread_id,  # Expose the session ID back to the frontend

            "planner_plan": final_state.get("planner_plan"),
            "planner_reasoning": final_state.get("planner_reasoning"),

            # These variables might have been overwritten by the Reflection Node
            "required_tools": final_state.get("required_tools"),
            "maps_query": final_state.get("maps_query"),
            "search_query": final_state.get("search_query"),
            "weather_query": final_state.get("weather_query"),

            # Reflection variables
            "reflection_logs": final_state.get("reflection_logs"),
            "revision_count": final_state.get("revision_count"),
            "past_queries": final_state.get("past_queries"),

            # --- Immutable trace data for Planner UI ---
            "planner_initial_tools": final_state.get("planner_initial_tools"),
            "planner_initial_maps_query": final_state.get("planner_initial_maps_query"),
            "planner_initial_search_query": final_state.get("planner_initial_search_query"),
            "planner_initial_weather_query": final_state.get("planner_initial_weather_query"),

            # Final itinerary
            "itinerary": display_itinerary
        }

    except Exception as e:
        print(f"❌ [API] Graph execution failed: {e}")
        # Standard HTTP 500 error propagation
        raise HTTPException(status_code=500, detail=str(e))


# Boilerplate to run the server locally if this script is executed directly
if __name__ == "__main__":
    uvicorn.run("backend.api:app", host="0.0.0.0", port=8000, reload=True)