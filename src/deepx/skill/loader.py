"""
Skill loader — scans SKILL.md files from workspace and global directories.
Mirrors Go: ~/devspace/deepx-code/skill/skill.go
"""
from __future__ import annotations

import os
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class Metadata:
    """Lightweight skill metadata (name/description/scope/path, no body)."""
    name: str = ""
    description: str = ""
    scope: str = ""   # "global" | "workspace"
    path: str = ""    # absolute path to SKILL.md


@dataclass
class Skill:
    """Fully-loaded skill with body content."""
    name: str = ""
    description: str = ""
    scope: str = ""    # "global" | "workspace"
    path: str = ""     # absolute path to SKILL.md
    body: str = ""     # markdown body after frontmatter


def _split_frontmatter(content: str) -> tuple[str, str]:
    """
    Split YAML frontmatter from markdown body.

    Format: "---\n<yaml>\n---\n<body>"
    Returns (frontmatter_yaml, body). frontmatter_yaml is "" when no fm present.
    """
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", content
    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end < 0:
        return "", content
    fm = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1:])
    return fm, body


def _parse_meta(path: str) -> Metadata | None:
    """
    Read only frontmatter (no body) — used by List() for speed.
    Returns None if SKILL.md missing or malformed.
    """
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None

    fm, _ = _split_frontmatter(content)
    meta = Metadata(path=path)
    if fm:
        try:
            data = yaml.safe_load(fm)
            if data:
                meta.name = str(data.get("name", ""))
                meta.description = str(data.get("description", ""))
        except yaml.YAMLError:
            pass
    return meta


def _load_skill(path: str, scope: str) -> Skill | None:
    """Read full SKILL.md (frontmatter + body)."""
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None

    fm, body = _split_frontmatter(content)
    skill = Skill(path=path, scope=scope, body=body)
    if fm:
        try:
            data = yaml.safe_load(fm)
            if data:
                skill.name = str(data.get("name", ""))
                skill.description = str(data.get("description", ""))
        except yaml.YAMLError:
            pass
    return skill


def _scan_dir(dir_path: str, scope: str, seen: dict[str, Metadata]) -> None:
    """Scan a single directory, writing matched skills into `seen` (overwriting)."""
    if not dir_path:
        return
    try:
        entries = os.scandir(dir_path)
    except OSError:
        return

    for entry in entries:
        if not entry.is_dir():
            continue
        skill_path = os.path.join(dir_path, entry.name, "SKILL.md")
        meta = _parse_meta(skill_path)
        if meta is None:
            continue
        if not meta.name:
            meta.name = entry.name
        meta.scope = scope
        meta.path = skill_path
        seen[meta.name] = meta


class Loader:
    """
    Multi-directory skill scanner.

    WorkspaceDirs / GlobalDirs are ordered: later entries in the same group
    overwrite earlier ones. Workspace is always scanned AFTER global, so it wins.
    """

    def __init__(
        self,
        workspace_dirs: list[str] | None = None,
        global_dirs: list[str] | None = None,
    ) -> None:
        self.workspace_dirs: list[str] = workspace_dirs or []
        self.global_dirs: list[str] = global_dirs or []

    def all_dirs(self) -> list[str]:
        """All directories in scan order (global first, workspace last)."""
        return list(self.global_dirs) + list(self.workspace_dirs)

    def list(self) -> list[Metadata]:
        """
        Scan all directories, return skill metadata sorted by name.
        Same name: workspace overwrites global; within group, later overwrites earlier.
        """
        seen: dict[str, Metadata] = {}
        for d in self.global_dirs:
            _scan_dir(d, "global", seen)
        for d in self.workspace_dirs:
            _scan_dir(d, "workspace", seen)
        result = list(seen.values())
        result.sort(key=lambda m: m.name)
        return result

    def load(self, name: str) -> Skill | None:
        """
        Load a skill by name. Returns None if not found.
        Priority: workspace first, then global; within a group, first-found wins.
        """
        name = name.strip()
        if not name:
            return None

        for d in self.workspace_dirs:
            skill_path = os.path.join(d, name, "SKILL.md")
            if os.path.isfile(skill_path):
                return _load_skill(skill_path, "workspace")

        for d in self.global_dirs:
            skill_path = os.path.join(d, name, "SKILL.md")
            if os.path.isfile(skill_path):
                return _load_skill(skill_path, "global")

        return None