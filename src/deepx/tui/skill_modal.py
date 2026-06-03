"""
Skill search / install modal — mirrors Go: ~/devspace/deepx-code/tui/skill_modal.go

Multi-phase modal (Textual 8.x Screen-based):
  Stage 1: query input — Enter to search or direct-install
  Stage 2: searching — loading overlay
  Stage 3: results list — ↑↓ select, Enter install
  Stage 4: installing — loading overlay
  Esc always dismisses.
"""
from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from textual.app import ComposeResult, Screen
from textual.binding import Binding
from textual.containers import Container
from textual.message import Message
from textual.widgets import Button, Input, Label

from deepx.skill.install import delete as skill_delete
from deepx.skill.install import (
    installed_list,
    install_from_source,
    install as install_src,
)
from deepx.skill.search import search_skills

if TYPE_CHECKING:
    pass

# safe_name pattern — mirrors Go/regex: ^[a-zA-Z0-9._-]{1,64}$
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")


def _is_direct_install(s: str) -> bool:
    """Return True if input looks like a GitHub URL or local path."""
    s = s.strip()
    return (
        s.startswith("https://")
        or s.startswith("http://")
        or s.startswith("/")
        or s.startswith("./")
        or s.startswith("../")
        or s.startswith("~")
    )


# ─────────────────────────────────────────────────────────────────────────────
# Messages
# ─────────────────────────────────────────────────────────────────────────────


class SkillInstallSuccess(Message):
    """Fired after a skill is successfully installed."""

    def __init__(self, skill_name: str) -> None:
        super().__init__()
        self.skill_name = skill_name


class SkillInstallError(Message):
    """Fired after a skill install fails."""

    def __init__(self, skill_name: str, error: str) -> None:
        super().__init__()
        self.skill_name = skill_name
        self.error = error


# ─────────────────────────────────────────────────────────────────────────────
# SkillSearchModal
# ─────────────────────────────────────────────────────────────────────────────


