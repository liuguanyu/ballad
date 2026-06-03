"""Grep tool — search for patterns in files."""
from __future__ import annotations

from pathlib import Path

from deepx.tools.base import Tool


class Grep(Tool):
    """Search for a pattern in files using regex. Returns matching lines with file:line:content format."""

    name = "Grep"
    description = "Search for a text pattern or regex in files. Returns matching lines in 'file:line:content' format. Supports regex patterns. Use this to find function definitions, import statements, error messages, TODO comments, and any other text patterns across files."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for. Case-insensitive by default.",
            },
            "path": {
                "type": "string",
                "description": "Directory or file path to search in. Defaults to workspace root.",
            },
            "file_pattern": {
                "type": "string",
                "description": "File glob pattern to filter files, e.g. '*.py', '*.go'.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of matching lines to return. Default 50.",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Whether the search is case-sensitive. Default false.",
            },
        },
        "required": ["pattern"],
    }

    async def execute(
        self,
        pattern: str,
        path: str | None = None,
        file_pattern: str | None = None,
        max_results: int = 50,
        case_sensitive: bool = False,
        workspace: str | None = None,
        **kwargs,
    ) -> str:
        import re

        search_dir = Path(path or workspace or ".")
        if not search_dir.exists():
            return f"Error: path not found: {search_dir}"

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Error: invalid regex: {e}"

        matches: list[str] = []
        for file in search_dir.rglob(file_pattern or "*"):
            if not file.is_file():
                continue
            if file.name.startswith("."):
                continue
            try:
                lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            for i, line in enumerate(lines, 1):
                if regex.search(line):
                    matches.append(f"{file}:{i}:{line.rstrip()}")
                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break

        if not matches:
            return f"No matches found for: {pattern}"
        header = f"[{len(matches)} matches for '{pattern}']\n"
        return header + "\n".join(matches)