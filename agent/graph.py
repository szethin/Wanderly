from langgraph.graph import StateGraph, START, END
from agent.state import WanderlyState
from agent.nodes import planner_node, tool_executor_node, generator_node

def build_graph():
    """
    Constructs and compile the Wanderly StateGraph.
    """
    print("🕸️ [Graph] Assembling Wanderly StateGraph...")

    # 1. Initial the graph with WanderlyState, so it can pass it between all nodes
    builder = StateGraph(WanderlyState)

    # 2. Add Nodes
    builder.add_node("planner", planner_node)
    builder.add_node("tool_executor", tool_executor_node)
    builder.add_node("generator", generator_node)

    # 3. Add Edges
    builder.add_edge(START, "planner")

    # Baseline linear flow: Planner -> Tools -> Generator
    builder.add_edge("planner", "tool_executor")
    builder.add_edge("tool_executor", "generator")

    # Exit point
    builder.add_edge("generator", END)

    # 4. Compile the graph
    graph = builder.compile()

    print("✅ [Graph] Compilation successful.")
    return graph

# Instantiate the compiled graph so it can be imported directly by the FastAPI backend
wanderly_graph = build_graph()