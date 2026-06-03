"""
Conditional edges for the DeepX LangGraph.

Routing logic (deterministic, no infinite loop):

  - next_node = "tools"  → tools_node (explicit)
  - next_node = "end"   → END (explicit)
  - next_node = anything else (or None) → check last assistant message

  Last assistant message check:
    - has tool_calls → "tools"  (execute tools, then loop)
    - otherwise     → "end"    (conversation complete)

This ensures:
  - tools_node returns next_node="agent" (→ merged into state)
  - BUT decide_next ignores "agent" (only handles "tools"/"end" explicitly)
  - Next call: next_node=None → check messages → no tool_calls → "end"
  → No infinite loop ✓
"""
from __future__ import annotations

from typing import Literal

from deepx.graph.state import DeepXState


def decide_next(state: DeepXState) -> Literal["tools", "agent", "plan", "compress", "model_switch", "end"]:
    """
    Decide the next node.

    Only respects next_node when explicitly "tools" or "end".
    Otherwise, always checks the actual last assistant message content.
    This prevents infinite loops from nodes that set next_node="agent".
    """
    explicit = state.get("next_node")

    # Only respect explicit routing for explicit targets
    if explicit in ("tools", "end"):
        return explicit

    # For all other values (including "agent", "plan", None, etc.)
    # → check the actual last assistant message
    messages: list[dict] = state.get("messages", [])
    if messages:
        last = messages[-1]
        if last.get("role") == "assistant":
            # Check for tool calls in the message
            if last.get("tool_calls"):
                return "tools"
            # No tool calls → conversation is complete
            return "end"

    # No messages yet
    return "end"