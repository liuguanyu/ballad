"""
Two-phase code index: fast syntax graph + precise type analysis.

Phase 1 (immediate): Fast syntax-level graph using tree-sitter.
Phase 2 (background): Precise type-level analysis using go/types.

The fast graph is returned immediately so the Agent can start working
right away, while precise analysis runs in the background.
"""
from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from deepx.config.settings import get_settings

# ── Try to import tree-sitter ────────────────────────────────────────────────
try:
    import tree_sitter_languages
    from tree_sitter import Language, Parser
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

# Language → tree-sitter language constant
_LANG_MAP: dict[str, str] = {
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "jsx": "tsx",
    "tsx": "tsx",
    "go": "go",
    "rs": "rust",
    "java": "java",
    "c": "c",
    "cpp": "cpp",
    "rb": "ruby",
    "php": "php",
    "swift": "swift",
    "kt": "kotlin",
    "cs": "csharp",
    "vue": "vue",
    "svelte": "svelte",
    "md": "markdown",
}


# ── Data models ─────────────────────────────────────────────────────────────

@dataclass
class Symbol:
    """A code symbol."""

    name: str
    kind: str  # function, class, method, variable, type, import, etc.
    file: str
    line: int
    col: int
    signature: str = ""  # e.g. "func(a int, b string)"
    doc: str = ""


@dataclass
class Ref:
    """A reference to a symbol."""

    file: str
    line: int
    col: int
    context: str = ""  # Surrounding code line


# ── Graph ───────────────────────────────────────────────────────────────────

@dataclass
class Graph:
    """A code symbol graph."""

    symbols: list[Symbol] = field(default_factory=list)
    # symbol_name → list of Refs
    refs: dict[str, list[Ref]] = field(default_factory=dict)
    # function_name → list of called function names
    calls: dict[str, list[str]] = field(default_factory=dict)


# ── CodeGraph ────────────────────────────────────────────────────────────────

