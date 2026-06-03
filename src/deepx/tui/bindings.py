"""Keyboard bindings for DeepX TUI — centralized here for reference."""

BINDINGS = [
    # Panel / Display
    ("ctrl+t", "toggle_panel", "Toggle status panel"),
    ("ctrl+l", "clear", "Clear messages"),

    # Mode
    ("ctrl+o", "toggle_mode", "Switch auto/review/plan"),
    ("ctrl+n", "new_conv", "New conversation"),

    # Session
    ("ctrl+s", "save", "Save session"),

    # Input / Cancel
    ("ctrl+c", "cancel", "Cancel / exit"),
    ("escape", "cancel", "Cancel current input"),

    # Vim-like navigation (future)
    # ("j", "cursor_down", "Move down"),
    # ("k", "cursor_up", "Move up"),
    # ("g", "scroll_top", "Scroll to top"),
    # ("G", "scroll_bottom", "Scroll to bottom"),
]

# Mode descriptions
MODES = {
    "auto": "All operations run automatically without confirmation",
    "review": "Write and shell operations require user confirmation",
    "plan": "Read-only mode, no file writes or shell commands",
}