"""
TokenPanel — right-side status panel with expand/collapse.

Toggle modes:
  Ctrl+T → show/hide panel (always collapsed width)
  Ctrl+O → expand/collapse detail view within panel

Compact view (collapsed): model + token summary
Expanded view (Ctrl+O): full status including model, mode, round,
  message count, context usage, parallel tasks, cache, cost
"""
from __future__ import annotations

from typing import Any

from textual.message import Message
from textual.widgets import Static


class PanelExpandRequest(Message):
    """Request to expand the token panel."""


class TokenPanel(Static):
    """
    Right-side status panel. Toggle with Ctrl+T, expand with Ctrl+O.

    Two views:
      compact: model + token summary (default)
      expanded: full status with parallel tasks
    """

    CSS = """
    TokenPanel {
        dock: right;
        width: 0;
        display: none;
        background: #0d1117;
        border-left: solid #58a6ff;
        padding: 1 2;
        overflow: hidden;
    }

    TokenPanel.panel-open {
        display: block;
        width: 32;
    }
    """

    def __init__(self):
        super().__init__(id="token-panel")
        self._reset()

    def _reset(self) -> None:
        self._expanded = False
        self.stats: dict[str, Any] = {
            "endpoint": "flash",
            "model": "—",
            "mode": "review",
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_hit": 0,
            "cache_pct": 0.0,
            "total_cost": 0.0,
            "round": 0,
            "msg_count": 0,
            "context_used": 0,
            "context_limit": 200_000,
            # Parallel tasks
            "parallel_active": False,
            "parallel_tasks": [],      # [{id, desc, status, tool}]
            "parallel_done": 0,
            "parallel_errors": 0,
        }

    def reset(self) -> None:
        self._reset()
        Static.update(self, "")
        if self.has_class("panel-open"):
            self.remove_class("panel-open")

    # ── Toggle ────────────────────────────────────────────────────────────

    def toggle_expand(self) -> None:
        """Expand or collapse the panel detail view (Ctrl+O)."""
        self._expanded = not self._expanded
        self._render()

    # ── Update ─────────────────────────────────────────────────────────────

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
        msg_count: int = 0,
        context_used: int = 0,
        context_limit: int = 200_000,
    ) -> None:
        self.stats.update(
            endpoint=endpoint,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_hit=cache_hit,
            cache_pct=cache_pct,
            total_cost=total_cost,
            round=round,
            msg_count=msg_count,
            context_used=context_used,
            context_limit=context_limit,
        )
        self._render()

    def update_parallel(
        self,
        active: bool = False,
        tasks: list[dict] | None = None,
        done: int = 0,
        errors: int = 0,
    ) -> None:
        if tasks is not None:
            self.stats["parallel_tasks"] = tasks
        self.stats["parallel_active"] = active
        self.stats["parallel_done"] = done
        self.stats["parallel_errors"] = errors
        self._render()

    def update_task_status(
        self,
        task_id: str,
        status: str,  # "running" | "done" | "error"
        result: str = "",
    ) -> None:
        for task in self.stats["parallel_tasks"]:
            if task.get("id") == task_id:
                task["status"] = status
                task["result"] = result[:80]
                break
        # Update counts
        tasks = self.stats["parallel_tasks"]
        self.stats["parallel_done"] = sum(1 for t in tasks if t.get("status") == "done")
        self.stats["parallel_errors"] = sum(1 for t in tasks if t.get("status") == "error")
        self._render()

    # ── Render ─────────────────────────────────────────────────────────────

    def _render(self) -> None:
        s = self.stats

        if not self._expanded:
            # Compact: just model + tokens summary
            cp = s["cache_pct"]
            cp_cls = "good" if cp > 80 else "warn" if cp > 50 else "bad"
            cost_str = f"${s['total_cost']:.4f}" if s["total_cost"] else "—"
            content = (
                f"[bold]$ DeepX[/bold]\n\n"
                f"[section-label]Model[/][section-value] {s['model']}\n"
                f"[section-label]In[/]   [section-value]{s['input_tokens']:,}\n"
                f"[section-label]Out[/]  [section-value]{s['output_tokens']:,}\n"
                f"[section-label]Cache[/] [{cp_cls}]{cp:.1f}%[/]\n"
                f"[section-label]Cost[/]  [section-value]{cost_str}\n"
            )
        else:
            # Expanded: full status
            cp = s["cache_pct"]
            cp_cls = "good" if cp > 80 else "warn" if cp > 50 else "bad"
            cost_str = f"${s['total_cost']:.4f}" if s["total_cost"] else "—"

            context_pct = (
                s["context_used"] / s["context_limit"] * 100
                if s["context_limit"] else 0
            )
            ctx_cls = "good" if context_pct < 60 else "warn" if context_pct < 85 else "bad"

            content_lines = [
                "[bold]$ DeepX Status[/bold]",
                "[divider]────────────────────────────────────[/divider]",
                f"[section-label]Model[/]    [section-value]{s['model']}",
                f"[section-label]Mode[/]     [section-value]{s['mode']}",
                f"[section-label]Round[/]    [section-value]{s['round']}",
                f"[section-label]Messages[/] [section-value]{s['msg_count']}",
                f"[section-label]Context[/]  [{ctx_cls}]{context_pct:.0f}%[/] ({s['context_used']:,}/{s['context_limit']:,})",
                "",
                f"[section-label]In/Out[/]  [section-value]{s['input_tokens']:,} / {s['output_tokens']:,}",
                f"[section-label]Cache[/]   [{cp_cls}]{cp:.1f}%[/]",
                f"[section-label]Cost[/]    [section-value]{cost_str}",
            ]

            # Parallel tasks section
            if s["parallel_active"] or s["parallel_tasks"]:
                tasks = s["parallel_tasks"]
                if tasks:
                    total = len(tasks)
                    done = s["parallel_done"]
                    err = s["parallel_errors"]
                    status_icon = "✅" if err == 0 and done == total else "⚠️" if err > 0 else "⏳"
                    content_lines.append("")
                    content_lines.append(f"[bold]⏳ Parallel ({status_icon} {done}/{total})[/bold]")
                    for task in tasks:
                        tid = task.get("id", "?")
                        desc = task.get("desc", task.get("description", ""))[:35]
                        status = task.get("status", "pending")
                        icon = {"running": "→", "done": "✓", "error": "✗", "pending": "○"}.get(status, "?")
                        cls = {
                            "running": "task-running",
                            "done": "task-done",
                            "error": "task-error",
                        }.get(status, "task-running")
                        result = task.get("result", "")
                        result_str = f" → {result[:25]}" if result else ""
                        content_lines.append(f"  [{cls}]{icon}[/] [{tid}] {desc}{result_str}")
                else:
                    content_lines.append(f"\n[dim]⏳ Parallel: initializing...[/dim]")

            content = "\n".join(content_lines)

        Static.update(self, content)