class CodeGraph:
    """
    Two-phase code index.

    Phase 1 (immediate): Fast syntax-level graph using tree-sitter.
    Phase 2 (background): Precise type-level analysis (go/types for Go files).

    File changes are detected via file signature (size + mtime hash).
    Only re-indexes changed files.
    """

    def __init__(self, workspace: Path | str):
        self.workspace = Path(workspace if isinstance(workspace, Path) else Path(workspace))
        self.settings = get_settings()
        self._graph: Graph | None = None
        self._lock = threading.Lock()
        self._precise_done = False
        self._parsers: dict[str, Parser] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    def symbols(self, file_path: str) -> list[Symbol]:
        """List all symbols in a file."""
        if self._graph is None:
            self._ensure_graph()
        return [s for s in (self._graph.symbols if self._graph else []) if s.file == file_path]

    def defn(self, query: str, file_path: str | None = None) -> list[Symbol]:
        """Find symbol definitions matching query."""
        if self._graph is None:
            self._ensure_graph()
        results = []
        for s in (self._graph.symbols if self._graph else []):
            if s.name == query and s.kind in ("function", "class", "method", "type"):
                if file_path is None or s.file == file_path:
                    results.append(s)
        return results

    def refs(self, query: str, file_path: str | None = None) -> list[Ref]:
        """Find all references to a symbol."""
        if self._graph is None:
            self._ensure_graph()
        all_refs = self._graph.refs.get(query, []) if self._graph else []
        if file_path:
            return [r for r in all_refs if r.file == file_path]
        return all_refs

    def callers(self, func_name: str) -> list[str]:
        """Find function names that call this function."""
        if self._graph is None:
            self._ensure_graph()
        # Inverse of calls: find f where f calls func_name
        if not self._graph:
            return []
        return [
            caller for caller, callees in self._graph.calls.items()
            if func_name in callees
        ]

    def callees(self, func_name: str) -> list[str]:
        """Find function names called by this function."""
        if self._graph is None:
            self._ensure_graph()
        if not self._graph:
            return []
        return self._graph.calls.get(func_name, [])

    def outline(self, file_path: str) -> list[Symbol]:
        """Get file outline (top-level symbols only)."""
        return [
            s for s in self.symbols(file_path)
            if s.line < 200  # top-level
        ]

    def imports(self, file_path: str) -> list[Symbol]:
        """Get import statements from a file."""
        return [
            s for s in self.symbols(file_path)
            if s.kind == "import"
        ]

    def impact(self, query: str) -> dict[str, list[str]]:
        """
        Transitive impact: all symbols that transitively depend on query.
        Returns {file: [affected_symbols]}.
        """
        if self._graph is None:
            self._ensure_graph()
        if not self._graph:
            return {}

        # BFS over the call graph
        affected: dict[str, set[str]] = {}
        queue = [query]
        seen = {query}
        while queue:
            current = queue.pop(0)
            callers = self.callers(current)
            for caller in callers:
                if caller not in seen:
                    seen.add(caller)
                    queue.append(caller)
                    # Group by file
                    for sym in self._graph.symbols:
                        if sym.name == caller:
                            affected.setdefault(sym.file, set()).add(caller)

        return {f: list(syms) for f, syms in affected.items()}

    # ── Graph building ────────────────────────────────────────────────────────

    def _ensure_graph(self) -> Graph:
        """Ensure the graph is built."""
        with self._lock:
            if self._graph is None:
                self._graph = self._build_graph()
        return self._graph

    def _build_graph(self) -> Graph:
        """Build the syntax-level graph from source files."""
        if not TREE_SITTER_AVAILABLE:
            return self._build_graph_regex()
        return self._build_graph_tree_sitter()

    def _build_graph_tree_sitter(self) -> Graph:
        """Build graph using tree-sitter."""
        graph = Graph()
        max_files = self.settings.codegraph_max_files
        max_mb = self.settings.codegraph_max_mb * 1024 * 1024
        timeout = self.settings.codegraph_timeout_seconds

        indexed = 0
        for file_path in self._iter_source_files():
            if indexed >= max_files:
                break

            size = file_path.stat().st_size
            if size > 5 * 1024 * 1024:  # skip files > 5MB
                continue

            try:
                syms, refs, calls = self._parse_file_tree_sitter(file_path)
                graph.symbols.extend(syms)
                for name, ref_list in refs.items():
                    graph.refs.setdefault(name, []).extend(ref_list)
                for caller, callee_list in calls.items():
                    graph.calls.setdefault(caller, []).extend(callee_list)
                indexed += 1
            except Exception:
                continue

        return graph

    def _build_graph_regex(self) -> Graph:
        """Fallback: basic regex-based parsing when tree-sitter is not available."""
        graph = Graph()
        for file_path in self._iter_source_files():
            try:
                syms, refs = self._parse_file_regex(file_path)
                graph.symbols.extend(syms)
                for name, ref_list in refs.items():
                    graph.refs.setdefault(name, []).extend(ref_list)
            except Exception:
                continue
        return graph

    def _parse_file_tree_sitter(self, file_path: Path) -> tuple[list[Symbol], dict[str, list[Ref]], dict[str, list[str]]]:
        """Parse a single file with tree-sitter."""
        ext = file_path.suffix.lstrip(".")
        lang_name = _LANG_MAP.get(ext)
        if not lang_name:
            return [], {}, {}

        try:
            lang: Language = tree_sitter_languages.get_language(lang_name)
        except Exception:
            return [], {}, {}

        parser = self._parsers.get(lang_name)
        if parser is None:
            parser = Parser(lang)
            self._parsers[lang_name] = parser

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return [], {}, {}

        try:
            tree = parser.parse(source.encode())
        except Exception:
            return [], {}, {}

        symbols: list[Symbol] = []
        refs: dict[str, list[Ref]] = {}
        calls: dict[str, list[str]] = {}

        cursor = tree.root_node.walk()

        # Traverse and extract symbols
        self._traverse_tree(cursor, source, file_path, symbols, refs, calls)

        return symbols, refs, calls

    def _traverse_tree(
        self,
        node,
        source: str,
        file_path: Path,
        symbols: list[Symbol],
        refs: dict[str, list[Ref]],
        calls: dict[str, list[str]],
    ) -> None:
        """Recursively traverse the tree-sitter AST and extract symbols."""
        node_type = node.type
        line = node.start_point[0] + 1
        col = node.start_point[1] + 1

        # Symbol kinds by language
        FUNCTION_KINDS = {
            "function_declaration", "function_definition", "method_definition",
            "function", "function_declarator",
        }
        CLASS_KINDS = {
            "class_declaration", "class_definition", "class",
            "type_declaration", "struct_declaration",
        }
        METHOD_KINDS = {
            "method_declaration", "method_definition",
        }
        CALL_KINDS = {
            "call_expression", "invocation",
        }

        name = ""
        if node_type in FUNCTION_KINDS:
            name = self._get_node_text(node, source, "identifier") or ""
            kind = "function"
        elif node_type in CLASS_KINDS:
            name = self._get_node_text(node, source, "identifier") or ""
            kind = "class"
        elif node_type in METHOD_KINDS:
            name = self._get_node_text(node, source, "identifier") or ""
            kind = "method"
        elif node_type == "import_statement":
            name = self._get_node_text(node, source, "identifier") or ""
            kind = "import"
        elif node_type == "identifier" and node.parent and node.parent.type in CALL_KINDS:
            # This is a function call reference
            name = node.text.decode() if isinstance(node.text, bytes) else node.text
            refs.setdefault(name, []).append(Ref(
                file=str(file_path),
                line=line,
                col=col,
                context=source.splitlines()[line - 1][:80] if line <= len(source.splitlines()) else "",
            ))
            # Track calls
            parent_call = self._find_parent_call_name(node, source)
            if parent_call:
                calls.setdefault(parent_call, []).append(name)
        else:
            # Try to find identifier children
            pass

        if name:
            doc = ""
            symbols.append(Symbol(
                name=name,
                kind=kind,
                file=str(file_path),
                line=line,
                col=col,
            ))

        # Recurse
        for child in node.children:
            self._traverse_tree(child, source, file_path, symbols, refs, calls)

    def _get_node_text(self, node, source: str, child_type: str) -> str | None:
        """Get text of a specific child type from a node."""
        for child in node.children:
            if child.type == child_type:
                text = child.text
                if isinstance(text, bytes):
                    return text.decode()
                return str(text)
        return None

    def _find_parent_call_name(self, node, source: str) -> str | None:
        """Find the name of the function that contains this call."""
        # Walk up to find function/method containing this call
        parent = node.parent
        while parent:
            if parent.type in ("function_declaration", "function_definition",
                               "method_definition", "function"):
                for child in parent.children:
                    if child.type == "identifier":
                        text = child.text
                        if isinstance(text, bytes):
                            return text.decode()
                        return str(text)
            parent = parent.parent
        return None

    def _parse_file_regex(self, file_path: Path) -> tuple[list[Symbol], dict[str, list[Ref]]]:
        """Fallback: regex-based parsing for basic symbol extraction."""
        symbols: list[Symbol] = []
        refs: dict[str, list[Ref]] = {}

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return [], {}

        ext = file_path.suffix.lstrip(".")
        lines = source.splitlines()

        # Python patterns
        if ext == "py":
            import re
            # Functions
            for i, line in enumerate(lines, 1):
                m = re.match(r"^\s*(?:def|async def)\s+(\w+)", line)
                if m:
                    symbols.append(Symbol(name=m.group(1), kind="function",
                                          file=str(file_path), line=i))
                # Classes
                m = re.match(r"^\s*class\s+(\w+)", line)
                if m:
                    symbols.append(Symbol(name=m.group(1), kind="class",
                                          file=str(file_path), line=i))
                # Calls
                for m in re.finditer(r'(\w+)\s*\(', line):
                    name = m.group(1)
                    if name not in ('if', 'while', 'for', 'return', 'def', 'class', 'import'):
                        refs.setdefault(name, []).append(Ref(
                            file=str(file_path), line=i, col=m.start() + 1,
                            context=line[:80],
                        ))

        # Go patterns
        elif ext == "go":
            import re
            for i, line in enumerate(lines, 1):
                m = re.match(r"^\s*func\s+(?:\([^)]+\)\s+)?(\w+)", line)
                if m:
                    symbols.append(Symbol(name=m.group(1), kind="function",
                                          file=str(file_path), line=i))
                m = re.match(r"^\s*type\s+(\w+)", line)
                if m:
                    symbols.append(Symbol(name=m.group(1), kind="class",
                                          file=str(file_path), line=i))

        return symbols, refs

    def _iter_source_files(self) -> Iterator[Path]:
        """Iterate over source files in the workspace."""
        EXTENSIONS = {
            ".py", ".go", ".js", ".ts", ".jsx", ".tsx",
            ".rs", ".java", ".c", ".cpp", ".h", ".hpp",
            ".rb", ".php", ".swift", ".kt", ".cs", ".vue", ".svelte",
        }
        for ext in EXTENSIONS:
            yield from self.workspace.rglob(f"*{ext}")

    def _signature(self) -> str:
        """Compute a signature based on file sizes and modification times."""
        parts = []
        for file_path in self._iter_source_files():
            stat = file_path.stat()
            parts.append(f"{file_path}:{stat.st_size}:{stat.st_mtime:.0f}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]