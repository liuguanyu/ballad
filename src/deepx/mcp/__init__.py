"""MCP module — Model Context Protocol client for DeepX.

Exposes tools from external MCP servers as DeepX tools (mcp__<server>__<tool>).
All server connections, auto-restart logic, and tool registration are in the Manager class.
"""
from deepx.mcp.client import Client, ServerStatus, ToolDef
from deepx.mcp.config import (
    ServerConfig,
    add_server,
    config_file,
    delete_server,
    load_config,
    save_config,
)
from deepx.mcp.manager import Manager

__all__ = [
    "Client",
    "ServerConfig",
    "ToolDef",
    "Manager",
    "ServerStatus",
    "config_file",
    "load_config",
    "save_config",
    "add_server",
    "delete_server",
]
