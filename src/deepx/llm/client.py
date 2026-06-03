"""LLM client — multi-provider (OpenAI-compatible + Anthropic)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx
from pydantic import BaseModel

from deepx.config.models import ModelConfig
from deepx.config.settings import get_settings
from deepx.llm.usage import UsageInfo


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class ToolCallBlock(BaseModel):
    id: str
    type: str = "function"
    function: ToolCall = field(default_factory=ToolCall)


class Message(BaseModel):
    role: str
    content: str = ""
    reasoning_content: str = ""
    tool_calls: list[ToolCallBlock] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.reasoning_content:
            d["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            d["tool_calls"] = [
                {"id": tc.id, "type": tc.type,
                 "function": {"name": tc.function.name, "arguments": json.dumps(tc.function.arguments)}}
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class StreamChunk:
    content: str = ""
    reasoning: str = ""
    tool_call: ToolCall | None = None
    tool_call_done: bool = False
    usage: UsageInfo | None = None
    done: bool = False
    error: str | None = None


class LLMClient:
    """Async LLM client: OpenAI (/chat/completions) and Anthropic (/v1/messages)."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self._custom_key = api_key
        self._custom_base = base_url
        self._clients: dict[str, httpx.AsyncClient] = {}

    def get_model(self, name: str) -> ModelConfig:
        return get_settings().model(name)

    def _client_for(self, model_cfg: ModelConfig) -> httpx.AsyncClient:
        key = f"{model_cfg.base_url}:{model_cfg.api_type}"
        if key not in self._clients:
            api_key = self._custom_key or model_cfg.api_key or ""
            base = self._custom_base or model_cfg.base_url
            self._clients[key] = httpx.AsyncClient(
                base_url=base,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=httpx.Timeout(120.0),
            )
        return self._clients[key]

    async def close(self):
        for c in self._clients.values():
            await c.aclose()
        self._clients.clear()

    async def chat(
        self,
        messages: list[Message],
        model: ModelConfig | str,
        tools: list[dict] | None = None,
        reasoning_effort: str | None = None,
        thinking: bool = False,
        stream: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        if isinstance(model, str):
            model = self.get_model(model)
        if model.api_type == "anthropic":
            async for chunk in self._chat_anthropic(model, messages, tools, thinking, stream):
                yield chunk
        else:
            async for chunk in self._chat_openai(model, messages, tools, reasoning_effort, stream):
                yield chunk

    async def _chat_openai(
        self,
        model: ModelConfig,
        messages: list[Message],
        tools: list[dict] | None,
        reasoning_effort: str | None,
        stream: bool,
    ) -> AsyncIterator[StreamChunk]:
        client = self._client_for(model)
        payload: dict[str, Any] = {
            "model": model.model,
            "messages": [m.to_dict() for m in messages],
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if tools:
            payload["tools"] = tools
        if reasoning_effort or model.reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort or model.reasoning_effort

        try:
            if stream:
                async with client.stream("POST", "/chat/completions", json=payload) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        yield StreamChunk(error=f"HTTP {resp.status_code}: {body[:500]}", done=True)
                        return
                    async for chunk in self._sse_openai(resp):
                        yield chunk
            else:
                resp = await client.post("/chat/completions", json=payload)
                if resp.status_code != 200:
                    yield StreamChunk(error=f"HTTP {resp.status_code}: {resp.text[:500]}", done=True)
                    return
                data = resp.json()
                choice = (data.get("choices") or [{}])[0]
                msg = choice.get("message", {})
                tc_data = msg.get("tool_calls", [])
                chunk = StreamChunk(content=msg.get("content", ""), done=True)
                if tc_data:
                    tc = tc_data[0]
                    chunk.tool_call = ToolCall(
                        id=tc.get("id", ""),
                        name=tc.get("function", {}).get("name", ""),
                        arguments=json.loads(tc.get("function", {}).get("arguments", "{}")),
                    )
                if u := data.get("usage"):
                    chunk.usage = UsageInfo(
                        prompt_tokens=u.get("prompt_tokens", 0),
                        completion_tokens=u.get("completion_tokens", 0),
                        prompt_cache_hit_tokens=u.get("prompt_cache_hit_tokens", 0),
                        prompt_cache_miss_tokens=u.get("prompt_cache_miss_tokens", 0),
                    )
                yield chunk
        except Exception as e:
            yield StreamChunk(error=str(e), done=True)

    async def _sse_openai(self, resp) -> AsyncIterator[StreamChunk]:
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            if line == "data: [DONE]":
                yield StreamChunk(done=True)
                return
            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            choice = (data.get("choices") or [{}])[0]
            delta = choice.get("delta", {})
            u = data.get("usage")
            finish = choice.get("finish_reason")
            chunk = StreamChunk()
            if delta.get("content"):
                chunk.content = delta["content"]
            if delta.get("reasoning_content"):
                chunk.reasoning = delta["reasoning_content"]
            if delta.get("tool_calls"):
                tc = delta["tool_calls"][0]
                chunk.tool_call = ToolCall(
                    id=tc.get("id", ""),
                    name=tc.get("function", {}).get("name", ""),
                    arguments=json.loads(tc.get("function", {}).get("arguments", "{}")),
                )
            if finish:
                chunk.done = True
            if u:
                chunk.usage = UsageInfo(
                    prompt_tokens=u.get("prompt_tokens", 0),
                    completion_tokens=u.get("completion_tokens", 0),
                    prompt_cache_hit_tokens=u.get("prompt_cache_hit_tokens", 0),
                    prompt_cache_miss_tokens=u.get("prompt_cache_miss_tokens", 0),
                )
            yield chunk

    async def _chat_anthropic(
        self,
        model: ModelConfig,
        messages: list[Message],
        tools: list[dict] | None,
        thinking: bool,
        stream: bool,
    ) -> AsyncIterator[StreamChunk]:
        """Anthropic /v1/messages: supports streaming (SSE event:/data:) and non-streaming."""
        client = self._client_for(model)

        system, role_msgs = [], []
        for m in messages:
            if m.role == "system":
                system.append(m.content)
            elif m.role == "user":
                role_msgs.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                parts = []
                if m.content:
                    parts.append({"type": "text", "text": m.content})
                if m.tool_calls:
                    for tc in m.tool_calls:
                        parts.append({"type": "tool_use", "id": tc.id, "name": tc.function.name, "input": tc.function.arguments})
                role_msgs.append({"role": "assistant", "content": parts or [{"type": "text", "text": ""}]})
            elif m.role == "tool":
                role_msgs.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}]})

        payload: dict[str, Any] = {
            "model": model.model,
            "messages": role_msgs,
            "max_tokens": model.max_tokens,
            "stream": stream,
        }
        if system:
            payload["system"] = system
        if thinking or model.thinking:
            payload["thinking"] = {"type": "enabled", "budget_tokens": 8000}
        if tools:
            payload["tools"] = [
                {"name": t["function"]["name"], "description": t["function"].get("description", ""), "input_schema": t["function"].get("parameters", {})}
                for t in tools
            ]

        try:
            if stream:
                async with client.stream("POST", "/v1/messages", json=payload) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        yield StreamChunk(error=f"HTTP {resp.status_code}: {body[:500]}", done=True)
                        return
                    event_type = ""
                    done = False
                    async for raw in resp.aiter_lines():
                        line = raw.strip()
                        if not line:
                            continue
                        if line.startswith("event: "):
                            event_type = line[7:]
                        elif line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])
                            except json.JSONDecodeError:
                                continue
                            if event_type == "content_block_delta":
                                delta = data.get("delta", {})
                                dt = delta.get("type", "")
                                if dt == "text_delta":
                                    yield StreamChunk(content=delta.get("text", ""))
                                elif dt == "thinking_delta":
                                    yield StreamChunk(reasoning=delta.get("thinking", ""))
                            elif event_type == "message_delta":
                                u = data.get("usage", {})
                                yield StreamChunk(
                                    usage=UsageInfo(prompt_tokens=u.get("input_tokens", 0), completion_tokens=u.get("output_tokens", 0), prompt_cache_hit_tokens=0, prompt_cache_miss_tokens=0),
                                    done=True,
                                )
                                done = True
                            elif event_type == "message_stop":
                                done = True
                    if not done:
                        yield StreamChunk(done=True)
            else:
                # Non-streaming
                resp = await client.post("/v1/messages", json=payload)
                if resp.status_code != 200:
                    yield StreamChunk(error=f"HTTP {resp.status_code}: {resp.text[:500]}", done=True)
                    return
                data = resp.json()
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        yield StreamChunk(content=block.get("text", ""))
                    elif block.get("type") == "thinking":
                        yield StreamChunk(reasoning=block.get("thinking", ""))
                u = data.get("usage", {})
                yield StreamChunk(
                    usage=UsageInfo(prompt_tokens=u.get("input_tokens", 0), completion_tokens=u.get("output_tokens", 0), prompt_cache_hit_tokens=0, prompt_cache_miss_tokens=0),
                    done=True,
                )
        except Exception as e:
            yield StreamChunk(error=str(e), done=True)