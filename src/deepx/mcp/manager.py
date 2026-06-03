"""MCP manager — manage all MCP server connections and tool registration."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from deepx.logging_config import mcp_logger
from deepx.mcp.client import Client, ServerStatus, ToolDef
from deepx.mcp.config import ServerConfig, load_config

logger = mcp_logger()


# Restart cooldown matching Go version
RESTART_COOLDOWN = timedelta(seconds=5)


def _looks_dead(err: Exception) -> bool:
    """Return True if the error indicates a dead connection."""
    msg = str(err)
    return "已关闭" in msg or "已断开" in msg or "连接中断" in msg


class Manager:
    """Manages all MCP server connections and exposes their tools to the LLM."""

    def __init__(self):
        self.clients: dict[str, Client] = {}
        self.status: dict[str, ServerStatus] = {}
        self.configs: dict[str, ServerConfig] = {}
        self.last_restart: dict[str, datetime] = {}
        self.lock = asyncio.Lock()

    async def connect_all(self) -> None:
        """Background connect to all servers in config, then refresh tools.

        Non-blocking; each server connects independently; failures are logged to status only.
        """
        servers = load_config()
        if not servers:
            return

        async def connect_one(s: ServerConfig) -> None:
            try:
                await self.connect(s)
            except Exception:
                pass  # status is set by connect()

        await asyncio.gather(*[connect_one(s) for s in servers], return_exceptions=True)
        await self.refresh_tools()

    async def connect(self, config: ServerConfig) -> None:
        """Connect to a single server and immediately refresh tools."""
        logger.info("connecting to MCP server: %s", config.name)
        async with self.lock:
            # Disconnect existing if any
            if config.name in self.clients:
                logger.debug("disconnecting existing client for %s", config.name)
                old = self.clients[config.name]
                await old.close()
                del self.clients[config.name]

            try:
                client = await Client.connect(config)
                logger.info("MCP server %s connected", config.name)
            except Exception as e:
                logger.error("MCP server %s connection failed: %s", config.name, e)
                self.status[config.name] = ServerStatus(
                    name=config.name,
                    connected=False,
                    tool_count=0,
                    error=str(e),
                )
                self.configs[config.name] = config
                raise

            try:
                tools = await client.list_tools()
                logger.info("MCP %s: %d tools available", config.name, len(tools))
            except Exception as e:
                logger.error("MCP %s tools/list failed: %s", config.name, e)
                await client.close()
                self.status[config.name] = ServerStatus(
                    name=config.name,
                    connected=False,
                    tool_count=0,
                    error=f"tools/list 失败: {e}",
                )
                self.configs[config.name] = config
                raise

            self.clients[config.name] = client
            self.status[config.name] = ServerStatus(
                name=config.name,
                connected=True,
                tool_count=len(tools),
                error="",
            )
            self.configs[config.name] = config

    async def disconnect(self, name: str) -> None:
        """Disconnect and remove a server, then refresh tools."""
        async with self.lock:
            if name in self.clients:
                await self.clients[name].close()
                del self.clients[name]
            self.status.pop(name, None)
            self.configs.pop(name, None)
            self.last_restart.pop(name, None)
        await self.refresh_tools()

    async def restart(self, name: str) -> None:
        """Kill old connection and reconnect with saved config. 5s cooldown."""
        async with self.lock:
            if name not in self.configs:
                raise ValueError(f'无 "{name}" 的 MCP 配置,无法重启')

            last = self.last_restart.get(name)
            if last and (datetime.now() - last) < RESTART_COOLDOWN:
                remaining = RESTART_COOLDOWN - (datetime.now() - last)
                raise ValueError(
                    f'MCP "{name}" 刚刚才重启过(冷却中,剩 {remaining.total_seconds():.1f}s),本次不再重试'
                )
            self.last_restart[name] = datetime.now()

            if name in self.clients:
                await self.clients[name].close()
                del self.clients[name]

        config = self.configs[name]
        await self.connect(config)

    async def call_tool(self, server: str, tool: str, args: dict) -> str:
        """Call a tool on a server; auto-restart + retry once if connection is dead."""
        client = await self.get_client(server)
        try:
            return await client.call_tool(tool, args)
        except Exception as call_err:
            if not _looks_dead(call_err):
                raise  # tool's own error, not connection dead

            # Connection dead — restart and retry once
            try:
                await self.restart(server)
            except Exception as restart_err:
                raise RuntimeError(
                    f"MCP 调用失败,自动重启也失败: {call_err} / 重启错误: {restart_err}"
                ) from restart_err

            client2 = await self.get_client(server)
            try:
                return await client2.call_tool(tool, args)
            except Exception as retry_err:
                raise RuntimeError(
                    f'已自动重启 MCP server "{server}",但重试调用仍失败: {retry_err}'
                ) from retry_err

    async def get_client(self, name: str) -> Client:
        """Get current client for a server; raises if not connected."""
        async with self.lock:
            client = self.clients.get(name)
            if client is None:
                raise ValueError(f'MCP server "{name}" 未连接')
            return client

    def server_status(self) -> list[ServerStatus]:
        """Return sorted snapshot of all server statuses."""
        statuses = list(self.status.values())
        statuses.sort(key=lambda s: s.name)
        return statuses

    async def refresh_tools(self) -> None:
        """List tools from all connected clients and register them in ToolRegistry."""
        from deepx.tools.base import ToolRegistry

        entries: list[tuple[Client, str, list[ToolDef]]] = []
        async with self.lock:
            for name, client in self.clients.items():
                try:
                    tools = await client.list_tools()
                    entries.append((client, name, tools))
                except Exception:
                    pass

        tools_out: list[dict] = []
        for client, server, defs in entries:
            for d in defs:
                tool = _make_tool_dict(server, d, self.call_tool)
                tools_out.append(tool)

        ToolRegistry.set_mcp_tools(tools_out)


def _schema_to_tool_param(schema: dict) -> dict:
    """Convert MCP JSON Schema to a Tool-compatible parameter dict."""
    p: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
    if not schema:
        return p

    props = schema.get("properties", {})
    for name, raw in props.items():
        prop: dict[str, Any] = {"type": "string"}
        if isinstance(raw, dict):
            if "type" in raw:
                prop["type"] = raw["type"]
            if "description" in raw:
                prop["description"] = raw["description"]
            if "items" in raw:
                prop["items"] = raw["items"]
        p["properties"][name] = prop

    for r in schema.get("required", []):
        if isinstance(r, str):
            p["required"].append(r)
    return p


def _make_tool_dict(
    server: str, d: ToolDef, call_tool_fn
) -> dict:
    """Build a tool dict with async executor that routes through manager.call_tool."""
    name = f"mcp__{server}__{d.name}"

    async def executor(args: dict) -> dict:
        result, success = "", True
        try:
            result = await call_tool_fn(server, d.name, args)
        except Exception as e:
            result = f"MCP 调用失败: {e}"
            success = False
        return {"output": result, "success": success}

    return {
        "name": name,
        "description": f"[MCP:{server}] {d.description}",
        "parameters": _schema_to_tool_param(d.inputSchema or {}),
        "read_only": False,
        "_executor": executor,
        "_server": server,
        "_tool": d.name,
    }
