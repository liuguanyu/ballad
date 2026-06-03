"""Session manager — manages conversation state and history."""
from __future__ import annotations

from pathlib import Path

from deepx.config.settings import get_settings
from deepx.llm.client import Message
from deepx.llm.usage import UsageInfo
from deepx.session.store import SessionStore


class SessionManager:
    """
    Manages a DeepX session: history, state, usage tracking.

    Provides:
    - Load/recent/save conversation history
    - Prefix snapshot management (for cache-friendly compression)
    - Usage aggregation
    - Conversation switching
    """

    def __init__(self, workspace: Path | str):
        self.store = SessionStore(workspace)
        self.current_conv_id: str | None = None
        # In-memory state (loaded lazily)
        self._history: list[dict] | None = None
        self._total_usage = UsageInfo()
        self._mode = "review"

    # ── History ─────────────────────────────────────────────────────────────

    @property
    def history(self) -> list[dict]:
        if self._history is None:
            self._history = self.store.load_history(self.current_conv_id)
        return self._history

    def add_message(self, msg: Message | dict) -> None:
        """Add a message to history and persist."""
        if isinstance(msg, Message):
            msg = msg.model_dump()
        self.history.append(msg)
        self.store.save_history(self.history, self.current_conv_id)
        # Also append to daily log for Memory search
        self.store.append_to_log(
            {"type": "message", "role": msg.get("role", ""), "content": msg.get("content", "")[:200]},
            self.current_conv_id,
        )

    def load_recent_turns(self, n: int = 10) -> list[dict]:
        """Load the most recent n user turns (reverse date order, lazy)."""
        history = self.history
        # Count user turns from the end
        user_turns = 0
        for i in range(len(history) - 1, -1, -1):
            if history[i].get("role") == "user":
                user_turns += 1
            if user_turns >= n:
                return history[i:]
        return history

    def clear(self) -> None:
        """Clear in-memory history (doesn't delete files)."""
        self._history = []

    # ── Usage tracking ───────────────────────────────────────────────────────

    def add_usage(self, usage: UsageInfo) -> None:
        self._total_usage = self._total_usage.merge(usage)

    @property
    def total_usage(self) -> UsageInfo:
        return self._total_usage

    # ── Prefix snapshot (for cache-friendly compression) ───────────────────

    def save_prefix_snapshot(
        self,
        sig: str,
        model: str,
        system_prompt: str,
        tool_specs_json: str,
    ) -> None:
        """Save the exact prefix sent to the LLM for cache-friendly restart."""
        state = {
            "sig": sig,
            "model": model,
            "saved_at": str(Path(__file__)),
        }
        self.store.write_raw("last_prompt.txt", system_prompt, self.current_conv_id)
        self.store.write_raw("last_tools.json", tool_specs_json, self.current_conv_id)
        self.store.write_json("state.json", state, self.current_conv_id)

    def load_prefix_snapshot(
        self,
    ) -> tuple[str | None, str | None, str | None]:
        """Load the last saved prefix components. Returns (sig, system_prompt, tool_specs)."""
        state = self.store.read_json("state.json", self.current_conv_id)
        if not state:
            return None, None, None
        system_prompt = self.store.read_raw("last_prompt.txt", self.current_conv_id)
        tool_specs = self.store.read_raw("last_tools.json", self.current_conv_id)
        return state.get("sig"), system_prompt, tool_specs

    # ── Conversation management ─────────────────────────────────────────────

    def new_conversation(self) -> str:
        """Start a new conversation and return its id."""
        self.current_conv_id = self.store.create_conversation()
        self._history = []
        return self.current_conv_id

    def switch_conversation(self, cid: str) -> None:
        """Switch to a different conversation."""
        self.current_conv_id = cid
        self._history = None  # Reload lazily

    # ── Mode ───────────────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, v: str) -> None:
        valid = {"auto", "review", "plan"}
        if v not in valid:
            raise ValueError(f"Mode must be one of {valid}")
        self._mode = v