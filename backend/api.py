from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, cast
import uvicorn
import time

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


@app.post("/plan_trip")
async def plan_trip(request: TripRequest):
    """
    REST endpoint to trigger the LangGraph agentic workflow.
    """
    print(f"📥 [API] Received trip planning request for {request.destination} starting {request.start_date}")
    api_start_time = time.time()

    # Construct the initial state dictionary matching WanderlyState schema
    initial_state = {
        # --- Input: User Travel Request ---
        "destination": request.destination,
        "start_date": request.start_date,
        "duration": request.duration,
        "budget": request.budget,
        "travel_style": request.travel_style,
        "constraints": request.constraints,
        "special_requests": request.special_requests,

        # --- Initialize Reflection State Variables ---
        "reflection_feedback": "",
        "need_more_info": False,
        "revision_count": 0,
        "past_queries": [],

        "metrics": {} # Initialize empty metrics dictionary
    }

    try:
        # Runs compiled LangGraph using initial_state as input
        final_state = wanderly_graph.invoke(cast(WanderlyState, initial_state))

        # Calculate Total System Latency
        total_time = time.time() - api_start_time
        metrics = final_state.get("metrics", {})

        # =====================================================
        # CONSOLIDATED TELEMETRY PRINT FOR V1 Baseline LOGGING
        # =====================================================
        print("\n" + "="*50)
        print("📊 WANDERLY METRICS REPORT (V1 Baseline)")
        print("="*50)
        print(f"⏱️  Total Latency: {total_time:.2f}s")
        print(f"   ├─ Planner Time:   {metrics.get('planner_time', 0):.2f}s")
        print(f"   ├─ Tools Time:     (Maps: {metrics.get('maps_time', 0):.2f}s | Weather: {metrics.get('weather_time', 0):.2f}s | Tavily: {metrics.get('tavily_time', 0):.2f}s)")
        print(f"   └─ Generator Time: {metrics.get('generator_time', 0):.2f}s")
        print("-" * 50)

        total_tokens = metrics.get('planner_tokens', 0) + metrics.get('generator_tokens', 0)
        print(f"🪙  Total Tokens:  {total_tokens}")
        print(f"   ├─ Planner:        {metrics.get('planner_tokens', 0)}")
        print(f"   └─ Generator:      {metrics.get('generator_tokens', 0)}")
        
        print("-" * 50)
        print("🛠️  Tool Calls:")
        print(f"   ├─ Maps:    {metrics.get('maps_calls', 0)}")
        print(f"   ├─ Weather: {metrics.get('weather_calls', 0)}")
        print(f"   └─ Tavily:  {metrics.get('tavily_calls', 0)}")
        print("="*50 + "\n")

        # Extract essential outputs for the frontend
        return {
            "status": "success",
            "planner_plan": final_state.get("planner_plan"),
            "planner_reasoning": final_state.get("planner_reasoning"),
            "required_tools": final_state.get("required_tools"),
            "maps_query": final_state.get("maps_query"),
            "search_query": final_state.get("search_query"),
            "itinerary": final_state.get("final_itinerary")
        }

    except Exception as e:
        print(f"❌ [API] Graph execution failed: {e}")
        # Standard HTTP 500 error propagation
        raise HTTPException(status_code=500, detail=str(e))


# Boilerplate to run the server locally if this script is executed directly
if __name__ == "__main__":
    uvicorn.run("backend.api:app", host="0.0.0.0", port=8000, reload=True)