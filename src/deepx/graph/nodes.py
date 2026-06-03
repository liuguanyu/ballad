"""
LangGraph nodes for the DeepX workflow.

These nodes provide the routing DECISIONS for LangGraph.
The actual LLM I/O is handled by AgentRunner (agent/runner.py),
which the TUI uses directly for streaming output.

These nodes can still be used for non-streaming/graph-based execution.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from deepx.agent.router import route_model
from deepx.config.settings import get_settings
from deepx.graph.state import DeepXState
from deepx.llm.client import LLMClient, Message
from deepx.tools.base import ToolRegistry

logger = logging.getLogger(__name__)

MAX_ROUNDS = 100


async def agent_node(state: DeepXState) -> dict[str, Any]:
    """
    Main Agent node — calls LLM with current history, parses response.

    Used by LangGraph workflow for non-streaming/graph-based execution.
    For TUI streaming, use AgentRunner instead.
    """
    settings = get_settings()
    round_num = state.get("round", 0) + 1
    if round_num > MAX_ROUNDS:
        return {
            "messages": [{"role": "assistant", "content": "[Max rounds reached.]"}],
            "next_node": "end",
            "round": round_num,
            "model": state.get("model", "flash"),
        }

    messages: list[dict] = state.get("messages", [])
    model_name = state.get("model", "flash")

    # Zero-token routing: upgrade to pro if needed
    if model_name == "flash" and len(messages) >= 2:
        last = messages[-1] if messages else {}
        tail = str(last.get("content", ""))[:200]
        suggested = route_model(tail)
        if suggested == "pro":
            model_name = "pro"

    model_cfg = settings.model_for(model_name)
    system_prompt = _build_system_prompt(state.get("_mode", "review"))
    llm_messages = [Message(role="system", content=system_prompt)]
    for m in messages:
        llm_messages.append(Message(**m))

    tool_specs = ToolRegistry.specs()
    llm = LLMClient(
        api_key=model_cfg.api_key or settings.deepseek_api_key,
        base_url=model_cfg.base_url or settings.deepseek_base_url,
    )

    content = ""
    reasoning_content = ""
    tool_calls: list[dict] = []
    error_msg: str | None = None

    try:
        async for chunk in llm.chat(
            messages=llm_messages,
            model=model_cfg.model_id,
            tools=tool_specs or None,
            reasoning_effort=model_cfg.reasoning_effort,
            stream=True,
        ):
            if chunk.error:
                error_msg = chunk.error
                break

            content += chunk.content
            reasoning_content += chunk.reasoning

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
                    (tc for tc in tool_calls if tc.get("id") == chunk.tool_call.id), None
                )
                if existing is None:
                    tool_calls.append({
                        "id": chunk.tool_call.id,
                        "type": "function",
                        "function": {"name": chunk.tool_call.name, "arguments": args_raw},
                    })
                else:
                    existing["function"]["arguments"] = args_raw

            if chunk.done and chunk.usage:
                state["_total_input_tokens"] = state.get("_total_input_tokens", 0) + chunk.usage.prompt_tokens
                state["_total_output_tokens"] = state.get("_total_output_tokens", 0) + chunk.usage.completion_tokens
                state["_total_cache_hits"] = state.get("_total_cache_hits", 0) + chunk.usage.prompt_cache_hit_tokens

    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        error_msg = str(e)

    await llm.close()

    if error_msg:
        return {
            "messages": [{"role": "assistant", "content": f"[Error: {error_msg}]"}],
            "next_node": "end",
            "round": round_num,
            "model": model_name,
        }

    next_node = "tools" if tool_calls else "end"
    assistant_msg: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning_content:
        assistant_msg["reasoning_content"] = reasoning_content
    if tool_calls:
        assistant_msg["tool_calls"] = tool_calls

    return {
        "messages": [assistant_msg],
        "tool_calls": tool_calls or None,
        "next_node": next_node,
        "round": round_num,
        "model": model_name,
    }


async def tools_node(state: DeepXState) -> dict[str, Any]:
    """Execute tool calls and return results."""
    tool_calls: list[dict] = state.get("tool_calls") or []
    if not tool_calls:
        return {"next_node": None}

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

        tool = ToolRegistry.get(name)
        if not tool:
            result = f"Error: unknown tool '{name}'. Available: {[t.name for t in ToolRegistry.all_tools()]}"
        else:
            try:
                result = await tool.execute(**args)
            except Exception as e:
                result = f"Error executing {name}: {e}"

        tool_messages.append({
            "role": "tool",
            "tool_call_id": tc.get("id", ""),
            "name": name,
            "content": str(result)[:3000],
        })

    return {
        "messages": tool_messages,
        "next_node": None,
    }


async def plan_node(state: DeepXState) -> dict[str, Any]:
    """Analyze task and create parallel sub-task plan."""
    return {"subtasks": [], "next_node": "subagents"}


async def subagents_node(state: DeepXState) -> dict[str, Any]:
    """Run independent sub-tasks in parallel."""
    subtasks = state.get("subtasks") or []
    if not subtasks:
        return {"next_node": None}
    return {
        "subtask_results": [{"task_id": t.get("id"), "result": "[stub]"} for t in subtasks],
        "messages": [{"role": "assistant", "content": f"[Parallel execution completed {len(subtasks)} tasks]"}],
        "next_node": None,
    }


async def compress_node(state: DeepXState) -> dict[str, Any]:
    """Compress history when context exceeds threshold."""
    messages = state.get("messages", [])
    if len(messages) <= 10:
        return {"next_node": None}
    keep = messages[-10:]
    return {
        "messages": [{"role": "system", "content": "[Earlier conversation history has been summarized.]"}] + keep,
        "next_node": None,
    }


async def model_switch_node(state: DeepXState) -> dict[str, Any]:
    """Upgrade from flash to pro model."""
    return {"model": "pro", "next_node": "agent"}


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