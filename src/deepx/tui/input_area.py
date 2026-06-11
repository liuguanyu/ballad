"""Input area widget — native Textual TextArea with full IME support.

CJK (Chinese/Japanese/Korean) input works because the app disables Textual's
Kitty keyboard protocol (TEXTUAL_DISABLE_KITTY_KEY=1, set in main.run()).
Under Kitty mode, iTerm2 encodes IME-committed characters in a way Textual's
extended-key parser misreads as control keys, dropping the input. With Kitty
disabled, committed CJK characters arrive as plain printable Key events and
TextArea inserts them normally.

Key bindings:
  - Enter         → submit (InputSubmitted)
  - Shift+Enter   → newline
"""
from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import TextArea


class InputSubmitted(Message):
    """Emitted when the user submits the input."""

    def __init__(self, value: str) -> None:
        self.value = value
        super().__init__()


class NavigateHistory(Message):
    """Emitted when the user wants to navigate prompt history."""

    def __init__(self, direction: str) -> None:
        self.direction = direction
        super().__init__()


class InputArea(TextArea):
    """IME-friendly input widget built on the native Textual TextArea.

    Enter submits the current text; Shift+Enter inserts a newline so
    multi-line prompts are still possible.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.show_line_numbers = False
        self.cursor_blink = True

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            text = self.text
            if text.strip():
                self.text = ""
                self.post_message(InputSubmitted(text))
            return
        if event.key == "shift+enter":
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        if event.key in ("up", "down"):
            event.prevent_default()
            event.stop()
            self.post_message(NavigateHistory(event.key))
            return
        await super()._on_key(event)
