"""
Agent runner — orchestrates LLM calls and tool execution.

This is the runtime engine that the TUI (and optionally graph nodes) use.
Separates two concerns:
  - LLM streaming: handled directly here (no LangGraph event overhead)
  - Tool execution: synchronous with state accumulation

The LangGraph workflow (nodes.py) provides the routing DECISIONS,
but this runner owns the actual LLM I/O and tool execution loop.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from deepx.agent.compress import ContextCompressor
from deepx.agent.prefix_cache import PrefixCache
from deepx.agent.router import route_model
from deepx.config.settings import get_settings
from deepx.llm.client import LLMClient, Message
from deepx.logging_config import agent_logger
from deepx.tools.base import ToolRegistry

logger = agent_logger()

# Max rounds to prevent infinite loops
MAX_ROUNDS = 100


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class StreamDelta:
    """A token or event from the LLM stream."""
    content: str = ""
    reasoning: str = ""
    tool_call: ToolCall | None = None
    tool_call_done: bool = False
    done: bool = False
    error: str | None = None
    # Aggregated usage at end
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_tokens: int = 0


@dataclass
class AgentResult:
    """Result of one agent turn."""
    content: str
    reasoning: str
    tool_calls: list[ToolCall]
    usage_input: int
    usage_output: int
    usage_cache: int
    error: str | None = None


class AgentRunner:
    """
    Runs the ReAct loop: LLM → parse → tools → repeat.
    
    Designed to be called by the TUI for streaming output.
    Each call() yields StreamDelta chunks for real-time display.
    """

    def __init__(self, workspace: str | None = None, session_store=None):
        self.workspace = workspace or "."
        self.settings = get_settings()
        self.llm = LLMClient()
        self.session_store = session_store

        # Context compression + prefix cache
        self._prefix_cache = PrefixCache(workspace=workspace or ".")
        self._compressor = ContextCompressor(prefix_cache=self._prefix_cache)

        # Conversation history (OpenAI message format)
        self.messages: list[dict[str, Any]] = []

        # Per-run accumulators (reset on each user input)
        self._input_tokens = 0
        self._output_tokens = 0
        self._cache_hits = 0

        logger.debug("AgentRunner initialized, workspace=%s", self.workspace)

    # ── Public streaming interface ──────────────────────────────────────────

    async def call(self, user_input: str, mode: str = "review") -> AsyncIterator[StreamDelta]:
        """
        Run one user turn: stream LLM response and execute tools if needed.
        
        Yields StreamDelta chunks for real-time UI updates.
        Tool results are appended to self.messages for the next LLM call.
        """
        logger.info("call start: mode=%s, input_len=%d", mode, len(user_input))
        # Append user message
        self.messages.append({"role": "user", "content": user_input})

        round_num = 0
        model_name = "flash"

        while round_num < MAX_ROUNDS:
            round_num += 1

            # ── Zero-token routing ─────────────────────────────────────
            if model_name == "flash" and len(self.messages) >= 3:
                last = self.messages[-2] if len(self.messages) >= 2 else {}
                tail = str(last.get("content", ""))[:200]
                suggested = route_model(tail)
                if suggested == "pro":
                    logger.info("routing: flash → pro (zero-token)")
                    model_name = "pro"

            # ── Context compression check ─────────────────────────────
            if self._compressor.should_compress(self.messages):
                logger.info("context exceeded threshold, compressing (msgs=%d)", len(self.messages))
                yield StreamDelta(content="\n[Compressing context...]\n")
                compressed, _ = await self._compressor.compress(
                    self.messages,
                    system_prompt=_build_system_prompt(mode, workspace=self.workspace),
                    model=model_name,
                    llm_client=self.llm,
                )
                self.messages = compressed
                logger.info("compression done, reduced to %d msgs", len(self.messages))
                yield StreamDelta(content="[Context compressed.]\n")

            # Build LLM messages
            system_prompt = _build_system_prompt(mode, workspace=self.workspace)
            llm_messages = [Message(role="system", content=system_prompt)]
            for m in self.messages:
                llm_messages.append(Message(**m))

            tool_specs = ToolRegistry.specs()
            model_cfg = self.settings.model_for(model_name)

            # ── LLM streaming ───────────────────────────────────────────
            content_parts: list[str] = []
            reasoning_parts: list[str] = []
            tool_calls_accumulated: list[ToolCall] = []

            async for chunk in self.llm.chat(
                messages=llm_messages,
                model=model_cfg.model_id,
                tools=tool_specs or None,
                reasoning_effort=model_cfg.reasoning_effort,
                stream=True,
            ):
                if chunk.error:
                    yield StreamDelta(error=chunk.error, done=True)
                    return

                if chunk.content:
                    content_parts.append(chunk.content)
                    yield StreamDelta(content=chunk.content)

                if chunk.reasoning:
                    reasoning_parts.append(chunk.reasoning)
                    yield StreamDelta(reasoning=chunk.reasoning)

                if chunk.tool_call and chunk.tool_call.name:
                    args_raw = chunk.tool_call.arguments
                    if isinstance(args_raw, str):
                        try:
                            args_raw = json.loads(args_raw) if args_raw else {}
                        except json.JSONDecodeError:
                            args_raw = {"_raw": args_raw}
                    elif not isinstance(args_raw, dict):
                        args_raw = {"_raw": str(args_raw)}

                    tc = ToolCall(
                        id=chunk.tool_call.id,
                        name=chunk.tool_call.name,
                        arguments=args_raw,
                    )
                    tool_calls_accumulated.append(tc)

                if chunk.done:
                    if chunk.usage:
                        self._input_tokens += chunk.usage.prompt_tokens
                        self._output_tokens += chunk.usage.completion_tokens
                        self._cache_hits += chunk.usage.prompt_cache_hit_tokens
                        yield StreamDelta(
                            done=True,
                            input_tokens=self._input_tokens,
                            output_tokens=self._output_tokens,
                            cache_hit_tokens=self._cache_hits,
                        )
                    else:
                        yield StreamDelta(done=True)

            full_content = "".join(content_parts)
            full_reasoning = "".join(reasoning_parts)

            # Append assistant message to history
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": full_content}
            if full_reasoning:
                assistant_msg["reasoning_content"] = full_reasoning
            if tool_calls_accumulated:
                assistant_msg["tool_calls"] = [
                    {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                    for tc in tool_calls_accumulated
                ]
            self.messages.append(assistant_msg)
            logger.info(
                "llm response: round=%d, model=%s, content_len=%d, tool_calls=%d",
                round_num, model_name, len(full_content), len(tool_calls_accumulated),
            )
            self._auto_save()

            # ── Execute tools if needed ────────────────────────────────
            if not tool_calls_accumulated:
                # Done! No more tool calls.
                logger.info("call done (no tool calls), total_tokens=%d/%d",
                            self._input_tokens, self._output_tokens)
                return

            for tc in tool_calls_accumulated:
                logger.info("tool exec: round=%d, tool=%s, args=%s",
                            round_num, tc.name, str(tc.arguments)[:100])
                tool = ToolRegistry.get(tc.name)
                if not tool:
                    result = f"Error: unknown tool '{tc.name}'. Available: {[t.name for t in ToolRegistry.all_tools()]}"
                else:
                    try:
                        result = await tool.execute(**tc.arguments)
                    except Exception as e:
                        result = f"Error executing {tc.name}: {e}"

                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": str(result)[:3000],
                }
                self.messages.append(tool_msg)
                yield StreamDelta(
                    tool_call=tc,
                    tool_call_done=True,
                    content=f"\n[Result: {str(result)[:200]}]\n",
                )

            # Next round: re-call LLM with tool results

        # Max rounds reached
        logger.warning("max rounds reached (%d), ending call", MAX_ROUNDS)
        yield StreamDelta(content="\n[Max rounds reached. Please start a new conversation.]", done=True)

    # ── Session management ──────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset conversation history (new session)."""
        self.messages.clear()
        self._input_tokens = 0
        self._output_tokens = 0
        self._cache_hits = 0

    def _auto_save(self) -> None:
        """Auto-save conversation history if session_store is set."""
        if self.session_store is None:
            return
        try:
            self.session_store.save_history(self.messages)
        except Exception:
            pass  # Non-blocking

    def load_history(self, messages: list[dict[str, Any]]) -> None:
        """Load existing conversation history."""
        self.messages = list(messages)

    def get_history(self) -> list[dict[str, Any]]:
        """Return current conversation history."""
        return list(self.messages)


def _build_system_prompt(mode: str, workspace: str = ".") -> str:
    mode_desc = {
        "auto": "All operations run automatically.",
        "review": "File writes and shell commands require confirmation.",
        "plan": "Read-only mode. Analyze but do not write files or run shell commands.",
    }
    tools_list = ", ".join(t.name for t in ToolRegistry.all_tools())
    return f"""\
You are DeepX, an expert AI programming assistant.

**Mode: {mode.upper()}**
{mode_desc.get(mode, '')}

You have access to tools: {tools_list}

When using tools:
- Use precise arguments matching the tool schema
- Prefer Read before Write to see existing content
- For complex tasks, break into steps
- Keep responses focused on what was asked

Be concise and accurate."""