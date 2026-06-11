"""Tool base class and global registry."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from deepx.logging_config import tools_logger

logger = tools_logger()


class Tool(ABC):
    """Base class for all DeepX tools.

    Each tool provides:
    - name: the function name the LLM sees
    - description: when to call this tool
    - parameters: OpenAI function-calling format (JSON Schema)
    """

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}

    def __init__(self, name: str = "", description: str = "", parameters: dict[str, Any] | None = None):
        if name:
            self.name = name
        if description:
            self.description = description
        if parameters is not None:
            self.parameters = parameters

    def to_spec(self) -> dict[str, Any]:
        """Export as OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Execute the tool with given arguments. Returns result string."""
        ...


# ---------------------------------------------------------------------------
# MCP Tool wrapper — adapts a dict-style MCP tool (with async executor)
# to the Tool interface so it integrates seamlessly with ToolRegistry.
# ---------------------------------------------------------------------------

class MCPTool(Tool):
    """Wraps a dict-style MCP tool with an async executor closure."""

    def __init__(self, name: str, description: str, parameters: dict,
                 executor: Callable[..., Coroutine[Any, Any, dict]], read_only: bool = False):
        self.name = name
        self.description = description
        self.parameters = parameters
        self._executor = executor
        self.read_only = read_only

    async def execute(self, **kwargs) -> str:
        result = await self._executor(kwargs)
        if isinstance(result, dict):
            out = result.get("output", str(result))
            success = result.get("success", True)
            return out if success else f"[失败] {out}"
        return str(result)


# ---------------------------------------------------------------------------
# Global tool registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """Singleton registry of all available tools."""

    _tools: list[Tool] = []
    _by_name: dict[str, Tool] = {}
    _mcp_tools: list[MCPTool] = []
    _mcp_by_name: dict[str, MCPTool] = {}

    @classmethod
    def register(cls, tool: Tool) -> None:
        if not tool.name:
            logger.warning("skipping tool registration with empty name: %s", tool)
            return
        if tool.name in cls._by_name:
            return  # already registered, skip
        cls._tools.append(tool)
        cls._by_name[tool.name] = tool

    @classmethod
    def get(cls, name: str) -> Tool | None:
        if t := cls._by_name.get(name):
            return t
        return cls._mcp_by_name.get(name)

    @classmethod
    def all_tools(cls) -> list[Tool]:
        return list(cls._tools) + list(cls._mcp_tools)

    @classmethod
    def specs(cls) -> list[dict]:
        """Export all tools as OpenAI function specs (skips tools with empty name)."""
        return [t.to_spec() for t in cls._tools + cls._mcp_tools if t.name]

    @classmethod
    def set_mcp_tools(cls, tool_dicts: list[dict]) -> None:
        """Replace current MCP-injected tool set (called by MCP Manager after connect/refresh)."""
        cls._mcp_tools = []
        cls._mcp_by_name.clear()
        for td in tool_dicts:
            executor = td.get("_executor")
            if not callable(executor):
                continue
            name = td.get("name", "")
            if not name:
                logger.warning("skipping MCP tool with empty name: %s", td)
                continue
            t = MCPTool(
                name=name,
                description=td.get("description", ""),
                parameters=td.get("parameters", {}),
                executor=executor,
                read_only=td.get("read_only", False),
            )
            cls._mcp_tools.append(t)
            cls._mcp_by_name[t.name] = t

    @classmethod
    def mcp_tools(cls) -> list[MCPTool]:
        """Return snapshot of current MCP tools."""
        return list(cls._mcp_tools)

    @classmethod
    def find_mcp_tool(cls, name: str) -> MCPTool | None:
        """Find an MCP tool by name; returns None if not found."""
        return cls._mcp_by_name.get(name)


def register_tools() -> None:
    """Register all built-in tools. Called once at startup."""
    from deepx.tools.builtins import (
        Read, Write, Glob, Grep, Bash, ListDir, Todo, CreatePlan,
        Memory, SwitchModel, WebSearch, WebFetch, OCR,
    )
    from deepx.tools.builtins.codegraph_tool import CodeGraphTool

    # Built-in tools
    for tool in [
        Read(),
        Write(),
        Glob(),
        Grep(),
        Bash(),
        ListDir(),
        Todo(),
        CreatePlan(),
        Memory(),
        SwitchModel(),
        WebSearch(),
        WebFetch(),
        OCR(),
    ]:
        ToolRegistry.register(tool)
        logger.debug("registered tool: %s", tool.name)

    # CodeGraph tools (all operations via one class)
    for name, description in [
        ("def", "Go to symbol definition"),
        ("refs", "Find all references to a symbol"),
        ("callers", "Find callers of a function"),
        ("callees", "Find callees of a function"),
        ("implementers", "Find interface implementers"),
        ("subtypes", "Find subtypes"),
        ("supertypes", "Find supertypes"),
        ("impact", "Impact analysis"),
        ("symbols", "List file symbols"),
        ("outline", "File outline"),
        ("imports", "File imports"),
    ]:
        ToolRegistry.register(CodeGraphTool(name, description))

    # Skill tools — lazy import to avoid circular dependency
    _register_skill_tools()
    logger.info("tools registered: %d total", len(ToolRegistry.all_tools()))


def _register_skill_tools() -> None:
    """Initialize skill loader and register skill tools."""
    import os

    from deepx.skill import Loader, extract_builtins
    from deepx.skill.tool import LoadSkillTool
    from deepx.skill.tool_registry import set_skill_loader

    # Extract built-in skills to ~/.deepx/skills/
    home = os.path.expanduser("~")
    extract_builtins(home)

    # Build workspace and global dirs
    cwd = os.getcwd()
    workspace_dirs = [
        os.path.join(cwd, ".deepx", "skills"),
    ]
    global_dirs = [
        os.path.join(os.path.expanduser("~"), ".agents", "skills"),
        os.path.join(os.path.expanduser("~"), ".claude", "skills"),
        os.path.join(os.path.expanduser("~"), ".deepx", "skills"),
    ]

    loader = Loader(workspace_dirs=workspace_dirs, global_dirs=global_dirs)
    set_skill_loader(loader)
    ToolRegistry.register(LoadSkillTool())