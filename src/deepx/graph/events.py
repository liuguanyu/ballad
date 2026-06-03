"""
Streaming events emitted by LangGraph nodes for real-time TUI display.

These are yielded by agent_node (and other nodes) as async generators.
LangGraph's astream() passes them through to the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StreamEvent:
    """
    A single event from a node's async generator.

    The TUI subscribes to astream() and processes these events
    in real-time — tokens appear as they arrive.
    """

    # Event type tags
    EVENT_TOKEN = "token"           # LLM text token (incremental)
    EVENT_REASONING = "reasoning"    # Thinking/reasoning token
    EVENT_TOOL_CALL = "tool_call"   # LLM requests a tool
    EVENT_TOOL_RESULT = "tool_result"  # Tool execution result
    EVENT_USAGE = "usage"            # Usage statistics at stream end
    EVENT_ERROR = "error"            # Something went wrong
    EVENT_NODE_DONE = "node_done"    # Node finished, next_node set
    EVENT_COMPRESS = "compress"      # Context compression triggered
    EVENT_ROUTING = "routing"        # Model routing decision

    # Which node produced this event
    node: str = "agent"
    # Event type: one of the EVENT_* constants above
    type: str = EVENT_TOKEN
    # For token/reasoning events
    content: str = ""
    # For tool_call events
    tool_name: str = ""
    tool_id: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    # For usage events
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_tokens: int = 0
    # For routing events
    model: str = ""
    reason: str = ""
    # Error message
    error: str = ""
    # Next node routing hint (set by agent_node)
    next_node: str | None = None

    @classmethod
    def token(cls, content: str, node: str = "agent") -> "StreamEvent":
        return cls(node=node, type=cls.EVENT_TOKEN, content=content)

    @classmethod
    def reasoning(cls, content: str) -> "StreamEvent":
        return cls(node="agent", type=cls.EVENT_REASONING, content=content)

    @classmethod
    def tool_call(cls, tool_id: str, tool_name: str, tool_args: dict) -> "StreamEvent":
        return cls(
            node="agent",
            type=cls.EVENT_TOOL_CALL,
            tool_id=tool_id,
            tool_name=tool_name,
            tool_args=tool_args,
        )

    @classmethod
    def tool_result(cls, tool_name: str, result: str, tool_id: str = "") -> "StreamEvent":
        return cls(
            node="tools",
            type=cls.EVENT_TOOL_RESULT,
            tool_name=tool_name,
            content=result[:200],
        )

    @classmethod
    def usage(
        cls,
        input_tokens: int,
        output_tokens: int,
        cache_hit_tokens: int,
    ) -> "StreamEvent":
        return cls(
            node="agent",
            type=cls.EVENT_USAGE,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_hit_tokens=cache_hit_tokens,
        )

    @classmethod
    def error(cls, message: str, node: str = "agent") -> "StreamEvent":
        return cls(node=node, type=cls.EVENT_ERROR, error=message)

    @classmethod
    def compress_triggered(cls) -> "StreamEvent":
        return cls(node="agent", type=cls.EVENT_COMPRESS, content="Compressing context...")

    @classmethod
    def routing(cls, model: str, reason: str) -> "StreamEvent":
        return cls(node="agent", type=cls.EVENT_ROUTING, model=model, reason=reason)