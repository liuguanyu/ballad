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

import asyncio
import json
import logging
from typing import Any

from langgraph.types import StreamWriter

from deepx.agent.router import route_model
from deepx.config.settings import get_settings
from deepx.graph.state import DeepXState
from deepx.llm.client import LLMClient, Message
from deepx.tools.base import ToolRegistry

logger = logging.getLogger(__name__)

MAX_ROUNDS = 100


def _emit(writer: StreamWriter | None, node: str, data: dict) -> None:
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
    writer: StreamWriter = None,
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
        if hasattr(last, "content"):
            tail = str(last.content)[:200]
        else:
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
    writer: StreamWriter = None,
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
    writer: StreamWriter = None,
) -> dict[str, Any]:
    """
    Analyze the user task and decompose it into parallel sub-tasks.

    Uses the last user message + context to create independent subtasks.
    Each subtask has: id, description, target_files, priority.
    
    The subtasks are returned as a list, which routes to subagents_node
    for parallel execution via LangGraph Send().
    """
    _emit(writer, "plan", {"type": "state", "status": "planning"})
    messages: list[dict] = state.get("messages", [])
    
    # Get the user's current task
    user_msgs = [m for m in messages if _get_role(m) == "user"]
    last_task = user_msgs[-1].get("content", "") if user_msgs else ""
    
    # Also include recent file context (from tool results or explicit context)
    context_snippets = []
    for m in messages[-6:]:
        role = _get_role(m)
        content = m.get("content", "") if isinstance(m, dict) else ""
        if role == "system" and "files:" in content:
            context_snippets.append(content)
    
    task_description = last_task or state.get("task", "")
    
    if not task_description:
        _emit(writer, "plan", {"type": "tool_result", "tool_name": "plan", "result": "No task to plan"})
        return {"subtasks": [], "next_node": None}
    
    _emit(writer, "plan", {"type": "tool_result", "tool_name": "plan", "result": f"Analyzing: {task_description[:60]}..."})
    
    # Call LLM to decompose the task
    subtasks = await _decompose_task(task_description, context_snippets, writer)
    
    _emit(writer, "plan", {
        "type": "tool_result",
        "tool_name": "plan",
        "result": f"Created {len(subtasks)} sub-tasks" + (
            "".join(f"\n  {i+1}. {s.get('description', '')[:60]}" for i, s in enumerate(subtasks))
            if subtasks else ""
        ),
    })
    
    return {"subtasks": subtasks, "next_node": "subagents"}


async def _decompose_task(
    task: str,
    context: list[str],
    writer: StreamWriter = None,
) -> list[dict]:
    """
    Use LLM to decompose a complex task into independent sub-tasks.

    Returns a list of subtask dicts:
      {id, description, target_files, priority, agent_type}
    """
    from deepx.config.settings import get_settings
    from deepx.llm.client import LLMClient, Message

    settings = get_settings()
    model_cfg = settings.flash_model()
    llm = LLMClient(api_key=model_cfg.api_key, base_url=model_cfg.base_url)

    context_text = "\n".join(context[:3]) if context else ""
    
    context_hint = f"Context:\n{context_text}" if context_text else ""

    prompt = f"""\
You are a task planning assistant. Decompose the following task into 2-5 independent sub-tasks that can be executed in parallel.

Requirements:
- Each subtask should be self-contained (no dependencies between subtasks)
- Each subtask should focus on a specific file or set of files
- Be specific about what to do and what files to modify

Return ONLY a JSON array (no markdown, no explanation):
[
  {{"id": "task-1", "description": "what to do", "target_files": ["path/to/file"], "priority": "high|medium|low"}},
  ...
]

Task: {task}
{context_hint}
"""
    
    try:
        content_parts = []
        async for chunk in llm.chat(
            messages=[
                Message(role="system", content="You are a JSON-only assistant. Output ONLY valid JSON array."),
                Message(role="user", content=prompt),
            ],
            model=model_cfg,
            tools=None,
            stream=True,
        ):
            if chunk.error:
                _emit(writer, "plan", {"type": "error", "message": f"Planning failed: {chunk.error}"})
                break
            if chunk.content:
                content_parts.append(chunk.content)
        
        raw = "".join(content_parts).strip()
        # Extract JSON from response
        json_start = raw.find("[")
        json_end = raw.rfind("]") + 1
        if json_start >= 0 and json_end > json_start:
            import json as _json
            tasks = _json.loads(raw[json_start:json_end])
            if isinstance(tasks, list) and tasks:
                return tasks
    except Exception as e:
        _emit(writer, "plan", {"type": "error", "message": f"Planning LLM error: {e}"})
    
    # Fallback: single task wrapping the original
    return [{
        "id": "task-1",
        "description": task[:200],
        "target_files": [],
        "priority": "medium",
    }]


