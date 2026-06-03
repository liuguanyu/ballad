"""Write tool — write content to a file."""
from __future__ import annotations

import hashlib
from pathlib import Path

from deepx.tools.base import Tool


class Write(Tool):
    """Write content to a file, replacing existing content entirely."""

    name = "Write"
    description = "Write content to a file at the specified path. This will overwrite the existing file if there is one at the provided path. Use this tool to create new files or update existing files with new content. Be sure to use the exact content provided by the user."
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path of the file to write.",
            },
            "content": {
                "type": "string",
                "description": "The complete content to write to the file.",
            },
        },
        "required": ["file_path", "content"],
    }

    async def execute(self, file_path: str, content: str, **kwargs) -> str:
        path = Path(file_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            line_count = len(content.splitlines())
            byte_count = len(content.encode("utf-8"))
            return f"Wrote {line_count} lines, {byte_count} bytes to {file_path}"
        except Exception as e:
            return f"Error writing file: {e}"


class Update(Tool):
    """Update specific lines in a file using an Edit instruction."""

    name = "Update"
    description = "Update a file by replacing specific lines. Use this when you want to modify only part of a file rather than rewriting it entirely. Provide the file path, the old text to find (exact match), and the new text to replace it with."
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path of the file to update.",
            },
            "old_string": {
                "type": "string",
                "description": "The exact text in the file to replace. Must be an exact match including all whitespace and newlines.",
            },
            "new_string": {
                "type": "string",
                "description": "The new text to replace old_string with.",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    }

    async def execute(self, file_path: str, old_string: str, new_string: str, **kwargs) -> str:
        path = Path(file_path)
        if not path.exists():
            return f"Error: file not found: {file_path}"
        try:
            text = path.read_text(encoding="utf-8")
            if old_string not in text:
                return f"Error: old_string not found in file. Please check the exact content."
            new_text = text.replace(old_string, new_string, 1)
            path.write_text(new_text, encoding="utf-8")
            return f"Updated {file_path}"
        except Exception as e:
            return f"Error updating file: {e}"