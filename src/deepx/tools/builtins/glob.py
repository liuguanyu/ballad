"""Glob tool — find files by pattern."""
from __future__ import annotations

from pathlib import Path

from deepx.tools.base import Tool


class Glob(Tool):
    """Find files matching a glob pattern. Returns a list of file paths."""

    name = "Glob"
    description = "Find all files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts', '*.md'). Use this to discover files when you don't know the exact path, or to find all files of a certain type in a directory tree."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern. Supports ** for recursive, * for any characters.",
            },
            "path": {
                "type": "string",
                "description": "Root directory to search from. Defaults to workspace root.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results. Default 100.",
            },
        },
        "required": ["pattern"],
    }

    async def execute(
        self,
        pattern: str,
        path: str | None = None,
        max_results: int = 100,
        workspace: str | None = None,
        **kwargs,
    ) -> str:
        search_dir = Path(path or workspace or ".")
        if not search_dir.exists():
            return f"Error: path not found: {search_dir}"

        matches: list[str] = []
        for file in search_dir.glob(pattern):
            if file.is_file():
                rel = file.relative_to(search_dir)
                matches.append(str(rel))
                if len(matches) >= max_results:
                    break

        if not matches:
            return f"No files found matching: {pattern}"
        return f"[{len(matches)} files]\n" + "\n".join(matches)