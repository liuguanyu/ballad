"""Read tool — read file contents."""
from __future__ import annotations

from pathlib import Path

from deepx.tools.base import Tool


class Read(Tool):
    """Read the full contents of a file."""

    name = "Read"
    description = "Read the complete contents of a file. Use this when you need to see the current contents of a file. Returns the full file content as text. For large files (>1000 lines), only the first 500 lines are returned unless line_range is specified."
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to read.",
            },
            "line_range": {
                "type": "string",
                "description": "Optional line range in 'start-end' format, e.g. '1-50' for first 50 lines.",
            },
        },
        "required": ["file_path"],
    }

    async def execute(self, file_path: str, line_range: str | None = None, **kwargs) -> str:
        path = Path(file_path)
        if not path.exists():
            return f"Error: file not found: {file_path}"
        if not path.is_file():
            return f"Error: not a file: {file_path}"

        try:
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()

            if line_range:
                try:
                    start_str, end_str = line_range.split("-")
                    start = int(start_str.strip())
                    end = int(end_str.strip())
                    lines = lines[start - 1 : end]  # 1-indexed
                    text = "\n".join(lines)
                except Exception:
                    return f"Error: invalid line_range format '{line_range}'. Use 'start-end' format."
            elif len(lines) > 1000:
                text = "\n".join(lines[:500])
                text += f"\n... [truncated, {len(lines) - 1000} more lines]"

            return text
        except Exception as e:
            return f"Error reading file: {e}"