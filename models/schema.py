from pydantic import BaseModel, Field
from typing import List

# Pydantic BaseModel: The industry standard for data validation and schema definition in Python.
class PlannerOutput(BaseModel):
    """
    Structured schema enforcing the output format for the Planner Node.
    """

    # Field(): Adds rich metadata and descriptions that guide the LLM on how to populate each attribute.
    planner_reasoning: str = Field(
        description="Concise logical reasoning for selecting or skipping specific tools based on user budger and constraints."
    )

    planner_plan: List[str] = Field(
        description="Step-by-step breakdown of subtasks the agent needs to perform to satisfy the user request."
    )

    required_tools: List[str] = Field(
        description="List of external tools to call. Must strictly contain choices from: ['maps', 'weather', 'tavily']. If no tools are needed, return an empty list."
    )

    maps_query: str = Field(
        default="attractions",
        description="If 'maps' is selected, determine the best place type to search based on user style (e.g., 'restaurants', 'museums', 'attractions')."
    )

    search_query: str = Field(
        default="",
        description="If 'tavily' is selected, write a highly optimized search engine query to fetch the missing info (e.g. historical climate, niche constraints). Leave empty if tavily is not used."
    )