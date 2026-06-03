"""
LangGraph workflow compiler for DeepX.

Builds the complete ReAct loop with:
  START → agent → [tools / plan / compress / model_switch / END]
              ↑___________________________|

Key design:
- agent_node: LLM call → response + tool_calls
- tools_node: execute tools → results → back to agent
- Each node sets state["next_node"] to control routing
"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from deepx.graph.state import DeepXState, initial_state
from deepx.graph.edges import decide_next
from deepx.graph.nodes import (
    agent_node,
    compress_node,
    model_switch_node,
    plan_node,
    subagents_node,
    tools_node,
)


def build_workflow(session_id: str):
    """
    Build and compile the DeepX LangGraph workflow.

    Graph structure:
        START → agent → [conditional on next_node]
          ├─ "tools"  → tools  → agent
          ├─ "plan"   → plan   → subagents → agent
          ├─ "compress" → compress → agent
          ├─ "model_switch" → model_switch → agent
          └─ "end" → END
    """
    workflow = StateGraph(DeepXState)

    # ── Nodes ────────────────────────────────────────────────────────────────
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tools_node)
    workflow.add_node("plan", plan_node)
    workflow.add_node("subagents", subagents_node)
    workflow.add_node("compress", compress_node)
    workflow.add_node("model_switch", model_switch_node)

    # ── Edges ────────────────────────────────────────────────────────────────
    # Entry point
    workflow.add_edge(START, "agent")

    # Fixed edges: after these nodes, always return to agent to continue
    workflow.add_edge("tools", "agent")
    workflow.add_edge("subagents", "agent")
    workflow.add_edge("compress", "agent")
    workflow.add_edge("model_switch", "agent")
    workflow.add_edge("plan", "subagents")  # plan → parallel sub-agents

    # Conditional edge: agent decides where to go next
    # Returns: "tools" | "agent" | "plan" | "compress" | "model_switch" | "end"
    workflow.add_conditional_edges(
        "agent",
        decide_next,
        {
            "tools": "tools",
            "agent": "agent",        # shouldn't happen from agent, but handled
            "plan": "plan",
            "compress": "compress",
            "model_switch": "model_switch",
            "end": END,
        },
    )

    # ── Compile ──────────────────────────────────────────────────────────────
    checkpointer = MemorySaver()
    app = workflow.compile(checkpointer=checkpointer)
    return app


def get_initial_state(session_id: str) -> DeepXState:
    """Get initial state for a new session."""
    state = initial_state(session_id)
    state["_mode"] = "review"
    state["_total_input_tokens"] = 0
    state["_total_output_tokens"] = 0
    state["_total_cache_hits"] = 0
    return state