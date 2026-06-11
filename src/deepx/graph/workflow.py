"""
DeepX LangGraph workflow — multi-agent with parallel sub-task execution.

Architecture:
  Main graph:
    START → agent → [tools / plan / compress / model_switch / END]
                   ↑
              subagents ← plan

  Parallel sub-agents via Send():
    plan_node decomposes task → subtasks[]
    subagents_node uses Send() to invoke agent_node concurrently per subtask
    Results collected in subtask_results[]

Streaming (dual-stream):
  - astream(stream_mode=values): state snapshots → LLM tokens in messages[]
  - astream(stream_mode=custom): writer() events → tool_call, routing, usage, etc.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.constants import Send
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

if TYPE_CHECKING:
    from langgraph.types import StreamWriter


__all__ = ["build_workflow", "get_initial_state", "DeepXState"]


def _route_subagents(state: DeepXState) -> Any:
    """
    Routing function for subagents_node.
    
    Returns Send() list for parallel execution, or END if no subtasks.
    LangGraph executes Send() targets concurrently (fan-out).
    Each Send() result becomes a separate subgraph run with its own checkpoint.
    """
    subtasks: list[dict] = state.get("subtasks") or []
    if not subtasks:
        return END

    return [
        Send(
            "agent",  # reuse agent_node for sub-agents
            _build_subagent_state(state, i, subtask),
        )
        for i, subtask in enumerate(subtasks)
    ]


def _build_subagent_state(
    parent: DeepXState,
    idx: int,
    subtask: dict[str, Any],
) -> dict[str, Any]:
    """Build isolated state for a single sub-agent invocation."""
    messages: list[dict] = parent.get("messages", [])
    
    # Last user message is the task input
    last_user_idx = -1
    for i, m in enumerate(messages):
        role = _get_role(m)
        if role == "user":
            last_user_idx = i

    # Sub-agent system prompt
    task_desc = subtask.get("description", "")
    target_files = subtask.get("target_files", [])
    files_hint = "\nTarget files:\n" + "\n".join(f"  - {f}" for f in target_files) if target_files else ""
    mode = parent.get("_mode", "auto")

    system_prompt = f"""\
You are a specialized sub-agent. Complete your assigned task precisely.

**Your Task**: {task_desc}{files_hint}

**Mode: {mode.upper()}**
- auto: execute automatically
- review: confirm destructive actions
- plan: analyze only, no writes

Focus only on your task. Do not expand scope.
Report results clearly and concisely."""

    return {
        # Isolated message history
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Complete this task:\n{task_desc}"},
        ],
        # Task metadata (not merged back to parent)
        "task": task_desc,
        "subtask_id": subtask.get("id", f"task-{idx}"),
        "subtask_idx": idx,
        "subtasks": None,
        "subtask_results": None,
        # Routing
        "model": parent.get("model", "flash"),
        "next_node": None,
        "round": 0,
        "tool_calls": None,
        "tool_results": None,
        # Context
        "context_budget": parent.get("context_budget", 200_000),
        "compress_triggered": False,
        "compressed_history": None,
        "session_id": f"{parent.get('session_id', '')}-sub-{idx}",
        # Usage (isolated per sub-agent)
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_hits": 0,
        # Private fields (not merged by LangGraph)
        "_mode": mode,
        "_total_input_tokens": 0,
        "_total_output_tokens": 0,
        "_total_cache_hits": 0,
    }


def build_workflow(session_id: str):
    """
    Build and compile the main DeepX LangGraph.

    Graph edges:
      START → agent
      tools → agent      (loop)
      compress → agent    (loop)
      model_switch → agent (loop)
      plan → subagents   (fan-out)
      agent → [conditional routing]
        "tools"  → tools
        "plan"   → plan
        "end"    → END
        (default from decide_next: no tool_calls → end)
    """
    workflow = StateGraph(DeepXState)

    # Nodes
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tools_node)
    workflow.add_node("plan", plan_node)
    workflow.add_node("subagents", subagents_node)
    workflow.add_node("compress", compress_node)
    workflow.add_node("model_switch", model_switch_node)

    # Fixed edges
    workflow.add_edge(START, "agent")
    workflow.add_edge("tools", "agent")
    workflow.add_edge("compress", "agent")
    workflow.add_edge("model_switch", "agent")
    workflow.add_edge("plan", "subagents")

    # Agent → routing
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

    # Subagents → parallel Send() fan-out
    workflow.add_conditional_edges(
        "subagents",
        _route_subagents,
        {"agent": "agent", END: END},
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


def _get_role(msg) -> str:
    if isinstance(msg, dict):
        return msg.get("role", "")
    return getattr(msg, "type", "")