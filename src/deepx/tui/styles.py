"""DeepX TUI CSS stylesheet."""

DEEPX_CSS = """
/* ── Colors (Dark theme) ─────────────────────────────────────────────────── */
$primary: #58a6ff;
$accent: #79c0ff;
$surface: #0d1117;
$background: #010409;
$text: #c9d1d9;
$text-muted: #8b949e;
$error: #f85149;
$warning: #d29922;
$success: #3fb950;

/* ── Layout ─────────────────────────────────────────────────────────────── */
Screen {
    background: $background;
    layout: vertical;
}

#main-area {
    width: 1fr;
    height: 1fr;
}

/* ── Header ─────────────────────────────────────────────────────────────── */
Header {
    dock: top;
    height: auto;
}

/* ── Message List ───────────────────────────────────────────────────────── */
#messages {
    width: 100%;
    height: 1fr;
    border: none;
    scrollbar-gutter: stable;
}

#spacer {
    height: 0;
    display: none;
}

/* ── Input Area ─────────────────────────────────────────────────────────── */
#input-dock {
    dock: bottom;
    height: auto;
    max-height: 5;
    background: $background;
    padding: 0;
    margin: 0;
}

.input-container {
    layout: horizontal;
    width: 100%;
    height: auto;
    max-height: 10;
    border: none;
    border-top: solid #30363d;
    border-bottom: solid #30363d;
    background: $background;
    align: left middle;
}

.input-prompt {
    width: 3;
    height: auto;
    color: $text-muted;
    background: $background;
}

.input-field {
    width: 1fr;
    height: auto;
    max-height: 10;
    margin: 0;
    border: none;
    background: $background;
}

.input-field:focus {
    border: none;
}

.history-hint {
    width: auto;
    min-width: 10;
    height: 1;
    color: $text-muted;
    background: $background;
    content-align: right middle;
    text-align: right;
    padding: 0 1;
    display: none;
}

.history-hint.visible {
    display: block;
}

.token-hint {
    width: auto;
    min-width: 24;
    height: 1;
    color: #e3b341;
    background: $background;
    content-align: right middle;
    text-align: right;
    padding: 0 1;
    margin-right: 1;
    display: none;
}

.token-hint.visible {
    display: block;
}

/* ── Token Panel ─────────────────────────────────────────────────────────── */
TokenPanel {
    width: 0;
    display: none;
    background: $surface;
    border-left: solid $primary;
    padding: 1 2;
    overflow: hidden;
}

TokenPanel.panel-open {
    display: block;
    width: 32;
}

/* ── Message Rows (Claude Code-like) ─────────────────────────────────────── */
.message-view {
    width: 100%;
    margin: 0;
    padding: 0 2;
}

.message-view.user {
    background: #2d3139;
    color: #f0f6fc;
    padding: 0 2;
    margin: 1 0;
}

.message-view.assistant {
    background: transparent;
    color: #c9d1d9;
    padding: 0 2;
    margin: 0 0 1 0;
}

.message-view.tool {
    background: transparent;
    color: #8b949e;
    border-left: solid #58a6ff;
    padding: 0 2;
    margin: 0 0 1 0;
}

.message-view.thinking {
    background: transparent;
    color: #8b949e;
    text-style: italic;
    padding: 0 2;
    margin: 0 0 1 0;
}

/* ── Scrollbar ──────────────────────────────────────────────────────────── */
ScrollableContainer > .scrollbar {
    color: $primary;
    opacity: 0.5;
}

/* ── Focus — only style input fields on focus, not containers ─────────── */
Input:focus {
    border: solid $accent;
}
"""
