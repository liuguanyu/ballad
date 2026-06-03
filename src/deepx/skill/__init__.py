"""
Skill system — mirrors Go: ~/devspace/deepx-code/skill/

Exports:
  - Loader, Metadata, Skill: local skill management
  - SkillSource, RemoteSkillInfo: remote source metadata
  - list_sources: list available sources
  - search_skills: search remote sources
  - install, install_from_source, installed_list, installed_dir, delete, safe_name: install ops
  - extract_builtins: extract bundled skills
  - LoadSkillTool: tool for LLM to load skills
"""
from __future__ import annotations

from deepx.skill.loader import Loader, Metadata, Skill
from deepx.skill.source import (
    SkillSource,
    RemoteSkillInfo,
    list_sources,
)
from deepx.skill.search import search_skills
from deepx.skill.install import (
    install,
    install_from_source,
    installed_list,
    installed_dir,
    delete,
    safe_name,
)
from deepx.skill.builtin import extract_builtins, BUILTIN_VERSION
from deepx.skill.tool import LoadSkillTool

__all__ = [
    # Core types
    "Loader",
    "Metadata",
    "Skill",
    "SkillSource",
    "RemoteSkillInfo",
    # Source
    "list_sources",
    # Search
    "search_skills",
    # Install
    "install",
    "install_from_source",
    "installed_list",
    "installed_dir",
    "delete",
    "safe_name",
    # Builtin
    "extract_builtins",
    "BUILTIN_VERSION",
    # Tool
    "LoadSkillTool",
]