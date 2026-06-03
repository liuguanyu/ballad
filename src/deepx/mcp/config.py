"""MCP config — load/save ~/.deepx/mcp.json."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

_CONFIG_FILE: str | None = None


def config_file() -> str:
    """Return the MCP config file path (~/.deepx/mcp.json)."""
    if _CONFIG_FILE:
        return _CONFIG_FILE
    home = os.path.expanduser("~")
    return os.path.join(home, ".deepx", "mcp.json")


@dataclass
class ServerConfig:
    """MCP server configuration.

    URL non-empty = HTTP (Streamable HTTP) transport.
    Otherwise = stdio transport (run subprocess via Command/Args/Env).
    Headers are passed for HTTP transport (auth headers etc).
    """

    name: str
    command: str = ""        # stdio transport: executable
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""            # HTTP transport URL
    headers: dict[str, str] = field(default_factory=dict)


def load_config() -> list[ServerConfig]:
    """Read ~/.deepx/mcp.json, return list of ServerConfig. Missing file = empty list."""
    path = config_file()
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    servers = []
    for raw in doc.get("servers", []):
        servers.append(ServerConfig(
            name=raw.get("name", ""),
            command=raw.get("command", ""),
            args=raw.get("args", []),
            env=raw.get("env", {}),
            url=raw.get("url", ""),
            headers=raw.get("headers", {}),
        ))
    return servers


def save_config(servers: list[ServerConfig]) -> None:
    """Atomically write servers back to ~/.deepx/mcp.json (write to .tmp then rename)."""
    path = config_file()
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)

    doc = {"servers": [
        {
            "name": s.name,
            "command": s.command,
            "args": s.args,
            "env": s.env,
            "url": s.url,
            "headers": s.headers,
        }
        for s in servers
    ]}
    data = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(tmp, path)


def add_server(server: ServerConfig) -> None:
    """Add a server to config (replace by name if exists), then save."""
    servers = load_config()
    replaced = False
    for i, s in enumerate(servers):
        if s.name == server.name:
            servers[i] = server
            replaced = True
            break
    if not replaced:
        servers.append(server)
    save_config(servers)


def delete_server(name: str) -> bool:
    """Delete server by name. Returns True if deleted, False if not found."""
    servers = load_config()
    original_len = len(servers)
    servers = [s for s in servers if s.name != name]
    if len(servers) == original_len:
        return False
    save_config(servers)
    return True