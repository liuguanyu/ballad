"""
Built-in skills — mirrors Go: ~/devspace/deepx-code/skill/builtin.go

Extracts embedded skills from the package to ~/.deepx/skills/.
Uses version file to skip redundant writes.
"""
from __future__ import annotations

import os
import shutil
import importlib.resources
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Version tag — bumped on release, "dev" for local builds
BUILTIN_VERSION = "dev"

# Package resources path: deepx/skill/skills/
_RESOURCES_PATH = Path(__file__).parent / "skills"


def extract_builtins(home: str | None = None) -> str:
    """
    Extract embedded skills to ~/.deepx/skills/.

    Reads embedded skills from the package (deepx/skill/skills/).
    Checks version file to avoid redundant writes.
    Returns the skills directory path.
    """
    if home is None:
        home = os.path.expanduser("~")
    dest = os.path.join(home, ".deepx", "skills")
    ver_file = os.path.join(dest, ".builtin_version")

    # dev build always re-extracts (so changes to embedded skills take effect immediately)
    if BUILTIN_VERSION != "dev":
        try:
            with open(ver_file, encoding="utf-8") as f:
                if f.read().strip() == BUILTIN_VERSION:
                    return dest
        except FileNotFoundError:
            pass

    os.makedirs(dest, exist_ok=True)

    # Copy each skill directory
    _copy_builtin_dir(_RESOURCES_PATH, dest)

    # Write version tag
    with open(ver_file, "w", encoding="utf-8") as f:
        f.write(BUILTIN_VERSION)

    return dest


def _copy_builtin_dir(src: Path, dst: str) -> None:
    """Recursively copy a directory from package resources to filesystem."""
    if not src.is_dir():
        return
    os.makedirs(dst, exist_ok=True)
    for entry in src.iterdir():
        dst_path = os.path.join(dst, entry.name)
        if entry.is_dir():
            _copy_builtin_dir(entry, dst_path)
        else:
            data = entry.read_bytes()
            with open(dst_path, "wb") as f:
                f.write(data)
            os.chmod(dst_path, 0o644)