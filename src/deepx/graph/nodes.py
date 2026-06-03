"""
LangGraph nodes for the DeepX workflow.

Custom streaming via stream_mode="custom":
  - Each node accepts a `writer: StreamWriter` parameter (injected by LangGraph)
  - Use writer({"type": "custom", "ns": (node,), "data": {...}}) to emit real-time events
  - Return a dict normally (LangGraph state update)

Event data types (emitted via writer):
  - token:       {"type": "token", "content": str}
  - reasoning:   {"type": "reasoning", "content": str}
  - tool_call:   {"type": "tool_call", "tool_id", "tool_name", "tool_args": dict}
  - tool_result: {"type": "tool_result", "tool_name", "result", "tool_id"}
  - usage:       {"type": "usage", "input", "output", "cache": int}
  - routing:     {"type": "routing", "model", "reason": str}
  - compress:    {"type": "compress"}
  - error:       {"type": "error", "message": str}
  - state:       {"type": "state", "status": str, ...}
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from deepx.agent.router import route_model
from deepx.config.settings import get_settings
from deepx.graph.state import DeepXState
from deepx.llm.client import LLMClient, Message
from deepx.tools.base import ToolRegistry

if TYPE_CHECKING:
    from langgraph.types import StreamWriter

logger = logging.getLogger(__name__)

MAX_ROUNDS = 100


def _emit(writer: "StreamWriter | None", node: str, data: dict) -> None:
    """Emit a custom stream event via writer (non-blocking)."""
    if writer is None:
        return
    try:
        writer({"type": "custom", "ns": (node,), "data": data})
    except Exception:
        pass  # Never let a stream failure break the agent


def _normalize_message(msg) -> dict[str, Any]:
    """Convert LangChain message objects to dict format."""
    if isinstance(msg, dict):
        return msg
    if hasattr(msg, "content") and hasattr(msg, "type"):
        role = {"human": "user", "ai": "assistant", "tool": "tool", "system": "system"}.get(msg.type, msg.type)
        result = {"role": role, "content": msg.content}
        if hasattr(msg, "tool_call_id"):
            result["tool_call_id"] = msg.tool_call_id
        if hasattr(msg, "name"):
            result["name"] = msg.name
        if hasattr(msg, "tool_calls"):
            result["tool_calls"] = msg.tool_calls
        return result
    return {"role": "user", "content": str(msg)}


def _build_messages_for_llm(messages: list) -> list[Message]:
    """Convert state messages (may be LC objects or dicts) to LLM Message list."""
    result = []
    for m in messages:
        d = _normalize_message(m)
        # Skip system messages (already added separately)
        if d.get("role") == "system":
            continue
        result.append(Message(**d))
    return result


# ═════════════════════════════════════════════════════════════════════════════
# agent_node — core ReAct LLM call
# ═════════════════════════════════════════════════════════════════════════════

async def agent_node(
    state: DeepXState,
    writer: "StreamWriter | None" = None,
) -> dict[str, Any]:
    """
    Main Agent node — calls LLM with current history, emits stream events.

    The writer param is injected by LangGraph when stream_mode="custom".
    Use astream_events() on the TUI side to receive these events in real-time.
    """
    settings = get_settings()
    round_num = state.get("round", 0) + 1

    if round_num > MAX_ROUNDS:
        _emit(writer, "agent", {"type": "error", "message": "Max rounds reached"})
        return {
            "messages": [{"role": "assistant", "content": "[Max rounds reached.]"}],
            "next_node": "end",
            "round": round_num,
            "model": state.get("model", "flash"),
        }

    messages: list[dict] = state.get("messages", [])
    model_name = state.get("model", "flash")

    # Zero-token routing
    if model_name == "flash" and len(messages) >= 2:
        last = messages[-1] if messages else {}
        tail = str(last.get("content", ""))[:200]
        suggested = route_model(tail)
        if suggested == "pro":
            model_name = "pro"
            _emit(writer, "agent", {"type": "routing", "model": "pro", "reason": "zero-token heuristic"})

    model_cfg = settings.model_for(model_name)
    system_prompt = _build_system_prompt(state.get("_mode", "review"))
    llm_messages = [Message(role="system", content=system_prompt)]
    llm_messages.extend(_build_messages_for_llm(messages))

    tool_specs = ToolRegistry.specs()
    llm = LLMClient(api_key=model_cfg.api_key, base_url=model_cfg.base_url)

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls_accumulated: list[dict] = []
    input_tokens = 0
    output_tokens = 0
    cache_hit_tokens = 0
    error_msg: str | None = None

    try:
        async for chunk in llm.chat(
            messages=llm_messages,
            model=model_cfg,
            tools=tool_specs or None,
            reasoning_effort=model_cfg.reasoning_effort,
            stream=True,
        ):
            if chunk.error:
                error_msg = chunk.error
                _emit(writer, "agent", {"type": "error", "message": chunk.error})
                break

            if chunk.content:
                content_parts.append(chunk.content)
                _emit(writer, "agent", {"type": "token", "content": chunk.content})

            if chunk.reasoning:
                reasoning_parts.append(chunk.reasoning)
                _emit(writer, "agent", {"type": "reasoning", "content": chunk.reasoning})

            if chunk.tool_call and chunk.tool_call.name:
                args_raw = chunk.tool_call.arguments
                if isinstance(args_raw, str):
                    try:
                        args_raw = json.loads(args_raw) if args_raw else {}
                    except json.JSONDecodeError:
                        args_raw = {"_raw": args_raw}
                elif not isinstance(args_raw, dict):
                    args_raw = {"_raw": str(args_raw)}

                existing = next(
                    (tc for tc in tool_calls_accumulated
                     if tc.get("id") == chunk.tool_call.id),
                    None,
                )
                if existing is None:
                    tc_entry = {
                        "id": chunk.tool_call.id,
                        "type": "function",
                        "function": {"name": chunk.tool_call.name, "arguments": args_raw},
                    }
                    tool_calls_accumulated.append(tc_entry)
                    _emit(writer, "agent", {
                        "type": "tool_call",
                        "tool_id": chunk.tool_call.id,
                        "tool_name": chunk.tool_call.name,
                        "tool_args": args_raw,
                    })
                else:
                    existing["function"]["arguments"] = args_raw

            if chunk.done and chunk.usage:
                input_tokens = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens
                cache_hit_tokens = chunk.usage.prompt_cache_hit_tokens
                _emit(writer, "agent", {
                    "type": "usage",
                    "input": input_tokens,
                    "output": output_tokens,
                    "cache": cache_hit_tokens,
                })

    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        error_msg = str(e)
        _emit(writer, "agent", {"type": "error", "message": str(e)})

    await llm.close()

    if error_msg and not content_parts:
        return {
            "messages": [{"role": "assistant", "content": f"[Error: {error_msg}]"}],
            "next_node": "end",
            "round": round_num,
            "model": model_name,
        }

    full_content = "".join(content_parts)
    full_reasoning = "".join(reasoning_parts)
    next_node = "tools" if tool_calls_accumulated else "end"

    assistant_msg: dict[str, Any] = {"role": "assistant", "content": full_content}
    if full_reasoning:
        assistant_msg["reasoning_content"] = full_reasoning
    if tool_calls_accumulated:
        assistant_msg["tool_calls"] = tool_calls_accumulated

    return {
        "messages": [assistant_msg],
        "tool_calls": tool_calls_accumulated or None,
        "next_node": next_node,
        "round": round_num,
        "model": model_name,
        "_total_input_tokens": state.get("_total_input_tokens", 0) + input_tokens,
        "_total_output_tokens": state.get("_total_output_tokens", 0) + output_tokens,
        "_total_cache_hits": state.get("_total_cache_hits", 0) + cache_hit_tokens,
    }


# ═════════════════════════════════════════════════════════════════════════════
# tools_node — execute tool calls
# ═════════════════════════════════════════════════════════════════════════════

async def tools_node(
    state: DeepXState,
    writer: "StreamWriter | None" = None,
) -> dict[str, Any]:
    """Execute pending tool_calls and emit results."""
    tool_calls: list[dict] = state.get("tool_calls") or []
    if not tool_calls:
        return {"messages": [], "next_node": None}

    tool_messages: list[dict] = []

    for tc in tool_calls:
        func = tc.get("function", {})
        name = func.get("name", "")
        raw_args = func.get("arguments", "{}")

        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {}
        elif isinstance(raw_args, dict):
            args = raw_args
        else:
            args = {}

        logger.info("tool exec: tool=%s args=%s", name, str(args)[:100])
        _emit(writer, "tools", {"type": "state", "status": "executing", "tool": name})

        tool = ToolRegistry.get(name)
        if not tool:
            result = f"Error: unknown tool '{name}'. Available: {[t.name for t in ToolRegistry.all_tools()]}"
        else:
            try:
                result = await tool.execute(**args)
            except Exception as e:
                result = f"Error executing {name}: {e}"

        display_result = str(result)[:300]
        _emit(writer, "tools", {
            "type": "tool_result",
            "tool_name": name,
            "result": display_result,
            "tool_id": tc.get("id", ""),
        })

        tool_messages.append({
            "role": "tool",
            "tool_call_id": tc.get("id", ""),
            "name": name,
            "content": str(result)[:3000],
        })

    return {"messages": tool_messages, "next_node": None}


# ═════════════════════════════════════════════════════════════════════════════
# plan_node — task decomposition (multi-agent planning)
# ═════════════════════════════════════════════════════════════════════════════

async def plan_node(
    state: DeepXState,
    writer: "StreamWriter | None" = None,
) -> dict[str, Any]:
    """
    Analyze the user task and decompose it into parallel sub-tasks.

    The subtasks are returned as a list, which the workflow routes to
    subagents_node for parallel execution via LangGraph Send().
    """
    _emit(writer, "plan", {"type": "state", "status": "planning"})
    # TODO: LLM-based task decomposition
    return {"subtasks": [], "next_node": "subagents"}


# ═════════════════════════════════════════════════════════════════════════════
# subagents_node — parallel multi-agent via Send()
# ═════════════════════════════════════════════════════════════════════════════

async def subagents_node(
    state: DeepXState,
    writer: "StreamWriter | None" = None,
) -> dict[str, Any]:
    """
    Execute independent sub-tasks in parallel using LangGraph Send().

    Each Send() spawns a concurrent agent invocation.
    Results are collected and the TUI shows parallel progress.
    """
    subtasks: list[dict] = state.get("subtasks") or []
    if not subtasks:
        return {
            "messages": [{"role": "assistant", "content": "[No sub-tasks to execute.]"}],
            "next_node": None,
        }

    _emit(writer, "subagents", {"type": "state", "status": "parallel_start", "task_count": len(subtasks)})

    # TODO: implement Send()-based parallel execution
    # For now: sequential stub
    results = []
    for task in subtasks:
        task_id = task.get("id", "?")
        _emit(writer, "subagents", {
            "type": "tool_result",
            "tool_name": "subagent",
            "result": f"[Running task {task_id}...]",
            "tool_id": task_id,
        })
        results.append({"task_id": task_id, "result": "[stub]"})

    return {
        "subtask_results": results,
        "messages": [{"role": "assistant", "content": f"[Parallel execution completed {len(subtasks)} tasks]"}],
        "next_node": None,
    }


# ═════════════════════════════════════════════════════════════════════════════
# compress_node — context exceeded threshold
# ═════════════════════════════════════════════════════════════════════════════

async def compress_node(
    state: DeepXState,
    writer: "StreamWriter | None" = None,
) -> dict[str, Any]:
    """Compress history when context exceeds threshold."""
    messages = state.get("messages", [])
    if len(messages) <= 10:
        return {"next_node": None}

    _emit(writer, "compress", {"type": "compress"})
    keep = messages[-10:]
    return {
        "messages": [{"role": "system", "content": "[Earlier conversation history has been summarized.]"}] + keep,
        "next_node": None,
    }


# ═════════════════════════════════════════════════════════════════════════════
# model_switch_node — flash → pro upgrade
# ═════════════════════════════════════════════════════════════════════════════

async def model_switch_node(
    state: DeepXState,
    writer: "StreamWriter | None" = None,
) -> dict[str, Any]:
    _emit(writer, "model_switch", {"type": "routing", "model": "pro", "reason": "model_switch triggered"})
    return {"model": "pro", "next_node": "agent"}


# ═════════════════════════════════════════════════════════════════════════════
# System prompt builder
# ═════════════════════════════════════════════════════════════════════════════

def _build_system_prompt(mode: str) -> str:
    mode_desc = {
        "auto": "All operations run automatically.",
        "review": "File writes and shell commands require confirmation.",
        "plan": "Read-only mode. Analyze but do not write files or run shell commands.",
    }
    return f"""\
You are DeepX, an expert AI programming assistant.

**Mode: {mode.upper()}**
{mode_desc.get(mode, '')}

You have access to tools: {', '.join(t.name for t in ToolRegistry.all_tools())}

When using tools:
- Use precise arguments matching the tool schema
- Prefer Read before Write to see existing content
- For complex tasks, break into steps
- Keep responses focused on what was asked

Be concise and accurate."""