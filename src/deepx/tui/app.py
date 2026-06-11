"""DeepX TUI App — main Textual application."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Header

from deepx.agent.runner import AgentRunner
from deepx.config.settings import get_settings
from deepx.graph import build_workflow, get_initial_state
from deepx.mcp.manager import Manager
from deepx.session.manager import SessionManager
from deepx.session.store import SessionStore
from deepx.tui.input_area import InputArea, InputSubmitted, NavigateHistory
from deepx.tui.message_list import MessageList
from deepx.tui.skill_modal import (
    SkillDeleted,
    SkillDeleteError,
    SkillInstallError,
    SkillInstallSuccess,
    SkillsListModal,
    SkillSearchModal,
)
from deepx.tui.token_panel import TokenPanel
from deepx.tui.styles import DEEPX_CSS


class DeepXTUI(App):
    """
    DeepX Terminal UI — Claude Code-style layout.

    ┌────────────────────────────────────┬──────────────────┐
    │  Header                            │                  │
    ├──────────────────────────────────┤  TokenPanel      │
    │  MessageList                      │  (Ctrl+T toggle) │
    │  (scrollable, flex-grow: 1)       │                  │
    ├──────────────────────────────────┤                  │
    │  [Input area — dock: bottom]      │                  │
    └────────────────────────────────────┴──────────────────┘
    """

    CSS = DEEPX_CSS

    BINDINGS = [
        Binding("ctrl+t", "toggle_panel", "Status", show=True),
        Binding("ctrl+h", "toggle_token_hint", "Hint", show=True),
        Binding("ctrl+o", "toggle_expand", "Expand", show=True),
        Binding("ctrl+l", "clear", "Clear", show=True),
        Binding("ctrl+n", "new_conv", "New Chat", show=True),
        Binding("ctrl+s", "save", "Save", show=True),
        Binding("ctrl+k", "open_skills", "Skills", show=True),
        Binding("ctrl+shift+k", "open_skill_add", "Add Skill", show=True),
    ]

    def __init__(
        self,
        workspace: Path | str = ".",
        session_id: str | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.workspace = Path(workspace if isinstance(workspace, Path) else Path(workspace))
        self.session_id = session_id or "default"
        self.settings = get_settings()
        self.panel_visible = False

        # Core components
        self.message_list = MessageList()
        self.token_panel = TokenPanel()

        # Session store + manager (persistence)
        self.session_store = SessionStore(workspace=str(self.workspace))
        self.session_manager = SessionManager(workspace=str(self.workspace))

        # LangGraph workflow (streaming via astream + astream_events)
        self._workflow = build_workflow(self.session_id)
        self._app_state = get_initial_state(self.session_id)

        # Agent state (must be before _app_state["_mode"] reference)
        self._mode = "review"  # auto | review | plan
        self._app_state["_mode"] = self._mode

        # Load existing history into workflow state
        history = self.session_manager.history
        if history:
            self._app_state["messages"] = history
            for item in history:
                if isinstance(item, dict) and item.get("role") == "user":
                    content = str(item.get("content", "")).strip()
                    if content:
                        self.session_manager.add_input_history(content)

        # Agent runner (for /run subprocess executor)
        self.runner = AgentRunner(workspace=str(self.workspace), session_store=self.session_store)

        # MCP manager
        self.mcp_manager = Manager()

        # Agent state
        self._streaming = False
        self._streaming_msg_id: str | None = None
        self._assistant_content: str = ""  # accumulate for storage
        self._usage_input: int = 0
        self._usage_output: int = 0
        self._usage_cache: int = 0
        self._display_input_tokens: int = 0
        self._display_output_tokens: int = 0
        self._display_cache_tokens: int = 0
        self._token_hint_visible = True
        self._token_anim_task: asyncio.Task | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.title = "DeepX"
        self.sub_title = f"Mode: {self._mode} | Workspace: {self.workspace}"

        # Register tools and start MCP in background
        self._start_background()
        
        # Auto focus input area
        self.query_one("#input", InputArea).focus()
        self._render_history_hint()

    def _start_background(self) -> None:
        """Register tools and connect MCP servers (non-blocking)."""
        from deepx.logging_config import setup_logging
        from deepx.tools.base import register_tools

        setup_logging()
        register_tools()

        async def init_mcp():
            await self.mcp_manager.connect_all()

        asyncio.get_event_loop().create_task(init_mcp())

    # ── Compose ─────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        yield self.token_panel
        yield self.message_list
        from textual.widgets import Static
        
        with Container(id="input-dock"):
            with Container(classes="input-container"):
                yield Static("❯", classes="input-prompt")
                yield InputArea(
                    id="input",
                    classes="input-field",
                )
                yield Static("", id="history-hint", classes="history-hint")
                yield Static("", id="token-hint", classes="token-hint")

    # ── Actions ─────────────────────────────────────────────────────────────

    def action_toggle_panel(self) -> None:
        self.panel_visible = not self.panel_visible
        self.token_panel.set_class(self.panel_visible, "panel-open")

    def action_toggle_token_hint(self) -> None:
        """Show or hide the token hint near the input area (Ctrl+H)."""
        self._token_hint_visible = not self._token_hint_visible
        self._render_token_hint()

    def action_toggle_expand(self) -> None:
        """Expand/collapse the token panel detail view (Ctrl+O)."""
        self.token_panel.toggle_expand()

    def action_clear(self) -> None:
        self.message_list.clear()
        self._streaming_msg_id = None
        self._assistant_content = ""
        self._usage_input = 0
        self._usage_output = 0
        self._usage_cache = 0
        self._app_state["messages"] = []
        self._app_state["_total_input_tokens"] = 0
        self._app_state["_total_output_tokens"] = 0
        self._app_state["_total_cache_hits"] = 0
        self.session_manager.clear()
        self._display_input_tokens = 0
        self._display_output_tokens = 0
        self._display_cache_tokens = 0
        self._stop_token_animation()
        self._render_token_hint()
        self._render_history_hint()
        self.notify("Cleared")

    def action_new_conv(self) -> None:
        self.message_list.clear()
        self._app_state = get_initial_state(self.session_id)
        self._app_state["_mode"] = self._mode
        self.session_manager.new_conversation()
        self._streaming = False
        self._streaming_msg_id = None
        self._usage_input = 0
        self._usage_output = 0
        self._usage_cache = 0
        self._display_input_tokens = 0
        self._display_output_tokens = 0
        self._display_cache_tokens = 0
        self._stop_token_animation()
        self.token_panel.reset()
        self._render_token_hint()
        self._render_history_hint()
        self.notify("New conversation")

    def action_save(self) -> None:
        self.session_manager.store.save_history(
            self._app_state.get("messages", []),
            self.session_manager.current_conv_id,
        )
        self.notify("Session saved")

    def action_run(self, raw: str) -> None:
        """
        Execute deepx exec from the TUI via subprocess.
        Usage: /run PROMPT [--flag VALUE]...
        """
        import re
        import subprocess
        import threading

        self.message_list.add_message("user", f"/run {raw}")

        segments = re.split(r'\s+--', raw.strip())
        prompt = segments[0].strip()
        flag_parts = []
        for seg in segments[1:]:
            tokens = seg.strip().split(maxsplit=1)
            flag_parts.append(f"--{tokens[0]}")
            if len(tokens) > 1:
                flag_parts.append(tokens[1])

        cmd = ["deepx", "exec", prompt] + [f for f in flag_parts if f]
        cmd_str = " ".join(f"'{p}'" if " " in p else p for p in cmd if p)

        self._assistant_content = f"$ {cmd_str}\n"
        self._streaming_msg_id = self.message_list.add_message_stream("assistant", self._assistant_content)
        self._streaming = True

        def run_in_thread():
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                for line in proc.stdout:
                    self.call_from_thread(self._append_to_stream, line)
                proc.wait()
                self.call_from_thread(self._on_run_done)
            except Exception as e:
                self.call_from_thread(self._append_to_stream, f"\n[Error] {e}\n")
                self.call_from_thread(self._on_run_done)

        threading.Thread(target=run_in_thread, daemon=True).start()

    def action_open_skills(self) -> None:
        """Open the skills list modal (Ctrl+K)."""
        modal = SkillsListModal()
        self.push_screen(modal)

    def action_open_skill_add(self) -> None:
        """Open the skill search/install modal (Ctrl+Shift+K)."""
        modal = SkillSearchModal()
        self.push_screen(modal)

    # ── Command interceptors ──────────────────────────────────────────────

    def on_input_submitted(self, event: InputSubmitted) -> None:
        user_input = event.value.strip()
        if not user_input or self._streaming:
            return

        input_widget = self.query_one("#input", InputArea)

        if user_input.startswith("/run "):
            input_widget.text = ""
            prompt = user_input[5:].strip()
            if prompt:
                self.action_run(prompt)
            return
        if user_input == "/skills":
            input_widget.text = ""
            self.action_open_skills()
            return
        if user_input == "/skill-add":
            input_widget.text = ""
            self.action_open_skill_add()
            return
        if user_input in ("/exit", "/quit"):
            self.exit()
            return

        input_widget.text = ""
        if self._streaming:
            return

        self.session_manager.add_input_history(user_input)
        self._render_history_hint()
        self.message_list.add_message("user", user_input)
        asyncio.get_event_loop().create_task(self._run_agent(user_input))

    def on_navigate_history(self, event: NavigateHistory) -> None:
        """Navigate prompt history from the textarea with up/down keys."""
        input_widget = self.query_one("#input", InputArea)
        if event.direction == "up":
            value = self.session_manager.get_previous_input()
            if value is None:
                return
        else:
            value = self.session_manager.get_next_input()
        input_widget.text = value
        input_widget.move_cursor((len(value.splitlines()) - 1, len(value.splitlines()[-1]) if value else 0))
        self._render_history_hint()

    # ── Agent worker (async streaming via LangGraph) ─────────────────────

    async def _run_agent(self, user_input: str) -> None:
        """Run the agent and ensure assistant replies are rendered exactly once."""
        self._streaming = True
        self._assistant_content = ""
        self._streaming_msg_id = None
        self._usage_input = 0
        self._usage_output = 0
        self._usage_cache = 0
        self._display_input_tokens = 0
        self._display_output_tokens = 0
        self._display_cache_tokens = 0
        self._stop_token_animation()
        self._render_token_hint()
        final_assistant_content = ""

        self._app_state["messages"].append({"role": "user", "content": user_input})
        self._app_state["_mode"] = self._mode
        config = {"configurable": {"thread_id": self.session_id}}

        try:
            async for mode, chunk in self._workflow.astream(
                input=self._app_state,
                config=config,
                stream_mode=["values", "custom"],
            ):
                if mode == "custom":
                    self._process_custom_event(chunk)
                elif mode == "values":
                    input_t = chunk.get("_total_input_tokens", 0)
                    if input_t and input_t != self._usage_input:
                        self._usage_input = input_t
                        self._usage_output = chunk.get("_total_output_tokens", 0)
                        self._usage_cache = chunk.get("_total_cache_hits", 0)
                        self._update_token_panel_async()
                    self._app_state = chunk

                    messages = chunk.get("messages", [])
                    for m in reversed(messages):
                        role = m.get("role", "") if isinstance(m, dict) else getattr(m, "type", "")
                        role = {"ai": "assistant", "human": "user"}.get(role, role)
                        if role == "assistant":
                            content = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
                            if content:
                                final_assistant_content = str(content)
                            break

        except Exception as e:
            import traceback
            error_msg = f"\n[Error: {e}]"
            if self._streaming_msg_id:
                self._append_to_stream(error_msg)
            else:
                self.message_list.add_message("assistant", error_msg)
            traceback.print_exc()
        finally:
            if final_assistant_content:
                if self._streaming_msg_id:
                    self.message_list.update_stream(self._streaming_msg_id, final_assistant_content)
                else:
                    self.message_list.add_message("assistant", final_assistant_content)
                self._assistant_content = final_assistant_content
            elif self._streaming_msg_id is None and not self._assistant_content:
                self.message_list.add_message("assistant", "[No response returned]")
            self.session_manager.add_message({"role": "user", "content": user_input})
            if self._assistant_content:
                self.session_manager.add_message({"role": "assistant", "content": self._assistant_content})
            self._streaming = False
            self._streaming_msg_id = None
            self._sync_display_tokens(force=True)

    def _emit_token_update(self) -> None:
        """Refresh the streaming assistant message with accumulated content."""
        self._refresh_stream()

    def _process_custom_event(self, event: dict) -> None:
        """Process a custom event emitted via writer()."""
        etype = event.get("type", "")
        if etype != "custom":
            return
        data = event.get("data", {})
        ct = data.get("type", "")

        if ct == "token":
            content = data.get("content", "")
            if content:
                self._assistant_content += content
                self._emit_token_update()
            return

        if ct == "tool_call":
            fname = data.get("tool_name", "?")
            args = str(data.get("tool_args", ""))[:80]
            self._assistant_content += f"\n[Calling: {fname}({args})]\n"
            self._refresh_stream()

        elif ct == "tool_result":
            fname = data.get("tool_name", "?")
            result = data.get("result", "")
            tool_id = data.get("tool_id", "")

            # Sub-agent task result (tool_id is the task_id)
            if fname == "subagent":
                self.token_panel.update_task_status(
                    task_id=tool_id,
                    status="done" if not result.startswith("[Error") else "error",
                    result=result,
                )
                self._assistant_content += f"\n[{tool_id}] {result[:150]}\n"
            else:
                self._assistant_content += f"\n[Result: {fname}] {result[:200]}\n"
            self._refresh_stream()

        elif ct == "routing":
            model = data.get("model", "?")
            reason = data.get("reason", "")
            self._assistant_content += f"\n[Model: {model} — {reason}]\n"
            self._refresh_stream()

        elif ct == "usage":
            self._usage_input = data.get("input", 0)
            self._usage_output = data.get("output", 0)
            self._usage_cache = data.get("cache", 0)
            self._start_token_animation()
            self._update_token_panel_async()

        elif ct == "error":
            self._assistant_content += f"\n[Error: {data.get('message', '')}]\n"
            self._refresh_stream()

        elif ct == "state":
            status = data.get("status", "")
            if status == "planning":
                self._assistant_content += "\n[Planning: analyzing task...]\n"
            elif status == "parallel_start":
                tasks = data.get("tasks", [])
                self.token_panel.update_parallel(
                    active=True,
                    tasks=[{"id": t.get("id", f"task-{i}"), "desc": t.get("desc", "")[:40], "status": "running"}
                          for i, t in enumerate(tasks)],
                )
                self._assistant_content += f"\n[Parallel: {len(tasks)} tasks starting...]\n"
            else:
                self._assistant_content += f"\n[Status: {status}]\n"
            self._refresh_stream()

        elif ct == "compress":
            self._assistant_content += "\n[Compressing context...]\n"
            self._refresh_stream()

    def _update_token_panel_async(self) -> None:
        """Update token panel and the input-corner token hint from the main thread."""
        model_cfg = self.settings.model_for("flash")
        display_input = self._display_input_tokens
        display_output = self._display_output_tokens
        display_cache = self._display_cache_tokens
        cache_pct = display_cache / display_input * 100 if display_input else 0
        cost = (
            self._usage_input * (model_cfg.input_price or 0) / 1_000_000
            + self._usage_output * (model_cfg.output_price or 0) / 1_000_000
        )
        round_num = self._app_state.get("round", 0)
        msg_count = len(self._app_state.get("messages", []))
        self.call_after_refresh(
            lambda i=display_input, o=display_output,
                   c=display_cache, p=cache_pct, cost=cost:
            self._update_token_panel("flash", model_cfg.model,
                                     i, o, c, p, cost, round=round_num, msg_count=msg_count)
        )
        self.call_after_refresh(self._render_token_hint)

    def _refresh_stream(self) -> None:
        """Refresh the streaming message display with current accumulated content."""
        if self._streaming_msg_id:
            self.message_list.update_stream(self._streaming_msg_id, self._assistant_content)
        else:
            self._streaming_msg_id = self.message_list.add_message_stream(
                "assistant", self._assistant_content
            )

    def _append_to_stream(self, delta: str) -> None:
        """Append delta text to the streaming message and refresh display."""
        self._assistant_content += delta
        self._refresh_stream()

    def _on_run_done(self) -> None:
        """Called when /run subprocess completes."""
        self._streaming = False
        self._streaming_msg_id = None

    def _update_token_panel(
        self,
        endpoint: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_hit: int,
        cache_pct: float,
        total_cost: float,
        round: int = 0,
        msg_count: int = 0,
    ) -> None:
        self.token_panel.update(
            endpoint=endpoint,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_hit=cache_hit,
            cache_pct=cache_pct,
            total_cost=total_cost,
            round=round,
            msg_count=msg_count,
        )

    def _render_token_hint(self) -> None:
        """Render the compact token summary in the input area's right corner."""
        hint = self.query_one("#token-hint")
        if not self._token_hint_visible:
            hint.remove_class("visible")
            hint.update("")
            return

        total = self._display_input_tokens + self._display_output_tokens
        parts = [
            f"↑ {self._display_input_tokens:,}",
            f"↓ {self._display_output_tokens:,}",
            f"Σ {total:,}",
        ]
        if self._display_cache_tokens:
            parts.append(f"⚡ {self._display_cache_tokens:,}")
        hint.update("   ".join(parts))
        hint.add_class("visible")

    def _render_history_hint(self) -> None:
        """Render prompt-history count and current navigation position."""
        hint = self.query_one("#history-hint")
        total = self.session_manager.input_history_count()
        if total <= 0:
            hint.update("")
            hint.remove_class("visible")
            return
        position = self.session_manager.input_history_position()
        if position is None:
            hint.update(f"Hist {total}")
        else:
            hint.update(f"Hist {position}/{total}")
        hint.add_class("visible")

    def _stop_token_animation(self) -> None:
        """Stop any running token animation task."""
        if self._token_anim_task and not self._token_anim_task.done():
            self._token_anim_task.cancel()
        self._token_anim_task = None

    def _start_token_animation(self) -> None:
        """Animate displayed token counters toward the latest actual usage values."""
        if self._token_anim_task and not self._token_anim_task.done():
            return
        self._token_anim_task = asyncio.get_event_loop().create_task(self._animate_token_counts())

    async def _animate_token_counts(self) -> None:
        """Smoothly increment visible token counters for a rolling-number effect."""
        try:
            while self._sync_display_tokens():
                self._update_token_panel_async()
                await asyncio.sleep(0.03)
        except asyncio.CancelledError:
            pass
        finally:
            self._token_anim_task = None
            self._sync_display_tokens(force=True)
            self._update_token_panel_async()

    def _sync_display_tokens(self, force: bool = False) -> bool:
        """Move displayed token counters toward actual counters."""
        changed = False
        changed |= self._step_display_token("_display_input_tokens", self._usage_input, force)
        changed |= self._step_display_token("_display_output_tokens", self._usage_output, force)
        changed |= self._step_display_token("_display_cache_tokens", self._usage_cache, force)
        return changed

    def _step_display_token(self, field_name: str, target: int, force: bool) -> bool:
        """Advance one displayed counter by a dynamic step toward its target."""
        current = getattr(self, field_name)
        if current == target:
            return False
        if force:
            setattr(self, field_name, target)
            return True
        delta = target - current
        step = max(1, abs(delta) // 6)
        if delta > 0:
            current = min(target, current + step)
        else:
            current = max(target, current - step)
        setattr(self, field_name, current)
        return True

    # ── Skill modal event handlers ────────────────────────────────────────

    def on_skill_install_success(self, event: SkillInstallSuccess) -> None:
        self.notify(f"✓ 已安装 skill「{event.skill_name}」", severity="information")

    def on_skill_install_error(self, event: SkillInstallError) -> None:
        self.notify(f"✗ 安装失败: {event.error}", severity="error")

    def on_skill_deleted(self, event: SkillDeleted) -> None:
        self.notify(f"✓ 已删除 skill「{event.skill_name}」", severity="information")

    def on_skill_delete_error(self, event: SkillDeleteError) -> None:
        self.notify(f"✗ 删除失败: {event.error}", severity="error")