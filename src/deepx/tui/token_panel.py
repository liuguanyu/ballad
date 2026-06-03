"""Token panel widget — right-side status display."""
from __future__ import annotations

from textual.widgets import Static


class TokenPanel(Static):
    """
    Right-side status panel showing endpoint, tokens, cache rate, and cost.

    Toggle with Ctrl+T. Displays real-time API usage information.

    DeepX original feature.
    """

    CSS = """
    TokenPanel {
        width: 0;        /* starts hidden, expands when .panel-open */
        dock: right;
        background: $surface;
        border-left: solid $primary;
        padding: 1 2;
        transition: width 200ms;
    }

    .panel-open {
        width: 220;
    }

    .panel-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    .panel-section {
        margin-bottom: 1;
    }

    .panel-label {
        color: $text-muted;
        width: 70;
    }

    .panel-value {
        color: $text;
    }

    .panel-good {
        color: #3fb950;
    }

    .panel-warn {
        color: #d29922;
    }

    .panel-bad {
        color: #f85149;
    }

    .panel-divider {
        color: $primary;
        opacity: 0.5;
    }
    """

    def __init__(self):
        super().__init__(id="token-panel")
        self._reset()

    def _reset(self):
        self.stats = {
            "endpoint": "flash",
            "model": "DeepSeek-v3",
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_hit": 0,
            "cache_pct": 0.0,
            "total_cost": 0.0,
            "round": 0,
            "context_used": 0,
            "context_limit": 1_000_000,
        }

    def reset(self) -> None:
        """Reset all stats."""
        self._reset()
        self.update_content("")

    def update(
        self,
        endpoint: str = "",
        model: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_hit: int = 0,
        cache_pct: float = 0.0,
        total_cost: float = 0.0,
        round: int = 0,
        context_used: int = 0,
        context_limit: int = 1_000_000,
    ) -> None:
        """Update stats from LLM usage events."""
        self.stats.update(
            endpoint=endpoint,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_hit=cache_hit,
            cache_pct=cache_pct,
            total_cost=total_cost,
            round=round,
            context_used=context_used,
            context_limit=context_limit,
        )
        self._render()

    def _render(self) -> None:
        """Render the panel content."""
        s = self.stats
        cp = s["cache_pct"]
        pct_color = (
            "panel-good" if cp > 80 else "panel-warn" if cp > 50 else "panel-bad"
        )
        cost_str = f"${s['total_cost']:.4f}" if s['total_cost'] else "—"

        self.update_content(
            f"""\
[bold]$ DeepX[/bold]

[.panel-section]
[.panel-label]Model[.panel-value]  {s['model']}
[.panel-label]Mode[.panel-value]   {s['endpoint']}

[dim]─── Tokens ───[/dim]
[.panel-label]Input[.panel-value]   {s['input_tokens']:,}
[.panel-label]Output[.panel-value]  {s['output_tokens']:,}
[.panel-label]Cache[.panel-value]   [{pct_color}]{s['cache_hit']:,}[/]
[.panel-label]Hit%[.panel-value]    [{pct_color}]{cp:.1f}%[/]

[dim]─── Cost ───[/dim]
[.panel-label]Total[.panel-value]   {cost_str}
"""
        )