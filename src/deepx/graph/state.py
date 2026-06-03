"""DeepXState — typed state for the LangGraph workflow."""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph import add_messages


class DeepXState(TypedDict, total=False):
    """
    State passed through the DeepX LangGraph.

    Fields are optional because they are accumulated progressively.
    """

    # Conversation
    messages: Annotated[list[dict], add_messages]

    # Tool execution
    tool_calls: list[dict] | None  # Pending tool calls from last LLM response
    tool_results: list[dict] | None  # Results of tool executions

    # Routing
    model: str  # "flash" or "pro"
    next_node: str | None  # Set by conditional edges

    # Planning
    task: str | None  # User's current task
    subtasks: list[dict] | None  # Parsed from CreatePlan
    subtask_results: list[Any] | None

    # Context management
    context_budget: int  # Remaining context budget in tokens
    compress_triggered: bool  # Whether compression was triggered
    compressed_history: list[dict] | None  # Result of compression

    # Session
    session_id: str
    round: int  # Current round number

    # Usage
    total_input_tokens: int
    total_output_tokens: int
    total_cache_hits: int


def initial_state(session_id: str) -> DeepXState:
    """Create an initial state for a new session."""
    return DeepXState(
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