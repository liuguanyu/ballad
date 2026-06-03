"""Message list widget for DeepX TUI."""
from __future__ import annotations

from textual.containers import ScrollableContainer
from textual.widgets import Static


class MessageView(Static):
    """A single message bubble in the chat."""

    CSS = """
    MessageView {
        width: 100%;
        margin: 0 0 1 0;
        padding: 1 2;
        border: none;
    }
    MessageView.user {
        color: $text;
    }
    MessageView.assistant {
        color: $text;
    }
    MessageView.tool {
        color: $text-muted;
        border-left: solid $primary;
    }
    MessageView.thinking {
        color: $text-muted;
        text-style: italic;
    }
    """

    def __init__(self, role: str, content: str, msg_id: str | None = None):
        super().__init__(content, id=msg_id)
        self.role = role
        self.add_class("message-view")
        self.add_class(role)
        self._content = content

    def set_content(self, content: str) -> None:
        """Set the message content."""
        self._content = content
        self.update(content)


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
        scrollbar-gutter: stable;
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
        self.call_after_refresh(self.scroll_to_end)

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