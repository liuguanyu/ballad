"""CodeGraph tool — unified interface for code navigation operations."""
from __future__ import annotations

from pathlib import Path

from deepx.codegraph.index import CodeGraph
from deepx.tools.base import Tool

# Global code graph instance (lazy init per workspace)
_graphs: dict[str, CodeGraph] = {}


def _get_graph(workspace: str | None = None) -> CodeGraph:
    """Get or create the CodeGraph for a workspace."""
    key = workspace or "default"
    if key not in _graphs:
        _graphs[key] = CodeGraph(workspace=workspace or ".")
    return _graphs[key]


class CodeGraphTool(Tool):
    """
    Code navigation operations: def, refs, callers, callees, impact, etc.

    Uses a two-phase approach:
    1. Fast syntax-level graph (tree-sitter) — immediate response
    2. Precise type-level analysis (go/types) — runs in background
    """

    def __init__(self, operation: str, description: str):
        self.operation = operation
        self.name = f"CodeGraph_{operation}"
        self.description = description
        self.parameters = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The symbol or query to search for.",
                },
                "file_path": {
                    "type": "string",
                    "description": "Optional file path to scope the search.",
                },
                "workspace": {
                    "type": "string",
                    "description": "Workspace root path. Defaults to current directory.",
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, file_path: str | None = None, workspace: str | None = None, **kwargs) -> str:
        graph = _get_graph(workspace)

        try:
            if self.operation == "def":
                results = graph.defn(query, file_path)
                if not results:
                    return f"[CodeGraph] 未找到符号 '{query}' 的定义"
                lines = [f"- {s.file}:{s.line}  {s.kind} {s.name}" for s in results]
                return "[CodeGraph 定义]\n" + "\n".join(lines)

            elif self.operation == "refs":
                results = graph.refs(query, file_path)
                if not results:
                    return f"[CodeGraph] 未找到 '{query}' 的引用"
                lines = [f"- {r.file}:{r.line}  {r.context[:60]}" for r in results]
                return f"[CodeGraph] 找到 {len(results)} 处引用:\n" + "\n".join(lines)

            elif self.operation == "callers":
                results = graph.callers(query)
                if not results:
                    return f"[CodeGraph] 未找到 '{query}' 的调用者"
                return "[CodeGraph 调用者]\n" + "\n".join(f"- {c}" for c in results)

            elif self.operation == "callees":
                results = graph.callees(query)
                if not results:
                    return f"[CodeGraph] 未找到 '{query}' 调用了任何已知的函数"
                return "[CodeGraph 被调用]\n" + "\n".join(f"- {c}" for c in results)

            elif self.operation == "impact":
                results = graph.impact(query)
                if not results:
                    return f"[CodeGraph] 未找到 '{query}' 的影响范围"
                lines = []
                for f, syms in sorted(results.items()):
                    lines.append(f"{f}:")
                    lines.extend(f"  - {s}" for s in syms)
                return "[CodeGraph 影响分析]\n" + "\n".join(lines)

            elif self.operation == "symbols":
                if not file_path:
                    return "[CodeGraph] symbols 操作需要提供 file_path"
                results = graph.symbols(file_path)
                if not results:
                    return f"[CodeGraph] 文件 {file_path} 中未找到符号"
                lines = [f"- {s.line:4d}  {s.kind:8s}  {s.name}" for s in results]
                return "[CodeGraph 文件符号]\n" + "\n".join(lines)

            elif self.operation == "outline":
                if not file_path:
                    return "[CodeGraph] outline 操作需要提供 file_path"
                results = graph.outline(file_path)
                if not results:
                    return f"[CodeGraph] 文件 {file_path} 中未找到顶层符号"
                lines = [f"- {s.line:4d}  {s.kind:8s}  {s.name}" for s in results]
                return "[CodeGraph 文件大纲]\n" + "\n".join(lines)

            elif self.operation == "imports":
                if not file_path:
                    return "[CodeGraph] imports 操作需要提供 file_path"
                results = graph.imports(file_path)
                if not results:
                    return f"[CodeGraph] 文件 {file_path} 中未找到 import"
                return "[CodeGraph 导入]\n" + "\n".join(f"- {s.name}" for s in results)

            else:
                return f"[CodeGraph] 未知操作: {self.operation}"
        except Exception as e:
            return f"[CodeGraph 错误] {e}"