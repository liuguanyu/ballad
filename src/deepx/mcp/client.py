"""MCP client — hand-written JSON-RPC, no SDK dependency.

Supports two transports:
  - stdio: server runs as subprocess, communicate via stdin/stdout line-delimited JSON
  - http:  Streamable HTTP, POST JSON-RPC to URL, response may be application/json or text/event-stream
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from deepx.mcp.config import ServerConfig

# Timeout constants matching Go version
WRITE_TIMEOUT = 5.0   # seconds per write stage (enqueue + encode)
REQUEST_TIMEOUT = 30.0  # seconds per JSON-RPC request

PROTOCOL_VERSION = "2024-11-05"


@dataclass
class ToolDef:
    """An MCP tool definition returned by tools/list."""
    name: str
    description: str
    inputSchema: dict


@dataclass
class ServerStatus:
    """Connection status of a single MCP server (for /mcp-list display)."""
    name: str
    connected: bool
    tool_count: int
    error: str = ""


# ---------------------------------------------------------------------------
# Transport interface (abstract base)
# ---------------------------------------------------------------------------

class _Transport:
    async def call(self, method: str, params: Any) -> Any:
        raise NotImplementedError

    async def notify(self, method: str, params: Any) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Stdio Transport — subprocess stdin/stdout JSON-RPC
# ---------------------------------------------------------------------------

class StdioTransport(_Transport):
    """Launch subprocess, communicate via stdin/stdout line-delimited JSON."""

    def __init__(self, command: str, args: list[str], env: dict[str, str]):
        self.command = command
        self.args = args
        self._env = env
        self._closed = False
        self._lock = asyncio.Lock()

        # pending request futures keyed by id
        self._pending: dict[int, asyncio.Future] = {}

        # write_queue serialises all writes through a single writer coroutine
        self._write_queue: asyncio.Queue[tuple[Any, asyncio.Future]] = asyncio.Queue(maxsize=64)
        # stop_evt signals writer/reader to exit
        self._stop_evt: asyncio.Event = asyncio.Event()

        # subprocess handles
        self._proc: asyncio.subprocess.Process | None = None
        self._stdin: asyncio.StreamWriter | None = None
        self._stdout: asyncio.StreamReader | None = None

        # request id counter
        self._next_id: int = 0

    async def _start(self) -> None:
        """Launch subprocess and start reader/writer loops."""
        # Merge env with current environment
        merged_env = dict(os.environ)
        merged_env.update(self._env)

        self._proc = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            env=merged_env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=sys.stderr,
        )
        self._stdin = self._proc.stdin
        self._stdout = self._proc.stdout

        # Start writer loop
        asyncio.create_task(self._writer_loop())
        # Start reader loop
        asyncio.create_task(self._reader_loop())

    async def _writer_loop(self) -> None:
        """Dedicated writer: serialise all writes via the write queue."""
        try:
            while True:
                try:
                    payload, done = await asyncio.wait_for(
                        self._write_queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    if self._stop_evt.is_set():
                        return
                    continue

                if self._stop_evt.is_set():
                    return

                try:
                    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
                    # Stage 2: actual write with timeout
                    self._stdin.write(data)
                    await asyncio.wait_for(self._stdin.drain(), timeout=WRITE_TIMEOUT)
                    if not done.done():
                        done.set_result(None)  # type: ignore
                except Exception as e2:
                    if not done.done():
                        done.set_exception(e2)

        except asyncio.CancelledError:
            pass

    async def _reader_loop(self) -> None:
        """Read stdout line by line, match responses to pending requests."""
        assert self._stdout is not None
        try:
            while not self._closed:
                try:
                    line = await asyncio.wait_for(
                        self._stdout.readline(),
                        timeout=REQUEST_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    # Timeout on read — not necessarily an error, just keep waiting
                    continue

                if not line:
                    # EOF — process exited
                    break

                try:
                    resp = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue

                # Extract id
                resp_id = resp.get("id")
                if resp_id is None:
                    continue

                async with self._lock:
                    fut = self._pending.pop(resp_id, None)

                if fut is not None and not fut.done():
                    # Populate result or error
                    if "error" in resp:
                        err = resp["error"]
                        fut.set_exception(RpcException(err.get("code", -1), err.get("message", "unknown")))
                    else:
                        fut.set_result(resp.get("result"))
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            await self.close()

    async def _send_payload(self, payload: Any) -> None:
        """Submit a write to the writer loop, with two-stage timeout."""
        if self._closed:
            raise RpcException(0, "MCP 连接已关闭")

        done: asyncio.Future = asyncio.get_event_loop().create_future()

        # Stage 1: enqueue with timeout
        try:
            self._write_queue.put_nowait((payload, done))
        except asyncio.QueueFull:
            raise RpcException(0, f"MCP 写入队列满({WRITE_TIMEOUT}), server 可能死锁")

        try:
            await asyncio.wait_for(done, timeout=WRITE_TIMEOUT)
        except asyncio.TimeoutError:
            # Writer is stuck in write/drain — server is deadlocked.
            # Trigger async close so writer exits.
            asyncio.create_task(self.close())
            raise RpcException(0, f"MCP 写入 stdin 超时({WRITE_TIMEOUT}), server 死锁, 连接已断开")

    async def call(self, method: str, params: Any) -> Any:
        """Send a JSON-RPC request, return result or raise."""
        async with self._lock:
            if self._closed:
                raise RpcException(0, "MCP 连接已关闭")
            self._next_id += 1
            req_id = self._next_id

        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        async with self._lock:
            self._pending[req_id] = fut

        try:
            await self._send_payload({
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            })
        except Exception as e:
            async with self._lock:
                self._pending.pop(req_id, None)
            raise

        # Wait for response with overall request timeout
        try:
            return await asyncio.wait_for(fut, timeout=REQUEST_TIMEOUT)
        except asyncio.TimeoutError:
            async with self._lock:
                self._pending.pop(req_id, None)
            raise RpcException(0, f"MCP 请求超时({method}, {REQUEST_TIMEOUT}s)")

    async def notify(self, method: str, params: Any) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        await self._send_payload({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        })

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_evt.set()

        # Cancel pending requests
        async with self._lock:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RpcException(0, "MCP 连接已关闭"))
            self._pending.clear()

        # Close stdin
        if self._proc and self._proc.stdin:
            self._proc.stdin.close()

        # Terminate subprocess
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=3.0)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass


# ---------------------------------------------------------------------------
# HTTP Transport — Streamable HTTP
# ---------------------------------------------------------------------------

class HTTPTransport(_Transport):
    """HTTP/JSON-RPC with SSE (text/event-stream) response support."""

    def __init__(self, url: str, headers: dict[str, str] | None = None):
        import httpx
        self.url = url
        self.headers = headers or {}
        self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
        self._lock = asyncio.Lock()
        self._session_id: str | None = None
        self._next_id = 0

    async def _post(self, body: bytes) -> Any:
        """Execute POST request with MCP session handling."""
        import httpx
        headers = dict(self.headers)
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json, text/event-stream"
        async with self._lock:
            sid = self._session_id
        if sid:
            headers["Mcp-Session-Id"] = sid

        resp = await self._client.post(self.url, content=body, headers=headers)
        if resp.status_code < 200 or resp.status_code >= 300:
            body_text = resp.text[:4096]
            raise RpcException(resp.status_code, f"HTTP {resp.status_code}: {body_text}")

        if "Mcp-Session-Id" in resp.headers:
            async with self._lock:
                self._session_id = resp.headers["Mcp-Session-Id"]

        return resp

    async def call(self, method: str, params: Any) -> Any:
        async with self._lock:
            self._next_id += 1
            req_id = self._next_id

        body = json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }).encode("utf-8")

        resp = await self._post(body)

        content_type = resp.headers.get("Content-Type", "")
        if content_type.startswith("text/event-stream"):
            return await self._handle_sse(resp, req_id)

        data = resp.json()
        if "error" in data:
            err = data["error"]
            raise RpcException(err.get("code", -1), err.get("message", "unknown"))
        return data.get("result")

    async def notify(self, method: str, params: Any) -> None:
        body = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }).encode("utf-8")
        resp = await self._post(body)
        await resp.aclose()

    async def _handle_sse(self, resp: Any, req_id: int) -> Any:
        """Parse SSE stream to find the JSON-RPC response matching req_id."""
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if not data:
                continue
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if obj.get("id") != req_id:
                continue
            if "error" in obj:
                err = obj["error"]
                raise RpcException(err.get("code", -1), err.get("message", "unknown"))
            return obj.get("result")
        raise RpcException(0, f"SSE stream did not return response for id={req_id}")

    async def close(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# RpcException
# ---------------------------------------------------------------------------

class RpcException(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"mcp rpc error {code}: {message}")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class Client:
    """An MCP server connection (transport-agnostic)."""

    def __init__(self, transport: _Transport):
        self._transport = transport

    @staticmethod
    async def connect(config: ServerConfig) -> Client:
        """Connect to a server (stdio or HTTP), perform MCP handshake, return Client."""
        if config.url:
            transport = HTTPTransport(config.url, config.headers)
        else:
            transport = StdioTransport(config.command, config.args, config.env)
            await transport._start()

        client = Client(transport)

        # MCP handshake: initialize
        init_params = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "deepx-python", "version": "1"},
        }
        try:
            await transport.call("initialize", init_params)
        except Exception as e:
            await transport.close()
            raise RpcException(0, f"MCP 握手失败: {e}")

        # Send notifications/initialized
        try:
            await transport.notify("notifications/initialized", None)
        except Exception as e:
            await transport.close()
            raise RpcException(0, f"MCP notifications/initialized 失败: {e}")

        return client

    async def list_tools(self) -> list[ToolDef]:
        """Call tools/list and return the list of ToolDef."""
        raw = await self._transport.call("tools/list", {})
        if raw is None:
            return []
        out = []
        for item in raw.get("tools", []):
            out.append(ToolDef(
                name=item.get("name", ""),
                description=item.get("description", ""),
                inputSchema=item.get("inputSchema") or {},
            ))
        return out

    async def call_tool(self, tool: str, args: dict | None = None) -> str:
        """Call tools/call, return concatenated text result."""
        if args is None:
            args = {}
        raw = await self._transport.call("tools/call", {"name": tool, "arguments": args})
        parts: list[str] = []
        is_error = raw.get("isError", False) if isinstance(raw, dict) else False
        for item in raw.get("content", []) if isinstance(raw, dict) else []:
            if item.get("type") == "text" and item.get("text"):
                parts.append(item["text"])
        result = "\n".join(parts)
        if is_error:
            return result + "\n(MCP 工具返回错误)"
        return result

    async def close(self) -> None:
        await self._transport.close()
