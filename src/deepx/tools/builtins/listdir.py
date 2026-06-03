"""ListDir tool — list directory contents."""
from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime

from deepx.tools.base import Tool


class ListDir(Tool):
    """List the contents of a directory with details (files, subdirs, sizes, dates)."""

    name = "ListDir"
    description = "List the contents of a directory showing files, subdirectories, sizes, and modification dates. Use this to explore the directory structure and understand what files exist in a location."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to list. Defaults to workspace root.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of entries. Default 50.",
            },
            "show_hidden": {
                "type": "boolean",
                "description": "Show hidden files (starting with .). Default false.",
            },
        },
        "required": [],
    }

    async def execute(
        self,
        path: str | None = None,
        max_results: int = 50,
        show_hidden: bool = False,
        workspace: str | None = None,
        **kwargs,
    ) -> str:
        target = Path(path or workspace or ".")
        if not target.exists():
            return f"Error: path not found: {target}"
        if not target.is_dir():
            return f"Error: not a directory: {target}"

        entries = []
        for entry in sorted(target.iterdir()):
            if entry.name.startswith(".") and not show_hidden:
                continue
            try:
                stat = entry.stat()
                size = stat.st_size if entry.is_file() else 0
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                kind = "DIR " if entry.is_dir() else f"{size:>10}"
                entries.append(f"  {kind}  {mtime}  {entry.name}")
            except Exception:
                entries.append(f"  ?    ???       {entry.name}")

            if len(entries) >= max_results:
                entries.append(f"  ... [{max_results} entries shown]")
                break

        if not entries:
            return f"(empty directory)"
        return "\n".join([f"[{target}]"] + entries)