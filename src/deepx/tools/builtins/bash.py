"""Bash tool — execute shell commands."""
from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from deepx.tools.base import Tool


class Bash(Tool):
    """Execute a shell command in the workspace directory."""

    name = "Bash"
    description = "Execute a shell command. Use for git operations, running tests, installing packages, compiling, and any other command-line operations. Returns stdout + stderr output. For long-running commands, consider using a timeout. The command runs in the workspace directory."
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds. Default 60. Max 300.",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for the command. Defaults to workspace root.",
            },
        },
        "required": ["command"],
    }

    async def execute(
        self,
        command: str,
        timeout: int = 60,
        cwd: str | None = None,
        workspace: str | None = None,
        **kwargs,
    ) -> str:
        if timeout > 300:
            timeout = 300
        workdir = Path(cwd or workspace or ".")
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(workdir),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            result = out
            if err:
                result += f"\n[stderr]\n{err}"
            if proc.returncode != 0:
                result += f"\n[exit code: {proc.returncode}]"
            return result or "(no output)"
        except asyncio.TimeoutError:
            proc.terminate()
            return f"Error: command timed out after {timeout} seconds"
        except Exception as e:
            return f"Error executing command: {e}"