class SkillSearchModal(Screen):
    """
    Search and install skills from Clawhub, GitHub URLs, or local paths.

    Design (mirrors Go skill_modal.go):
      - Stage 1: empty query prompt (Esc → dismiss)
      - Stage 2: searching spinner
      - Stage 3: results list (↑↓ navigate, Enter install, Esc dismiss)
      - Stage 4: installing spinner
      - Error messages displayed at bottom of each stage

    Events emitted:
      - SkillInstallSuccess / SkillInstallError on completion
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=True),
        Binding("enter", "submit", "Search / Install", show=True),
        Binding("up", "move_cursor", "Up", show=False),
        Binding("down", "move_cursor_down", "Down", show=False),
    ]

    # ── Internal state ───────────────────────────────────────────────────

    _stage: int = 0          # 0=query, 1=searching, 2=results, 3=installing
    _query: str = ""
    _results: list = []      # list[RemoteSkillInfo]
    _selected: int = 0
    _error: str = ""

    def __init__(self) -> None:
        super().__init__(classes="skill-modal")

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._stage = 0
        self._query = ""
        self._results = []
        self._selected = 0
        self._error = ""
        input_widget = self.query_one("#skill-search-input", Input)
        if input_widget:
            input_widget.focus()

    def compose(self) -> ComposeResult:
        yield from self._compose_body()

    def _compose_body(self) -> ComposeResult:
        """Yield widgets based on current stage."""
        # Title always shown
        yield Container(
            Label("安装 Skill", id="skill-modal-title"),
            id="skill-title-area",
        )

        if self._stage == 0:
            # Query input
            hint = (
                "输入关键词搜索 Clawhub，或直接粘贴 GitHub URL / 本地路径安装\n"
                "  • https://github.com/owner/repo\n"
                "  • https://github.com/anthropics/skills/tree/main/skills/docx\n"
                "  • ~/path/to/skill"
            )
            yield Label(hint, id="skill-hint", classes="skill-hint")
            yield Input(
                placeholder="搜索 Clawhub，或粘贴 URL / 路径直接安装...",
                id="skill-search-input",
            )
            if self._error:
                yield Label(f"✗ {self._error}", id="skill-error-msg", classes="skill-error")
            yield Label("Enter 搜索 / 安装  ·  Esc 关闭", id="skill-footer-hint", classes="skill-footer-hint")

        elif self._stage == 1:
            # Searching spinner
            yield Label("跨源搜索中…(最多 15s)", id="skill-searching-msg", classes="skill-status")
            yield Label(self._query, id="skill-searching-query", classes="skill-query-preview")

        elif self._stage == 2:
            # Results list
            yield from self._compose_results()

        elif self._stage == 3:
            # Installing spinner
            name = self._query
            if self._results and 0 <= self._selected < len(self._results):
                name = self._results[self._selected].name
            yield Label(f"正在下载并安装 {name}…", id="skill-installing-msg", classes="skill-status")
            yield Label("(最多 90s)", id="skill-installing-sub", classes="skill-installing-sub")

    def _compose_results(self) -> ComposeResult:
        """Yield result list widgets."""
        n = len(self._results)
        hint = f"搜到 {n} 个结果 (↑↓ 选 · Enter 安装 · Esc 关闭)"
        yield Label(hint, id="skill-results-hint", classes="skill-hint")

        for i, r in enumerate(self._results[:12]):
            meta_parts = [r.source_id or "clawhub"]
            if r.stars > 0:
                meta_parts.append(f"⭐ {r.stars}")
            if r.downloads > 0:
                meta_parts.append(f"📥 {r.downloads}")
            meta_str = " · ".join(meta_parts)

            line = f"▸ {r.name}  [{meta_str}]" if i == self._selected else f"  {r.name}  [{meta_str}]"
            if r.description:
                desc = r.description
                if len(desc) > 70:
                    desc = desc[:67] + "…"
                line += f"\n    {desc}"

            sel_cls = "skill-result-item skill-result-selected" if i == self._selected else "skill-result-item"
            yield Label(line, id=f"skill-result-{i}", classes=sel_cls)

        if n > 12:
            yield Label(f"  … 还有 {n - 12} 条未显示，请优化查询关键词", classes="skill-footer-hint")

        if self._error:
            yield Label(f"✗ {self._error}", classes="skill-error")

    # ── Actions ───────────────────────────────────────────────────────────

    def action_dismiss(self) -> None:
        self.app.pop_screen()

    async def action_submit(self) -> None:
        """Stage 0: submit query — search or direct install."""
        if self._stage == 0:
            input_widget = self.query_one("#skill-search-input", Input)
            q = input_widget.value.strip()

            if not q:
                self._error = "请输入关键词搜索，或粘贴 GitHub URL / 本地路径"
                self.refresh()
                return

            self._query = q
            self._error = ""

            if _is_direct_install(q):
                # Direct install (GitHub URL / local path)
                self._stage = 3
                self.refresh()
                await self._do_install()
            else:
                # Search Clawhub
                self._stage = 1
                self.refresh()
                await self._do_search()

        elif self._stage == 2:
            # Install selected result
            if self._results and 0 <= self._selected < len(self._results):
                self._stage = 3
                self.refresh()
                await self._do_install_from_result()

    def action_move_cursor(self) -> None:
        if self._stage != 2 or not self._results:
            return
        self._selected = max(0, self._selected - 1)
        self.refresh()

    def action_move_cursor_down(self) -> None:
        if self._stage != 2 or not self._results:
            return
        self._selected = min(len(self._results) - 1, self._selected + 1)
        self.refresh()

    # ── Background workers ───────────────────────────────────────────────

    async def _do_search(self) -> None:
        """Run skill search in background thread, then update stage to results."""
        try:
            results = await asyncio.get_event_loop().run_in_executor(
                None, search_skills, self._query, ""
            )
            self._results = results
            self._selected = 0
            self._stage = 2
            self.refresh()
        except Exception as e:
            self._error = f"搜索失败: {e}"
            self._stage = 0
            self.refresh()

    async def _do_install(self) -> None:
        """Run direct install (GitHub URL / local path) in background."""
        try:
            name = await asyncio.get_event_loop().run_in_executor(
                None, install_src, self._query
            )
            self.post_message(SkillInstallSuccess(name))
            self.app.pop_screen()
        except Exception as e:
            self._error = f"安装失败: {e}"
            self._stage = 0
            self.refresh()

    async def _do_install_from_result(self) -> None:
        """Install the currently selected result."""
        if not (self._results and 0 <= self._selected < len(self._results)):
            return
        r = self._results[self._selected]
        try:
            name = await asyncio.get_event_loop().run_in_executor(
                None, install_from_source, r.source_id, r.remote_ref
            )
            self.post_message(SkillInstallSuccess(name))
            self.app.pop_screen()
        except Exception as e:
            self._error = f"安装 {r.name} 失败: {e}"
            self._stage = 2
            self.refresh()

    # ── CSS ───────────────────────────────────────────────────────────────

    CSS = """
    SkillSearchModal {
        width: 80;
        height: auto;
        max-height: 30;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }

    #skill-title-area {
        margin-bottom: 1;
    }

    #skill-modal-title {
        color: $accent;
        text-style: bold;
    }

    .skill-hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    #skill-search-input {
        margin-bottom: 1;
    }

    .skill-error {
        color: $error;
    }

    .skill-footer-hint {
        color: $text-muted;
        margin-top: 1;
    }

    .skill-status {
        color: $text-muted;
        padding: 1 0;
    }

    .skill-query-preview {
        color: $text;
        text-style: italic;
    }

    #skill-results-hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    .skill-result-item {
        width: 100%;
        color: $text;
        margin: 0 0 0 0;
    }

    .skill-result-selected {
        background: $primary-darken-1;
        color: $text;
        text-style: bold;
    }

    .skill-installing-sub {
        color: $text-muted;
    }
    """


# ─────────────────────────────────────────────────────────────────────────────
# SkillsListModal
# ─────────────────────────────────────────────────────────────────────────────


class SkillsListModal(Screen):
    """
    List installed skills and allow deletion.

    Features:
      - Shows all skills in ~/.deepx/skills/
      - ↑↓ navigate, Enter → confirm-delete, Esc dismiss
      - Confirm step: "确定删除 <name>？" (Y/n)
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=True),
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "confirm", "Delete", show=True),
    ]

    _skills: list = []        # list[Metadata]
    _selected: int = 0
    _confirm: bool = False     # True = showing delete confirmation
    _loading: bool = True
    _error: str = ""

    def __init__(self) -> None:
        super().__init__(classes="skills-list-modal")

    def on_mount(self) -> None:
        self._loading = True
        self._confirm = False
        self._selected = 0
        self._error = ""
        self.run_worker(self._load_skills(), exclusive=True)

    async def _load_skills(self) -> None:
        try:
            skills = await asyncio.get_event_loop().run_in_executor(None, installed_list)
            self._skills = skills
        except Exception as e:
            self._error = f"读取已装 skill 失败: {e}"
            self._skills = []
        finally:
            self._loading = False
            self.refresh()

    def compose(self) -> ComposeResult:
        yield Container(
            Label("已安装 Skill", id="skills-list-title"),
            id="skills-list-header",
        )

        if self._loading:
            yield Label("加载中…", classes="skill-status")
            return

        if self._error:
            yield Label(f"✗ {self._error}", classes="skill-error")
            return

        if not self._skills:
            yield Label("~/.deepx/skills/ 下没有 deepx 管理的 skill", classes="skill-hint")
            yield Label("Esc 关闭", classes="skill-footer-hint")
            return

        if self._confirm:
            name = self._skills[self._selected].name if 0 <= self._selected < len(self._skills) else "?"
            yield Label(f"确定删除 skill「{name}」？", id="skills-confirm-prompt")
            yield Label("Enter 确认删除  ·  Esc 取消", classes="skill-footer-hint")
            return

        yield Label(f"{len(self._skills)} 个 skill (↑↓ 选 · Enter 删除 · Esc 关闭)", classes="skill-hint")

        for i, s in enumerate(self._skills):
            scope_label = "🌐" if s.scope == "global" else "📁"
            name = s.name or "(unnamed)"
            desc = s.description or ""
            if len(desc) > 60:
                desc = desc[:57] + "…"
            line = f"▸ {name} {scope_label}"
            sub = f"   {desc}" if desc else ""
            if i != self._selected:
                line = "  " + name + " " + scope_label
                sub = f"   {desc}" if desc else ""

            sel_cls = "skill-result-item skill-result-selected" if i == self._selected else "skill-result-item"
            if sub:
                yield Label(f"{line}\n{sub}", id=f"skill-item-{i}", classes=sel_cls)
            else:
                yield Label(line, id=f"skill-item-{i}", classes=sel_cls)

    def action_move_up(self) -> None:
        if self._confirm:
            return
        if not self._skills:
            return
        self._selected = max(0, self._selected - 1)
        self.refresh()

    def action_move_down(self) -> None:
        if self._confirm:
            return
        if not self._skills:
            return
        self._selected = min(len(self._skills) - 1, self._selected + 1)
        self.refresh()

    def action_confirm(self) -> None:
        """Stage 1: enter confirm mode. Stage 2: perform delete."""
        if not self._skills:
            return

        if self._confirm:
            # Actually delete
            name = self._skills[self._selected].name
            try:
                skill_delete(name)
                self.post_message(SkillDeleted(name))
            except Exception as e:
                self.post_message(SkillDeleteError(name, str(e)))
            self.app.pop_screen()
        else:
            # Enter confirm step
            self._confirm = True
            self.refresh()

    def action_dismiss(self) -> None:
        self.app.pop_screen()

    CSS = """
    SkillsListModal {
        width: 75;
        height: auto;
        max-height: 28;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }

    #skills-list-header {
        margin-bottom: 1;
    }

    #skills-list-title {
        color: $accent;
        text-style: bold;
    }

    #skills-confirm-prompt {
        color: $warning;
        text-style: bold;
        margin: 1 0;
    }

    .skill-status {
        color: $text-muted;
    }

    .skill-error {
        color: $error;
    }

    .skill-hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    .skill-footer-hint {
        color: $text-muted;
    }

    .skill-result-item {
        width: 100%;
        color: $text;
    }

    .skill-result-selected {
        background: $primary-darken-1;
        color: $text;
        text-style: bold;
    }
    """


class SkillDeleted(Message):
    def __init__(self, skill_name: str) -> None:
        super().__init__()
        self.skill_name = skill_name


class SkillDeleteError(Message):
    def __init__(self, skill_name: str, error: str) -> None:
        super().__init__()
        self.skill_name = skill_name
        self.error = error