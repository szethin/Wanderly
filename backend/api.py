from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, cast
import uvicorn

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

    # Construct the initial state dictionary matching WanderlyState schema
    initial_state = {
        "destination": request.destination,
        "start_date": request.start_date,
        "duration": request.duration,
        "budget": request.budget,
        "travel_style": request.travel_style,
        "constraints": request.constraints,
        "special_requests": request.special_requests,
    }

    try:
        # Runs compiled LangGraph from START to END
        final_state = wanderly_graph.invoke(cast(WanderlyState, initial_state))

        # Extract essential outputs for the frontend
        return {
            "status": "success",
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