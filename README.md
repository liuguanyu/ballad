# DeepX Python — Terminal AI Programming Agent

> Python reimplementation of DeepX — leveraging Python's AI ecosystem (LangGraph, Textual, PaddleOCR).

**Status**: early development — core architecture in place, wiring up remaining components.

## Architecture

```
deepx/
├── agent/          # Zero-token routing, prefix cache, context compression
├── config/         # Pydantic settings, model configs (flash/pro)
├── graph/          # LangGraph workflow (state, nodes, edges, workflow)
├── llm/            # DeepSeek API client, tiktoken usage tracking
├── session/        # Session management, file store, history
├── tools/          # Tool system (base class + built-in tools)
│   └── builtins/   # Read, Write, Bash, Grep, Glob, CodeGraph, OCR, etc.
├── codegraph/      # Two-phase code index (syntax + type analysis)
├── ocr/            # PaddleOCR engine + three-layer smart router
├── mcp/            # MCP server/client integration
└── tui/            # Textual TUI (Claude Code-style layout, token panel)
```

## Tech Stack

| Component | Technology | Reason |
|-----------|-----------|--------|
| Agent Framework | **LangGraph** | Declarative graph, multi-agent, checkpointing |
| TUI | **Textual** | Full CSS, dock layout, component model |
| LLM | **httpx** (direct DeepSeek API) | Minimal deps, full control |
| Token counting | **tiktoken** | Official, o200k_base encoder |
| OCR | **PaddleOCR** | Fast, offline, local |
| Config | **pydantic** | Type-safe, env var support |
| Code analysis | **tree-sitter** | Fast syntax-level analysis |

## Core Optimizations (from Go version, preserved)

- **Zero-token routing** — pure local string matching, no LLM call
- **Prefix cache strategy** — exact prefix reconstruction for DeepSeek cache hits (~99%)
- **Warm path compression** — restart with cached prefix (saves cost on compression calls)
- **Context compression** — keep last 5 turns + 20% budget, tiktoken-accurate counting

## Key Features

- Claude Code-style TUI with **right-side status panel** (Ctrl+T toggle)
- Token count, cache hit rate, endpoint, cost — always visible
- LangGraph-powered multi-agent with **parallel sub-task execution**
- Local OCR with **three-layer routing** (rule → quality → LLM judge)
- MCP integration via FastMCP
- Session persistence with JSONL logs for Memory search

## Installation

```bash
# Development
pip install -e ".[dev]"

# Or with pipx (isolated)
pipx install -e .

# Dependencies
pip install langgraph>=0.2.0 textual>=0.80.0 tiktoken>=0.7.0 \
    paddleocr>=2.9.0 httpx>=0.27.0 pydantic>=2.0.0
```

## Running

```bash
# TUI mode (default)
deepx

# Non-interactive exec mode (not yet implemented)
deepx exec "refactor this function"

# Web mode (not yet implemented)
deepx web
```

## Environment Variables

```bash
DEEPX_DEEPSEEK_API_KEY=sk-...
DEEPX_SESSION_DIR=~/.deepx/sessions
DEEPX_MAX_ROUNDS=100
DEEPX_CONTEXT_WINDOW=200000
```

## Development

```bash
# Run type checking
mypy src/deepx

# Run tests
pytest

# Lint
ruff check src/deepx
```

## What's Done vs. TODO

### Done
- [x] Project structure + pyproject.toml
- [x] Config (pydantic settings, flash/pro models)
- [x] LLM client (streaming, cache hit tracking)
- [x] Session manager + file store
- [x] Zero-token router (keyword + length rules, 5 languages)
- [x] Prefix cache (snapshot, warm path)
- [x] Context compressor (tiktoken counting, keep-recent strategy)
- [x] Tool base class + registry
- [x] Built-in tools: Read, Write, Bash, Grep, Glob, ListDir (full)
- [x] Tool stubs: Todo, CreatePlan, Memory, SwitchModel, WebSearch, WebFetch, OCR
- [x] CodeGraph (two-phase index, stub)
- [x] OCR router (three-layer logic, stub engine)
- [x] MCP client (stub)
- [x] LangGraph workflow (state, nodes, edges, compile)
- [x] TUI App (Textual, Horizontal layout, Input area, message list)
- [x] Token panel (Ctrl+T toggle, real-time stats, DeepX original feature)
- [x] TUI CSS (dark theme, dock layout, transitions)
- [x] CLI + Web stubs (预留)

### TODO (high priority)
- [ ] Wire LangGraph → LLM client streaming
- [ ] Wire TUI → LangGraph workflow (stream events to message list)
- [ ] PaddleOCR integration in ocr/engine.py
- [ ] LLM judgment in ocr/router.py Layer 3
- [ ] MCP connect/discover in mcp/client.py
- [ ] FileStore for LangGraph checkpoint persistence
- [ ] MCP tools → ToolRegistry registration

### TODO (medium priority)
- [ ] CodeGraph two-phase with tree-sitter
- [ ] CreatePlan sub-agent parallel execution
- [ ] Memory tool (search JSONL logs)
- [ ] WebSearch / WebFetch (Bing, html2text)
- [ ] Command history in InputArea

### TODO (low priority)
- [ ] CLI mode (deepx exec)
- [ ] Web mode (FastAPI / Gradio dashboard)
- [ ] Auto-upgrade logic (flash → pro on failure)
- [ ] DSPy prompt optimization
- [ ] RAG pipeline integration