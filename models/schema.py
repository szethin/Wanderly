from pydantic import BaseModel, Field
from typing import List

# Pydantic BaseModel: The industry standard for data validation and schema definition in Python.
class PlannerOutput(BaseModel):
    """
    Structured schema enforcing the output format for the Planner Node.
    """

    # Field(): Adds rich metadata and descriptions that guide the LLM on how to populate each attribute.
    required_tools: List[str] = Field(
        description="List of external tools to call. Must strictly contain choices from: ['maps', 'weather', 'tavily']. If no tools are needed, return an empty list."
    )

    reasoning: str = Field(
        description="Concise logical reasoning for selecting or skipping specific tools based on user budger and constraints."
    )

    planner_plan: List[str] = Field(
        description="Step-by-step breakdown of subtasks the agent needs to perform to satisfy the user request."
    )