def _get_role(msg) -> str:
    if isinstance(msg, dict):
        return msg.get("role", "")
    return getattr(msg, "type", "")


# ═════════════════════════════════════════════════════════════════════════════
# subagents_node — parallel multi-agent via Send()
# ═════════════════════════════════════════════════════════════════════════════

async def subagents_node(
    state: DeepXState,
    writer: StreamWriter = None,
) -> dict[str, Any]:
    """
    Execute sub-tasks in parallel using asyncio.gather.

    Each sub-task runs a standalone ReAct loop (agent logic) concurrently.
    Results are collected and surfaced in the parent state as subtask_results[].
    
    For the TUI, emits parallel_start + per-subtask tool_result events.
    """
    subtasks: list[dict] = state.get("subtasks") or []
    mode = state.get("_mode", "auto")

    if not subtasks:
        return {
            "messages": [{"role": "assistant", "content": "[No sub-tasks to execute.]"}],
            "subtask_results": [],
            "next_node": None,
        }

    _emit(writer, "subagents", {
        "type": "state",
        "status": "parallel_start",
        "task_count": len(subtasks),
        "tasks": [{"id": t.get("id", f"task-{i}"), "desc": t.get("description", "")[:80]}
                  for i, t in enumerate(subtasks)],
    })

    # Build isolated state for each sub-agent
    sub_states = [
        _build_subagent_state(state, i, subtask)
        for i, subtask in enumerate(subtasks)
    ]

    # Run all sub-agents concurrently
    results = await asyncio.gather(
        *[_run_subagent(sub, mode, writer, task_idx=i) for i, sub in enumerate(sub_states)],
        return_exceptions=True,
    )

    # Collect results
    subtask_results = []
    for i, result in enumerate(results):
        task_id = subtasks[i].get("id", f"task-{i}")
        if isinstance(result, Exception):
            subtask_results.append({
                "task_id": task_id,
                "status": "error",
                "result": f"Error: {result}",
                "output_tokens": 0,
            })
            _emit(writer, "subagents", {
                "type": "tool_result",
                "tool_name": "subagent",
                "result": f"[Error] {result}",
                "tool_id": task_id,
            })
        else:
            subtask_results.append({
                "task_id": task_id,
                "status": "done",
                "result": str(result)[:500],
                "output_tokens": sub_states[i].get("total_output_tokens", 0),
            })
            _emit(writer, "subagents", {
                "type": "tool_result",
                "tool_name": "subagent",
                "result": f"[Done] {str(result)[:100]}",
                "tool_id": task_id,
            })

    # Summary message in parent conversation
    done = [r for r in subtask_results if r["status"] == "done"]
    errors = [r for r in subtask_results if r["status"] == "error"]
    summary_parts = []
    if done:
        summary_parts.append(f"{len(done)} tasks completed")
    if errors:
        summary_parts.append(f"{len(errors)} failed")
    summary = ", ".join(summary_parts) or "No tasks"

    return {
        "subtask_results": subtask_results,
        "messages": [{
            "role": "assistant",
            "content": f"[Parallel execution: {summary}]\n" +
                       "\n".join(
                           f"- [{r['task_id']}] {r['status']}: {r['result'][:80]}"
                           for r in subtask_results
                       ),
        }],
        "next_node": None,
    }


def _build_subagent_state(
    parent: DeepXState,
    idx: int,
    subtask: dict[str, Any],
) -> dict[str, Any]:
    """Build isolated state for one sub-agent invocation."""
    task_desc = subtask.get("description", "")
    target_files = subtask.get("target_files", [])
    files_hint = "\n".join(f"  - {f}" for f in target_files) if target_files else ""
    mode = parent.get("_mode", "auto")

    system_prompt = f"""\
You are a specialized sub-agent completing a single task.

**Your Task**: {task_desc}
{files_hint}

**Mode: {mode.upper()}**
- auto: execute automatically
- review: confirm destructive actions  
- plan: analyze only, no writes

Focus ONLY on your task. Be concise and precise.
Report results clearly at the end."""

    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Complete this task:\n{task_desc}"},
        ],
        "task": task_desc,
        "subtask_id": subtask.get("id", f"task-{idx}"),
        "subtask_idx": idx,
        "model": parent.get("model", "flash"),
        "next_node": None,
        "round": 0,
        "tool_calls": None,
        "tool_results": None,
        "context_budget": parent.get("context_budget", 200_000),
        "compress_triggered": False,
        "compressed_history": None,
        "session_id": f"sub-{parent.get('session_id', '')}-{idx}",
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_hits": 0,
        "_mode": mode,
        "_total_input_tokens": 0,
        "_total_output_tokens": 0,
        "_total_cache_hits": 0,
    }


