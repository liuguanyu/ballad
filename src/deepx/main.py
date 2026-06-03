"""Unified entry point for DeepX."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_mcp_manager = None


def run():
    """Run DeepX: CLI or TUI based on arguments."""
    argv = sys.argv[1:]

    # If no args or shell/tui, launch full TUI
    if not argv or argv[0] in ("shell", "tui", "web"):
        _run_tui()
    else:
        # CLI mode
        from deepx.cli import app
        app()


def _run_tui():
    """Launch the TUI."""
    from deepx.tools.base import register_tools
    from deepx.skill.builtin import extract_builtins
    from deepx.skill.tool_registry import set_skill_loader
    from deepx.skill.loader import Loader
    from deepx.tui.app import DeepXTUI

    register_tools()

    home = str(Path.home())
    extract_builtins(home)

    cwd = str(Path.cwd())
    workspace_skills = os.path.join(cwd, ".deepx", "skills")
    loader = Loader(
        workspace_dirs=[workspace_skills],
        global_dirs=[
            os.path.join(home, ".agents", "skills"),
            os.path.join(home, ".claude", "skills"),
            os.path.join(home, ".deepx", "skills"),
        ],
    )
    set_skill_loader(loader)

    global _mcp_manager
    _mcp_manager = asyncio.run(_init_mcp())

    app = DeepXTUI(workspace=Path.cwd())
    app.run()


async def _init_mcp():
    from deepx.mcp.manager import Manager
    manager = Manager()
    await manager.connect_all()
    await manager.refresh_tools()
    return manager


if __name__ == "__main__":
    run()