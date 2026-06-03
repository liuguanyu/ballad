"""deepx exec — CLI with file save + code execution."""
from __future__ import annotations

import asyncio
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import NamedTuple

import typer
from rich.console import Console
from rich.panel import Panel
from rich.tree import Tree
from rich.theme import Theme

from deepx.llm.client import LLMClient, Message
from deepx.config.settings import get_settings

console = Console(theme=Theme({
    "repr.str": "cyan",
    "repr.number": "bold green",
    "panel.border": "dim blue",
}))

# ── Language aliases ─────────────────────────────────────────────────────────
LANG_ALIASES = {
    "py": "python", "python3": "python", "python": "python",
    "sh": "shell", "bash": "shell", "shell": "shell", "zsh": "shell",
    "js": "javascript", "javascript": "javascript",
    "ts": "typescript", "go": "go", "rs": "rust", "rb": "ruby",
    "sql": "sql", "json": "json", "yaml": "yaml", "yml": "yaml",
}


# ── Code block extraction ─────────────────────────────────────────────────────
class CodeBlock(NamedTuple):
    lang: str
    content: str
    raw: str


def _normalize_lang(raw_lang: str) -> str:
    raw_lang = (raw_lang or "").strip().lower()
    if not raw_lang:
        return "text"
    return LANG_ALIASES.get(raw_lang, raw_lang)


def extract_code_blocks(text: str) -> list[CodeBlock]:
    """
    Extract fenced code blocks.
    Handles: ```python\\n...\\n```, ```\\n...\\n```, ```python\\n...```
    """
    results = []
    # Split on code fence starts
    fence_pat = re.compile(r"(?:^|\n)(```+)(\w*[^\n]*?\n)([\s\S]*?)(```+)",
                           re.MULTILINE)
    for m in fence_pat.finditer(text):
        open_fence, lang_line, body, close_fence = m.group(1), m.group(2), m.group(3), m.group(4)
        if len(open_fence) != len(close_fence):
            continue
        lang = lang_line.strip() if lang_line.strip() != "" else "text"
        # Extract just the word after ``` if on same line
        lang = _normalize_lang(lang.split()[0] if lang_line.strip() else "text")
        content = body.rstrip("\n")
        results.append(CodeBlock(lang=lang, content=content, raw=m.group(0)))
    return results


# ── Model resolution ──────────────────────────────────────────────────────────
def resolve_model(name: str | None) -> str:
    if name:
        return name
    s = get_settings()
    return s.current_model() or s.default_model() or "deepseek-flash"


# ── LLM call ──────────────────────────────────────────────────────────────────
async def llm_call(prompt: str, model_key: str, system: str | None = None) -> tuple[str, str]:
    client = LLMClient()
    m = get_settings().model(model_key)
    messages = []
    if system:
        messages.append(Message(role="system", content=system))
    messages.append(Message(role="user", content=prompt))
    resp = client.chat(messages, model=m, stream=False)
    chunks = [c async for c in resp]
    full = "".join(c.content for c in chunks)
    reasoning = "".join(c.reasoning for c in chunks if c.reasoning)
    return full, reasoning


# ── Execution ─────────────────────────────────────────────────────────────────
import os as _os
_VENV_PY = str(Path(__file__).parent.parent.parent / ".venv" / "bin" / "python3")

RUNNERS: dict[str, tuple[str, list[str]]] = {
    "python":    (_VENV_PY, []),
    "shell":     ("bash",   []),
    "bash":      ("bash",   []),
    "sh":        ("sh",     []),
    "javascript":("node",   []),
    "go":        ("go",     ["run"]),
}


class ExecResult(NamedTuple):
    ok: bool
    lang: str
    stdout: str
    stderr: str
    returncode: int
    duration_ms: float


def run_code(code: str, lang: str, timeout: int = 30) -> ExecResult:
    runner = RUNNERS.get(lang)
    if not runner:
        return ExecResult(False, lang, "", f"No runner for: {lang}", 1, 0.0)
    cmd_base, extra = runner
    start = time.monotonic()
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=f".{lang}", delete=False, encoding="utf-8",
        ) as f:
            f.write(code)
            tmp = f.name
        cmd = [cmd_base, *extra, tmp]
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)
        Path(tmp).unlink(missing_ok=True)
        return ExecResult(
            r.returncode == 0, lang, r.stdout, r.stderr,
            r.returncode, (time.monotonic() - start) * 1000,
        )
    except subprocess.TimeoutExpired:
        Path(tmp).unlink(missing_ok=True)
        return ExecResult(False, lang, "", "Timeout", 124, 0.0)
    except Exception as e:
        Path(tmp).unlink(missing_ok=True)
        return ExecResult(False, lang, "", str(e), 1, 0.0)


