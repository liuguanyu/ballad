"""
Skill sources — mirrors Go: ~/devspace/deepx-code/skill/source.go

Currently only built-in Clawhub registry.
"""
from __future__ import annotations

from dataclasses import dataclass


# Clawhub constants
SOURCE_ID_CLAWHUB = "clawhub"
CLAWHUB_BASE = "https://wry-manatee-359.convex.site"
CLAWHUB_WEB = "https://clawhub.ai"


@dataclass
class SkillSource:
    """A skill registry/source."""
    id: str
    name: str
    type: str   # "clawhub"
    url: str
    enabled: bool = True


@dataclass
class RemoteSkillInfo:
    """A skill found during remote search."""
    name: str = ""
    description: str = ""
    version: str = ""
    source_id: str = ""
    remote_ref: str = ""   # Clawhub slug
    author: str = ""
    url: str = ""
    downloads: int = 0
    stars: int = 0


_builtin_clawhub = SkillSource(
    id=SOURCE_ID_CLAWHUB,
    name="Clawhub",
    type="clawhub",
    url=CLAWHUB_BASE,
    enabled=True,
)


def list_sources() -> list[SkillSource]:
    """List all available skill sources (currently just Clawhub)."""
    return [_builtin_clawhub]