async def _run_subagent(
    sub_state: dict,
    parent_mode: str,
    writer: StreamWriter = None,
    task_idx: int = 0,
) -> str:
    """
    Run a single sub-agent's ReAct loop until completion (no tool calls or tools done).

    This is a standalone async function that can run concurrently via asyncio.gather.
    Each sub-agent gets its own LLM client and isolated state.
    """
    task_id = sub_state.get("subtask_id", f"task-{task_idx}")
    MAX_SUB_ROUNDS = 20
    sub_round = 0
    sub_messages: list[dict] = sub_state.get("messages", [])
    sub_model = sub_state.get("model", "flash")

    settings = get_settings()
    model_cfg = settings.model_for(sub_model)

    while sub_round < MAX_SUB_ROUNDS:
        sub_round += 1

        # Call LLM
        system_prompt = next(
            (m["content"] for m in sub_messages if m.get("role") == "system"),
            "",
        )
        llm_messages = [Message(role="system", content=system_prompt)]
        for m in sub_messages:
            if m.get("role") != "system":
                llm_messages.append(Message(**m))

        tool_specs = ToolRegistry.specs()
        llm = LLMClient(api_key=model_cfg.api_key, base_url=model_cfg.base_url)

        content_parts = []
        tool_calls = []
        input_t = 0
        output_t = 0
        cache_t = 0

        try:
            async for chunk in llm.chat(
                messages=llm_messages,
                model=model_cfg,
                tools=tool_specs or None,
                reasoning_effort=model_cfg.reasoning_effort,
                stream=True,
            ):
                if chunk.error:
                    _emit(writer, "subagents", {
                        "type": "error",
                        "message": f"Sub-agent {task_id} error: {chunk.error}",
                    })
                    return f"Error: {chunk.error}"

                if chunk.content:
                    content_parts.append(chunk.content)
                if chunk.reasoning:
                    content_parts.append(f"[Think: {chunk.reasoning[:100]}]")

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
                        (tc for tc in tool_calls if tc.get("id") == chunk.tool_call.id),
                        None,
                    )
                    if existing is None:
                        tool_calls.append({
                            "id": chunk.tool_call.id,
                            "type": "function",
                            "function": {"name": chunk.tool_call.name, "arguments": args_raw},
                        })

                if chunk.done and chunk.usage:
                    input_t = chunk.usage.prompt_tokens
                    output_t = chunk.usage.completion_tokens
                    cache_t = chunk.usage.prompt_cache_hit_tokens

        finally:
            await llm.close()

        full_content = "".join(content_parts)
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": full_content}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls

        sub_messages.append(assistant_msg)

        # Execute tools if any
        if not tool_calls:
            # Sub-agent done
            sub_state["total_output_tokens"] += output_t
            return full_content or "[Done]"

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

            _emit(writer, "subagents", {
                "type": "tool_call",
                "tool_id": task_id,
                "tool_name": name,
                "tool_args": {k: str(v)[:50] for k, v in args.items()},
            })

            tool = ToolRegistry.get(name)
            if not tool:
                result = f"Unknown tool: {name}"
            else:
                try:
                    result = await tool.execute(**args)
                except Exception as e:
                    result = f"Error: {e}"

            _emit(writer, "subagents", {
                "type": "tool_result",
                "tool_name": name,
                "result": str(result)[:150],
                "tool_id": task_id,
            })

            sub_messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "name": name,
                "content": str(result)[:3000],
            })

    return f"[Max rounds ({MAX_SUB_ROUNDS}) reached for {task_id}]"


# ═════════════════════════════════════════════════════════════════════════════
# compress_node — context exceeded threshold
# ═════════════════════════════════════════════════════════════════════════════

async def compress_node(
    state: DeepXState,
    writer: StreamWriter = None,
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
    writer: StreamWriter = None,
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