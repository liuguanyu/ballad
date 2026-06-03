"""Input area widget — bottom input with history and autocomplete."""
from __future__ import annotations

from textual.widgets import Input


class InputArea(Input):
    """
    Enhanced input widget for the bottom of the TUI.

    Features:
    - Command history (up/down arrows)
    - Multiline input (Shift+Enter)
    - Send on Enter
    """

    CSS = """
    InputArea {
        height: 3;
        border: solid $primary;
    }
    InputArea:focus {
        border: solid $accent;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._history: list[str] = []
        self._history_idx = -1