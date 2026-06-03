"""
LangGraph workflow compiler for DeepX.

Streaming via stream_mode="custom":
  astream_events(input={"messages": [{"role": "user", "content": "..."}]})
  
  Each event is a dict like:
    {"type": "custom", "ns": ("agent",), "data": {"type": "token", "content": "hi"}}
  
  The TUI subscribes to these events and updates in real-time.
"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from deepx.graph.edges import decide_next
from deepx.graph.nodes import (
    agent_node,
    compress_node,
    model_switch_node,
    plan_node,
    subagents_node,
    tools_node,
)
from deepx.graph.state import DeepXState


def build_workflow(session_id: str):
    workflow = StateGraph(DeepXState)

    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tools_node)
    workflow.add_node("plan", plan_node)
    workflow.add_node("subagents", subagents_node)
    workflow.add_node("compress", compress_node)
    workflow.add_node("model_switch", model_switch_node)

    workflow.add_edge(START, "agent")
    workflow.add_edge("tools", "agent")
    workflow.add_edge("subagents", "agent")
    workflow.add_edge("compress", "agent")
    workflow.add_edge("model_switch", "agent")
    workflow.add_edge("plan", "subagents")

    workflow.add_conditional_edges(
        "agent",
        decide_next,
        {
            "tools": "tools",
            "agent": "agent",
            "plan": "plan",
            "compress": "compress",
            "model_switch": "model_switch",
            "end": END,
        },
    )

    checkpointer = MemorySaver()
    app = workflow.compile(checkpointer=checkpointer)
    return app


def get_initial_state(session_id: str) -> DeepXState:
    state = DeepXState(
        messages=[],
        model="flash",
        next_node=None,
        context_budget=200_000,
        compress_triggered=False,
        session_id=session_id,
        round=0,
        total_input_tokens=0,
        total_output_tokens=0,
        total_cache_hits=0,
    )
    state["_mode"] = "review"
    state["_total_input_tokens"] = 0
    state["_total_output_tokens"] = 0
    state["_total_cache_hits"] = 0
    return state


__all__ = ["build_workflow", "get_initial_state"]