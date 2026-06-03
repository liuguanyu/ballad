"""
DeepX Logging — structured, rotated log output.

Log files: ~/.deepx/logs/
  deepx.log          — all modules
  deepx-agent.log   — agent/runner (LLM calls, tool executions)
  deepx-mcp.log     — MCP connections
  deepx-tools.log   — tool invocations

Default level: DEBUG in TTY (interactive), INFO otherwise.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Literal

# Log level by environment
_DEFAULT_LEVEL = logging.DEBUG if sys.stderr.isatty() else logging.INFO

# All known module names → log file suffix
_MODULES: dict[str, str] = {
    "deepx.agent": "agent",
    "deepx.mcp": "mcp",
    "deepx.tools": "tools",
    "deepx.tui": "tui",
    "deepx.llm": "llm",
    "deepx.graph": "graph",
}


def _log_dir() -> Path:
    d = Path.home() / ".deepx" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_logging(
    level: int | None = None,
    log_file: bool = True,
    console: bool = True,
) -> None:
    """
    Configure logging for all deepx modules.

    Call once at startup.
    """
    if level is None:
        level = _DEFAULT_LEVEL

    root = logging.getLogger("deepx")
    root.setLevel(level)
    if root.handlers:
        return  # Already configured

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt)

    # ── Console handler ──────────────────────────────────────────────────
    if console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(level)
        ch.setFormatter(formatter)
        root.addHandler(ch)

    # ── Per-module rotating file handlers ────────────────────────────────
    if log_file:
        from logging.handlers import RotatingFileHandler

        log_dir = _log_dir()
        seen_suffixes: set[str] = set()

        for module_prefix, suffix in _MODULES.items():
            if suffix in seen_suffixes:
                continue
            seen_suffixes.add(suffix)

            fh = RotatingFileHandler(
                log_dir / f"deepx-{suffix}.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            fh.setLevel(logging.DEBUG)  # File gets everything
            fh.setFormatter(formatter)
            root.addHandler(fh)

        # Main combined log
        main = RotatingFileHandler(
            log_dir / "deepx.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        main.setLevel(level)
        main.setFormatter(formatter)
        root.addHandler(main)


def get_logger(name: str) -> logging.Logger:
    """Get a logger for the given module name."""
    return logging.getLogger(f"deepx.{name}")


# ── Convenience loggers (pre-bound) ─────────────────────────────────────────

def agent_logger() -> logging.Logger:
    return logging.getLogger("deepx.agent")


def mcp_logger() -> logging.Logger:
    return logging.getLogger("deepx.mcp")


def tools_logger() -> logging.Logger:
    return logging.getLogger("deepx.tools")


def llm_logger() -> logging.Logger:
    return logging.getLogger("deepx.llm")