def print_exec(r: ExecResult):
    status = "[green]OK[/green]" if r.ok else "[red]FAIL[/red]"
    console.print(f"\n[bold]── Run ({r.lang}) {status} · {r.duration_ms:.0f}ms ──[/bold]")
    if r.stdout:
        console.print(Panel(r.stdout.strip(), title="stdout",
                            border_style="green" if r.ok else "default"))
    if r.stderr:
        console.print(Panel(r.stderr.strip(), title="stderr", border_style="red"))
    console.print(f"[dim]exit {r.returncode}[/dim]")


# ── Rich helpers ───────────────────────────────────────────────────────────────
def print_reasoning(text: str):
    if text:
        console.print(Panel(text[:2000], title="[bold blue]Thinking[/bold blue]",
                            border_style="dim", expand=False))


def print_tree(blocks: list[CodeBlock]):
    tree = Tree("[bold]Extracted code blocks:[/bold]")
    for i, b in enumerate(blocks):
        preview = b.content[:60].replace("\n", "↵")
        tree.add(f"[cyan]{i+1}. [{b.lang}][/cyan]  {preview!r}...")
    console.print(tree)


# ── Main CLI ──────────────────────────────────────────────────────────────────
app = typer.Typer(help="deepx CLI — AI tasks from the terminal.", no_args_is_help=True)


@app.command()
def exec(
    prompt: str = typer.Argument(..., help="Task or question."),
    model: str = typer.Option("", "--model", "-m", help="Model key."),
    system: str = typer.Option("", "--system", "-s", help="Extra system prompt."),
    no_thinking: bool = typer.Option(False, "--no-thinking", help="Disable extended thinking."),
    save_to: str = typer.Option("", "--save-to", help="Write code block to TARGET."),
    exec_code: bool = typer.Option(False, "--exec", help="Run first code block."),
    exec_lang: str = typer.Option("", "--lang", "-l", help="Force language."),
    exec_timeout: int = typer.Option(30, "--timeout", help="Timeout in seconds."),
    auto: str = typer.Option("", "--auto", help="Save+exec to TARGET."),
    list_models: bool = typer.Option(False, "--list-models", help="Show models."),
):
    settings = get_settings()

    if list_models:
        console.print("[bold]Available models:[/bold]\n")
        for key in settings.all_models():
            m = settings.model(key)
            if m:
                flag = " ← current" if key == settings.current_model() else ""
                flag += " ← default" if key == settings.default_model() else ""
                console.print(f"  [cyan]{key}[/cyan]  ({m.name}){flag}")
        raise typer.Exit()

    model_key = resolve_model(model or None)
    m = settings.model(model_key)
    if not m:
        console.print(f"[bold red]Model not found:[/bold red] {model_key}", err=True)
        raise typer.Exit(1)
    console.print(f"[dim]Model:[/dim] [cyan]{model_key}[/cyan] ({m.name})")

    try:
        full, reasoning = asyncio.run(llm_call(prompt, model_key, system or None))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}", err=True)
        raise typer.Exit(1)

    print_reasoning(reasoning)

    blocks = extract_code_blocks(full)

    if not blocks:
        console.print("\n[bold green]── Response ──[/bold green]")
        console.print(full)
        return

    print_tree(blocks)

    # Choose best block (prefer executable languages)
    block = blocks[0]
    if len(blocks) > 1:
        for b in blocks:
            if b.lang in RUNNERS:
                block = b
                break

    # --save-to / --auto
    if save_to or auto:
        target = auto or save_to
        p = Path(target).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(block.content, encoding="utf-8")
        console.print(f"[dim]Saved[/dim] [cyan]{p}[/cyan]  "
                      f"[dim]({len(block.content)} bytes)[/dim]")

    # --exec / --auto
    if exec_code or auto:
        lang = exec_lang or block.lang
        console.print(f"[dim]Run as[/dim] [cyan]{lang}[/cyan]...")
        r = run_code(block.content, lang, timeout=exec_timeout)
        print_exec(r)

    else:
        console.print("\n[bold green]── Response ──[/bold green]")
        console.print(full)


@app.command()
def shell(workspace: str = typer.Option("", "--workspace", "-w")):
    """Launch interactive TUI."""
    import deepx.main
    ws = Path(workspace) if workspace else Path.cwd()
    deepx.main.run()


if __name__ == "__main__":
    app()