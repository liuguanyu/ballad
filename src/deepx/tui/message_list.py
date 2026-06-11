"""Message list widget for DeepX TUI."""
from __future__ import annotations

from textual.containers import ScrollableContainer
from textual.widgets import Static


class MessageView(Static):
    """A single message row in the chat."""

    def __init__(self, role: str, content: str, msg_id: str | None = None):
        prefix = self._prefix_for_role(role)
        super().__init__(f"{prefix}{content}", id=msg_id, markup=False)
        self.role = role
        self.add_class("message-view")
        self.add_class(role)
        self._content = content

    @staticmethod
    def _prefix_for_role(role: str) -> str:
        if role == "assistant":
            return "  "
        if role == "user":
            return "You: "
        if role == "tool":
            return "Tool: "
        if role == "thinking":
            return "Thinking: "
        return ""

    def set_content(self, content: str) -> None:
        """Set the message content."""
        self._content = content
        prefix = self._prefix_for_role(self.role)
        Static.update(self, f"{prefix}{content}")


class MessageList(ScrollableContainer):
    """
    Scrollable message list — Claude Code style.

    Messages are appended at the bottom, auto-scrolls to show new messages.
    Supports streaming via message IDs.
    """

    CSS = """
    MessageList {
        width: 100%;
        height: 1fr;
        border: none;
        scrollbar-gutter: stable;
        background: #010409;
    }
    MessageList:focus {
        border: none;
    }
    """

    def __init__(self):
        super().__init__(id="messages")
        self._msg_count = 0
        self._messages: list[MessageView] = []
        self._by_id: dict[str, MessageView] = {}

    def _scroll(self) -> None:
        """Scroll to the bottom."""
        self.call_after_refresh(self.scroll_end)

    # ── Add message ──────────────────────────────────────────────────────────

    def add_message(self, role: str, content: str) -> str:
        """
        Add a complete message and return its id.
        """
        self._msg_count += 1
        msg_id = f"msg-{self._msg_count}"
        msg = MessageView(role=role, content=content, msg_id=msg_id)
        self.mount(msg)
        self._messages.append(msg)
        self._by_id[msg_id] = msg
        self._scroll()
        return msg_id

    # ── Streaming support ────────────────────────────────────────────────────

    def add_message_stream(self, role: str, initial: str = "") -> str:
        """
        Add a streaming message placeholder and return its id.
        Use update_stream() to update content as tokens arrive.
        """
        return self.add_message(role, initial)

    def update_stream(self, msg_id: str, content: str) -> None:
        """Update the content of a streaming message."""
        msg = self._by_id.get(msg_id)
        if msg:
            msg.set_content(content)
            self._scroll()

    # ── Clear ────────────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Clear all messages."""
        for msg in self._messages:
            msg.remove()
        self._messages.clear()
        self._by_id.clear()
        self._msg_count = 0