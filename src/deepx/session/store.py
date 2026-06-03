"""Session storage — file-based persistence for DeepX sessions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import orjson

from deepx.config.settings import get_settings


class SessionStore:
    """
    File-based session storage.

    Layout:
        ~/.deepx/sessions/{workspace_hash}/
        ├── meta.json           # Session metadata
        ├── current             # Pointer to current conversation id
        ├── state.json          # Current state snapshot
        ├── history.gob         # Full message history (binary) — Python: pickle
        ├── YYYY-MM-DD.jsonl    # Text logs (for Memory search)
        └── conversations/
            └── {id}/
                ├── meta.json
                └── state.json
    """

    def __init__(self, workspace: Path | str):
        settings = get_settings()
        self.base_dir = settings.session_dir
        self.workspace = workspace if isinstance(workspace, Path) else Path(workspace)
        self.session_id = self._workspace_hash()
        self.session_dir = self.base_dir / self.session_id
        self.conversations_dir = self.session_dir / "conversations"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.conversations_dir.mkdir(parents=True, exist_ok=True)

    def _workspace_hash(self) -> str:
        s = hashlib.sha1(str(self.workspace.resolve()).encode()).hexdigest()
        return s[:16]

    def _conversation_dir(self, cid: str | None = None) -> Path:
        if cid is None:
            cid = self._read_current_conversation_id()
        if cid is None:
            cid = "default"
        return self.conversations_dir / cid

    def _read_current_conversation_id(self) -> str | None:
        current_file = self.session_dir / "current"
        if not current_file.exists():
            return None
        return current_file.read_text().strip() or None

    # ── Read / Write raw files ──────────────────────────────────────────────

    def read_raw(self, name: str, conv_id: str | None = None) -> str | None:
        path = self._conversation_dir(conv_id) / name
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def write_raw(self, name: str, content: str, conv_id: str | None = None) -> None:
        d = self._conversation_dir(conv_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(content, encoding="utf-8")

    # ── JSON helpers ────────────────────────────────────────────────────────

    def read_json(self, name: str, conv_id: str | None = None) -> dict | None:
        raw = self.read_raw(name, conv_id)
        if raw is None:
            return None
        return orjson.loads(raw)

    def write_json(self, name: str, data: dict, conv_id: str | None = None) -> None:
        self.write_raw(name, orjson.dumps(data).decode("utf-8"), conv_id)

    # ── Message history ────────────────────────────────────────────────────

    def load_history(self, conv_id: str | None = None) -> list[dict]:
        """Load full message history from pickle-equivalent JSON."""
        history = self.read_json("history.json", conv_id)
        return history if history else []

    def save_history(self, history: list[dict], conv_id: str | None = None) -> None:
        self.write_json("history.json", history, conv_id)

    def append_to_log(self, entry: dict, conv_id: str | None = None) -> None:
        """Append a structured entry to the daily JSONL log (for Memory search)."""
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        log_file = self._conversation_dir(conv_id) / f"{today}.jsonl"
        line = orjson.dumps(entry).decode("utf-8")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    # ── Conversation management ─────────────────────────────────────────────

    def create_conversation(self) -> str:
        """Create a new conversation and return its id."""
        import uuid

        cid = uuid.uuid4().hex[:8]
        d = self.conversations_dir / cid
        d.mkdir(parents=True, exist_ok=True)
        self.write_json("meta.json", {"id": cid, "created": str(Path(__file__))})
        self._set_current_conversation(cid)
        return cid

    def _set_current_conversation(self, cid: str) -> None:
        (self.session_dir / "current").write_text(cid)

    def list_conversations(self) -> list[dict]:
        """List all conversations in this session."""
        result = []
        for d in sorted(self.conversations_dir.iterdir()):
            if not d.is_dir():
                continue
            meta = self.read_json("meta.json", conv_id=d.name)
            if meta:
                result.append(meta)
        return result