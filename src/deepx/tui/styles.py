"""DeepX TUI CSS stylesheet."""

DEEPX_CSS = """
/* ── Layout ─────────────────────────────────────────────────────────────── */
Screen {
    layout: horizontal;    /* main area + token panel side by side */
}

#main-area {
    width: 1fr;
    layout: vertical;
}

/* ── Header ─────────────────────────────────────────────────────────────── */
Header {
    dock: top;
    height: auto;
}

/* ── Message List ───────────────────────────────────────────────────────── */
#messages {
    height: 1fr;
    width: 100%;
    scrollbar-gutter: stable;
}

#spacer {
    height: 1;
}

/* ── Input Area ─────────────────────────────────────────────────────────── */
#input-dock {
    dock: bottom;
    height: 3;
    background: $surface;
    border-top: solid $primary;
    padding: 0 2;
}

.input-field {
    margin: 0;
    border: solid $primary;
}

.input-field:focus {
    border: solid $accent;
}

/* ── Token Panel ─────────────────────────────────────────────────────────── */
#token-panel {
    width: 0;
    dock: right;
    background: $surface;
    border-left: solid $primary;
    padding: 1 2;
    transition: width 200ms;
}

#token-panel.panel-open {
    width: 220;
}

/* ── Message Bubbles ─────────────────────────────────────────────────────── */
.message-view {
    width: 100%;
    margin: 0 0 1 0;
    padding: 1 2;
}

.message-view.user {
    background: $surface;
}

.message-view.assistant {
    background: $surface;
    color: $text;
}

.message-view.tool {
    background: $surface;
    color: $text-muted;
    border-left: solid $primary;
}

.message-view.thinking {
    background: $surface;
    color: $text-muted;
    text-style: italic;
}

/* ── Scrollbar ──────────────────────────────────────────────────────────── */
ScrollableContainer > .scrollbar {
    color: $primary;
    opacity: 0.5;
}

/* ── Focus ──────────────────────────────────────────────────────────────── */
*:focus {
    border: solid $accent;
}

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
"""