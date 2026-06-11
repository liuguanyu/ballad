"""
Conditional edges for the DeepX LangGraph.

Routing logic:

  Explicit next_node from node return values:
    "tools"       → tools_node (execute pending tool calls)
    "plan"        → plan_node (decompose into parallel sub-tasks)
    "compress"    → compress_node (context exceeded threshold)
    "model_switch" → model_switch_node (flash → pro upgrade)
    "end"         → END (conversation complete)

  Fallback when next_node is None or "agent":
    - Check last user message for planning keywords → "plan"
    - Check last assistant message for tool_calls → "tools"
    - Otherwise → "end"

This ensures no infinite loops:
  - tools_node returns next_node=None → next decide_next → checks messages
  - subagents_node returns next_node=None → back to agent
"""
from __future__ import annotations

from typing import Literal

from deepx.graph.state import DeepXState


def decide_next(state: DeepXState) -> Literal["tools", "agent", "plan", "compress", "model_switch", "end"]:
    """
    Decide the next node from current state.

    Priority:
      1. Explicit next_node from node return value (highest)
      2. Last user message contains planning keywords → "plan"
      3. Last assistant message has tool_calls → "tools"
      4. Otherwise → "end"
    """
    explicit = state.get("next_node")

    # Explicit routing (set by node return values)
    if explicit in ("tools", "end", "plan", "compress", "model_switch", "agent"):
        if explicit == "agent":
            explicit = None  # fall through to message-based check
        else:
            return explicit

    messages: list[dict] = state.get("messages", [])

    # Check last user message for planning keywords
    for m in reversed(messages):
        role = _get_role(m)
        content = _get_content(m)
        if role == "user" and content:
            lower = content.lower()
            plan_keywords = [
                "plan", "replan", "refactor", "re-factor", "re factor",
                "重构", "implement", "实现", "build", "建设",
                "migrate", "迁移", "upgrade", "升级",
                "parallel", "parallelize", "并行", "同时",
                "multi-step", "多步", "split", "分解", "decompose",
                "do these in parallel", "run these in parallel",
            ]
            if any(kw in lower for kw in plan_keywords):
                return "plan"
            break  # found last user message, stop checking

    # Check last assistant message for tool calls
    for m in reversed(messages):
        role = _get_role(m)
        if role == "assistant":
            if _has_tool_calls(m):
                return "tools"
            return "end"

    return "end"


def _get_role(msg) -> str:
    if isinstance(msg, dict):
        return msg.get("role", "")
    return getattr(msg, "type", "")


def _get_content(msg) -> str:
    if isinstance(msg, dict):
        return msg.get("content", "")
    return getattr(msg, "content", "")


def _has_tool_calls(msg) -> bool:
    if isinstance(msg, dict):
        return bool(msg.get("tool_calls"))
    return bool(getattr(msg, "tool_calls", None))