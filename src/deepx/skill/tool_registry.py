"""Tool registry for skill loader injection (mirrors Go's tools.SetSkillLoader)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepx.skill import Loader

_current_loader: "Loader | None" = None


def set_skill_loader(loader: "Loader") -> None:
    """Inject the skill loader (called once at startup from tui.initialModel)."""
    global _current_loader
    _current_loader = loader


def get_skill_loader() -> "Loader | None":
    """Get the current skill loader."""
    return _current_loader