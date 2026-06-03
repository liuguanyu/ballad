"""DeepX TUI App — main Textual application."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.widgets import Header, Static
from textual.widgets import Input

from deepx.agent.runner import AgentRunner, StreamDelta
from deepx.config.settings import get_settings
from deepx.mcp.manager import Manager
from deepx.session.manager import SessionManager
from deepx.session.store import SessionStore
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
        Binding("ctrl+o", "toggle_mode", "Auto/Review", show=True),
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

        # Session manager (persistence)
        self.session_store = SessionStore(workspace=str(self.workspace))
        self.session_manager = SessionManager(workspace=str(self.workspace))

        # Agent runner (handles LLM streaming + tool execution)
        self.runner = AgentRunner(workspace=str(self.workspace), session_store=self.session_store)

        # Load existing history if any
        history = self.session_manager.history
        if history:
            self.runner.load_history(history)

        # MCP manager
        self.mcp_manager = Manager()

        # Agent state
        self._mode = "review"  # auto | review | plan
        self._streaming = False
        self._streaming_msg_id: str | None = None
        self._assistant_content: str = ""  # accumulate for storage
        self._usage_input: int = 0
        self._usage_output: int = 0
        self._usage_cache: int = 0

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.title = "DeepX"
        self.sub_title = f"Mode: {self._mode} | Workspace: {self.workspace}"

        # Register tools and start MCP in background
        self._start_background()

    def _start_background(self) -> None:
        """Register tools and connect MCP servers (non-blocking)."""
        from deepx.tools.base import register_tools

        register_tools()

        async def init_mcp():
            await self.mcp_manager.connect_all()

        asyncio.get_event_loop().create_task(init_mcp())

    # ── Compose ─────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Container(id="main-area"):
                yield Header()
                yield self.message_list
                yield Static("", id="spacer")
                with Container(id="input-dock"):
                    yield Input(
                        placeholder="Ask DeepX to help with your code...",
                        id="input",
                        classes="input-field",
                    )
            yield self.token_panel

    # ── Actions ─────────────────────────────────────────────────────────────

    def action_toggle_panel(self) -> None:
        self.panel_visible = not self.panel_visible
        self.token_panel.set_class(self.panel_visible, "panel-open")

    def action_toggle_mode(self) -> None:
        modes = ["auto", "review", "plan"]
        idx = (modes.index(self._mode) + 1) % len(modes)
        self._mode = modes[idx]
        self.sub_title = f"Mode: {self._mode} | Workspace: {self.workspace}"
        self.notify(f"Mode: {self._mode}")

    def action_clear(self) -> None:
        self.message_list.clear()
        self._streaming_msg_id = None
        self._assistant_content = ""
        self._usage_input = 0
        self._usage_output = 0
        self._usage_cache = 0
        self.runner.reset()
        self.session_manager.clear()
        self.notify("Cleared")

    def action_new_conv(self) -> None:
        self.message_list.clear()
        self.runner.reset()
        self.session_manager.new_conversation()
        self._streaming = False
        self._streaming_msg_id = None
        self.token_panel.reset()
        self.notify("New conversation")

    def action_save(self) -> None:
        # Persist current conversation history
        self.session_manager.store.save_history(
            self.runner.get_history(),
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

        self._assistant_content = ""
        self._streaming_msg_id = self.message_list.add_message_stream("assistant", f"$ {cmd_str}\n")
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
                self.call_from_thread(self._streaming_done)
            except Exception as e:
                self.call_from_thread(self._append_to_stream, f"\n[Error] {e}\n")
                self.call_from_thread(self._streaming_done)

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

    def on_input_submitted(self, event) -> None:
        user_input = event.value.strip()
        if not user_input or self._streaming:
            return

        if user_input.startswith("/run "):
            event.input.value = ""
            prompt = user_input[5:].strip()
            if prompt:
                self.action_run(prompt)
            return
        if user_input == "/skills":
            event.input.value = ""
            self.action_open_skills()
            return
        if user_input == "/skill-add":
            event.input.value = ""
            self.action_open_skill_add()
            return

        event.input.value = ""
        if self._streaming:
            return

        self.message_list.add_message("user", user_input)
        asyncio.get_event_loop().create_task(self._run_agent(user_input))

    # ── Agent worker (async streaming) ────────────────────────────────────

    async def _run_agent(self, user_input: str) -> None:
        """
        Run the agent with streaming output.
        Each StreamDelta updates the UI in real-time.
        """
        self._streaming = True
        self._assistant_content = ""
        self._streaming_msg_id = None
        self._usage_input = 0
        self._usage_output = 0
        self._usage_cache = 0

        try:
            async for delta in self.runner.call(user_input, mode=self._mode):
                # Token chunks
                if delta.content and not delta.tool_call and not delta.tool_call_done:
                    if self._streaming_msg_id is None:
                        self._streaming_msg_id = self.message_list.add_message_stream(
                            "assistant", delta.content
                        )
                    else:
                        self._assistant_content += delta.content
                        self.message_list.update_stream(
                            self._streaming_msg_id, self._assistant_content
                        )

                # Reasoning content (shown separately if needed)
                # For now, accumulated in content

                # Tool call notification
                if delta.tool_call and not delta.tool_call_done:
                    args_preview = str(delta.tool_call.arguments)[:80]
                    self._assistant_content += f"\n[Calling tool: {delta.tool_call.name}({args_preview})]\n"
                    if self._streaming_msg_id:
                        self.message_list.update_stream(
                            self._streaming_msg_id, self._assistant_content
                        )
                    else:
                        self._streaming_msg_id = self.message_list.add_message_stream(
                            "assistant", self._assistant_content
                        )

                # Tool result
                if delta.tool_call_done:
                    self._assistant_content += delta.content
                    if self._streaming_msg_id:
                        self.message_list.update_stream(
                            self._streaming_msg_id, self._assistant_content
                        )

                # Stream done (final usage info)
                if delta.done:
                    self._usage_input = delta.input_tokens
                    self._usage_output = delta.output_tokens
                    self._usage_cache = delta.cache_hit_tokens

                    if self._streaming_msg_id:
                        self.message_list.update_stream(
                            self._streaming_msg_id, self._assistant_content
                        )

                    # Update token panel
                    model_name = self.settings.model_for("flash").model_id
                    model_cfg = self.settings.model_for("flash")
                    cache_pct = (
                        self._usage_cache / self._usage_input * 100
                        if self._usage_input
                        else 0
                    )
                    cost = (
                        self._usage_input * (model_cfg.input_price or 0) / 1_000_000
                        + self._usage_output * (model_cfg.output_price or 0) / 1_000_000
                    )
                    self.call_after_refresh(
                        lambda i=self._usage_input, o=self._usage_output,
                               c=self._usage_cache, p=cache_pct, cost=cost:
                            self._update_token_panel("flash", model_cfg.model_id,
                                                      i, o, c, p, cost)
                    )

                # Error
                if delta.error:
                    self._append_to_stream(f"\n[Error: {delta.error}]\n")

        except Exception as e:
            import traceback
            error_msg = f"\n[Error: {e}]"
            if self._streaming_msg_id:
                self._append_to_stream(error_msg)
            else:
                self.message_list.add_message("assistant", error_msg)
            traceback.print_exc()

        finally:
            self._streaming = False
            self._streaming_msg_id = None

    def _handle_token(self, content: str) -> None:
        """Handle a token from the LLM stream."""
        if not content:
            return
        self._assistant_content += content
        if self._streaming_msg_id is None:
            self._streaming_msg_id = self.message_list.add_message_stream("assistant", content)
        else:
            self.message_list.update_stream(self._streaming_msg_id, self._assistant_content)

    def _append_to_stream(self, text: str) -> None:
        """Append text to the streaming message."""
        self._assistant_content += text
        if self._streaming_msg_id:
            self.message_list.update_stream(self._streaming_msg_id, self._assistant_content)

    def _streaming_done(self) -> None:
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
    ) -> None:
        self.token_panel.update(
            endpoint=endpoint,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_hit=cache_hit,
            cache_pct=cache_pct,
            total_cost=total_cost,
        )

    # ── Skill modal event handlers ────────────────────────────────────────

    def on_skill_install_success(self, event: SkillInstallSuccess) -> None:
        self.notify(f"✓ 已安装 skill「{event.skill_name}」", severity="information")

    def on_skill_install_error(self, event: SkillInstallError) -> None:
        self.notify(f"✗ 安装失败: {event.error}", severity="error")

    def on_skill_deleted(self, event: SkillDeleted) -> None:
        self.notify(f"✓ 已删除 skill「{event.skill_name}」", severity="information")

    def on_skill_delete_error(self, event: SkillDeleteError) -> None:
        self.notify(f"✗ 删除失败: {event.error}", severity="error")