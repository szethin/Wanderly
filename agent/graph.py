from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from agent.state import WanderlyState
from agent.nodes import planner_node, tool_executor_node, reflection_node, generator_node


def should_continue_planning(state: WanderlyState) -> str:
    """
    Conditional router function.
    Determines the next node dynamically based on the reflection flag in global state.
    """

    # Read the boolean flag set by the reflection node
    need_more_info = state.get("need_more_info", False)

    if need_more_info:
        print("🔄 [Router] Reflection requested more info. Routing back to Tool Executor.")
        return "tool_executor"
    else:
        return "generator"



def build_graph():
    """
    Constructs and compile the Wanderly StateGraph with cyclical reflection loops and persistent memory.
    """
    print("🕸️ [Graph] Assembling Wanderly StateGraph (V3)...")

    # 1. Initial the graph with WanderlyState, so it can pass it between all nodes
    builder = StateGraph(WanderlyState)

    # 2. Add Nodes
    builder.add_node("planner", planner_node)
    builder.add_node("tool_executor", tool_executor_node)
    builder.add_node("reflection", reflection_node)
    builder.add_node("generator", generator_node)

    # 3. Define the Static Control Flow (Fixed Edges)
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "tool_executor") # Planner outputs initial required_tools -> Pass to Executor
    builder.add_edge("tool_executor", "reflection") # After executing tools, ALWAYS route observations to Reflection for QA evaluation

    # 4. Define the Dynamic Control Flow (Conditional Edges)
    builder.add_conditional_edges(
        "reflection",   # The node where the decision is made
        should_continue_planning,    # The routing function returning the target node's string name
        
        # Explicit path map (Dictionary). 
        # Required for LangGraph's Mermaid visualizer to statically draw the cyclical edges.
        # Format: {"return_value_from_router": "actual_target_node_name"}
        {
            "tool_executor": "tool_executor",
            "generator": "generator"
        }
    )


    # 5. Exit point
    builder.add_edge("generator", END)

    # 6. Initialize the checkpointer instance
    # MemorySaver saves the graph state to RAM after every node executes. 
    # This prevents data loss between user chat turns.
    memory = MemorySaver()

    # 7. Compile the graph & bind the checkpointer
    # passing checkpointer=memory turns the graph from a stateless script into a stateful agent
    graph = builder.compile(checkpointer=memory)

    print("✅ [Graph] V3 Compilation successful (Memory Enabled).")
    return graph

# Instantiate the compiled graph so it can be imported directly by the FastAPI backend
wanderly_graph = build_graph()