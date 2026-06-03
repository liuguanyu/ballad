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
from deepx.graph import build_workflow, get_initial_state
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

        # Session store + manager (persistence)
        self.session_store = SessionStore(workspace=str(self.workspace))
        self.session_manager = SessionManager(workspace=str(self.workspace))

        # LangGraph workflow (streaming via astream + astream_events)
        self._workflow = build_workflow(self.session_id)
        self._app_state = get_initial_state(self.session_id)
        self._app_state["_mode"] = self._mode

        # Load existing history into workflow state
        history = self.session_manager.history
        if history:
            self._app_state["messages"] = history

        # Agent runner (for /run subprocess executor)
        self.runner = AgentRunner(workspace=str(self.workspace), session_store=self.session_store)

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
        from deepx.logging_config import setup_logging
        from deepx.tools.base import register_tools

        setup_logging()
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
        self._app_state["messages"] = []
        self._app_state["_total_input_tokens"] = 0
        self._app_state["_total_output_tokens"] = 0
        self._app_state["_total_cache_hits"] = 0
        self.session_manager.clear()
        self.notify("Cleared")

    def action_new_conv(self) -> None:
        self.message_list.clear()
        self._app_state = get_initial_state(self.session_id)
        self._app_state["_mode"] = self._mode
        self.session_manager.new_conversation()
        self._streaming = False
        self._streaming_msg_id = None
        self.token_panel.reset()
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

    # ── Agent worker (async streaming via LangGraph) ─────────────────────

    async def _run_agent(self, user_input: str) -> None:
        """
        Run the agent via LangGraph dual-stream.

        Two streams merged into one event handler:
          - astream(stream_mode=values) → state snapshots → LLM tokens
          - astream(stream_mode=custom) → custom events → tool calls, routing, usage

        astream_events() is NOT used — it doesn't emit on_chain_stream
        for custom LLM clients. State snapshots from 'values' mode
        include the complete LLM response in messages.
        """
        self._streaming = True
        self._assistant_content = ""
        self._streaming_msg_id = None
        self._usage_input = 0
        self._usage_output = 0
        self._usage_cache = 0

        self._app_state["messages"].append({"role": "user", "content": user_input})
        self._app_state["_mode"] = self._mode
        config = {"configurable": {"thread_id": self.session_id}}

        # Track seen message indices to detect new ones (for LLM response display)
        seen_msg_count = len(self._app_state.get("messages", [])) - 1  # exclude user msg
        # Also track LangChain messages (AIMessage, HumanMessage, ToolMessage)
        seen_lc_count = 0

        custom_queue: asyncio.Queue = asyncio.Queue()
        pump_done = False

        async def pump_custom():
            """Drain astream(stream_mode=custom) → custom events."""
            nonlocal pump_done
            try:
                async for chunk in self._workflow.astream(
                    input=self._app_state,
                    config=config,
                    stream_mode="custom",
                ):
                    await custom_queue.put(chunk)
            finally:
                pump_done = True
                await custom_queue.put(None)

        try:
            pump_task = asyncio.create_task(pump_custom())

            # Primary: stream state snapshots (values) → LLM tokens
            async for state_snapshot in self._workflow.astream(
                input=self._app_state,
                config=config,
                stream_mode="values",
            ):
                messages = state_snapshot.get("messages", [])

                # Detect new messages by index; display only 'assistant' role
                while seen_msg_count < len(messages):
                    msg = messages[seen_msg_count]
                    role = msg.get("role", "") if isinstance(msg, dict) else getattr(msg, "type", "")
                    # LangChain: "ai" → assistant, "human" → user
                    if role == "ai":
                        role = "assistant"
                    elif role == "human":
                        role = "user"
                    content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")

                    # Display assistant responses (LLM tokens)
                    if role == "assistant" and content:
                        self._assistant_content += content
                        self._emit_token(content)

                    seen_msg_count += 1

                # Usage from state
                input_t = state_snapshot.get("_total_input_tokens", 0)
                if input_t and input_t != self._usage_input:
                    self._usage_input = input_t
                    self._usage_output = state_snapshot.get("_total_output_tokens", 0)
                    self._usage_cache = state_snapshot.get("_total_cache_hits", 0)
                    self._update_token_panel_async()

                # Drain custom events
                while not custom_queue.empty() or not pump_done:
                    if custom_queue.empty():
                        try:
                            await asyncio.wait_for(custom_queue.get(), timeout=0.001)
                        except asyncio.TimeoutError:
                            break
                    ev = await custom_queue.get()
                    if ev is None:
                        break
                    self._process_custom_event(ev)

                # Check if done
                next_node = state_snapshot.get("next_node")
                if next_node == "end":
                    # Update app_state with final snapshot
                    self._app_state = state_snapshot
                    # Drain remaining custom
                    while not custom_queue.empty():
                        ev = await custom_queue.get()
                        if ev:
                            self._process_custom_event(ev)
                    self._streaming = False
                    self._streaming_msg_id = None
                    break

        except Exception as e:
            import traceback
            error_msg = f"\n[Error: {e}]"
            if self._streaming_msg_id:
                self._append_to_stream(error_msg)
            else:
                self.message_list.add_message("assistant", error_msg)
            traceback.print_exc()
            self._streaming = False
            self._streaming_msg_id = None

    def _emit_token(self, content: str) -> None:
        """Append a token to the streaming message view."""
        if not content:
            return
        if self._streaming_msg_id is None:
            self._streaming_msg_id = self.message_list.add_message_stream(
                "assistant", self._assistant_content
            )
        else:
            self.message_list.update_stream(self._streaming_msg_id, self._assistant_content)

    def _process_custom_event(self, event: dict) -> None:
        """Process a custom event emitted via writer()."""
        etype = event.get("type", "")
        if etype != "custom":
            return
        data = event.get("data", {})
        ct = data.get("type", "")

        if ct == "tool_call":
            fname = data.get("tool_name", "?")
            args = str(data.get("tool_args", ""))[:80]
            self._assistant_content += f"\n[Calling: {fname}({args})]\n"
            self._append_to_stream(self._assistant_content)

        elif ct == "tool_result":
            fname = data.get("tool_name", "?")
            result = data.get("result", "")
            self._assistant_content += f"\n[Result: {fname}] {result[:200]}\n"
            self._append_to_stream(self._assistant_content)

        elif ct == "routing":
            model = data.get("model", "?")
            reason = data.get("reason", "")
            self._assistant_content += f"\n[Model: {model} — {reason}]\n"
            self._append_to_stream(self._assistant_content)

        elif ct == "usage":
            self._usage_input = data.get("input", 0)
            self._usage_output = data.get("output", 0)
            self._usage_cache = data.get("cache", 0)
            self._update_token_panel_async()

        elif ct == "error":
            self._assistant_content += f"\n[Error: {data.get('message', '')}]\n"
            self._append_to_stream(self._assistant_content)

        elif ct == "state":
            status = data.get("status", "")
            self._assistant_content += f"\n[Status: {status}]\n"
            self._append_to_stream(self._assistant_content)

        elif ct == "compress":
            self._assistant_content += "\n[Compressing context...]\n"
            self._append_to_stream(self._assistant_content)

    def _update_token_panel_async(self) -> None:
        """Update token panel from the main thread."""
        if not (self._usage_input or self._usage_output):
            return
        model_cfg = self.settings.model_for("flash")
        cache_pct = self._usage_cache / self._usage_input * 100 if self._usage_input else 0
        cost = (
            self._usage_input * (model_cfg.input_price or 0) / 1_000_000
            + self._usage_output * (model_cfg.output_price or 0) / 1_000_000
        )
        self.call_after_refresh(
            lambda i=self._usage_input, o=self._usage_output,
                   c=self._usage_cache, p=cache_pct, cost=cost:
            self._update_token_panel("flash", model_cfg.model, i, o, c, p, cost)
        )

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