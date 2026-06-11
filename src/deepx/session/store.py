"""Session storage — SQLite-backed persistence for DeepX sessions."""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import orjson

from deepx.config.settings import get_settings


class SessionStore:
    """
    SQLite-backed session storage.

    Layout:
        ~/.deepx/sessions/{workspace_hash}/
        └── sessions.db
    """

    def __init__(self, workspace: Path | str):
        settings = get_settings()
        self.base_dir = settings.session_dir
        self.workspace = workspace if isinstance(workspace, Path) else Path(workspace)
        self.session_id = self._workspace_hash()
        self.session_dir = self.base_dir / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.session_dir / "sessions.db"
        self._init_db()

    def _workspace_hash(self) -> str:
        s = hashlib.sha1(str(self.workspace.resolve()).encode()).hexdigest()
        return s[:16]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS session_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    title TEXT,
                    meta_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    idx INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                    UNIQUE(conversation_id, idx)
                );

                CREATE TABLE IF NOT EXISTS kv_files (
                    conversation_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(conversation_id, name),
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS event_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    log_date TEXT NOT NULL,
                    entry_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
                ON messages(conversation_id, idx);

                CREATE INDEX IF NOT EXISTS idx_event_logs_conversation_date
                ON event_logs(conversation_id, log_date, id);
                """
            )

    def _utcnow(self) -> str:
        return datetime.utcnow().isoformat()

    def _serialize(self, data: Any) -> str:
        return orjson.dumps(data).decode("utf-8")

    def _deserialize(self, raw: str | None) -> Any:
        if raw is None:
            return None
        return orjson.loads(raw)

    def _read_current_conversation_id(self) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM session_meta WHERE key = 'current_conversation'"
            ).fetchone()
        return row["value"] if row else None

    def _ensure_conversation(self, cid: str) -> None:
        now = self._utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations (id, created_at, updated_at, title, meta_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (cid, now, now, None, "{}"),
            )

    def _resolved_conversation_id(self, cid: str | None = None) -> str:
        resolved = cid or self._read_current_conversation_id() or "default"
        self._ensure_conversation(resolved)
        return resolved

    def read_raw(self, name: str, conv_id: str | None = None) -> str | None:
        cid = self._resolved_conversation_id(conv_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content FROM kv_files WHERE conversation_id = ? AND name = ?",
                (cid, name),
            ).fetchone()
        return row["content"] if row else None

    def write_raw(self, name: str, content: str, conv_id: str | None = None) -> None:
        cid = self._resolved_conversation_id(conv_id)
        now = self._utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO kv_files (conversation_id, name, content, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(conversation_id, name)
                DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at
                """,
                (cid, name, content, now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, cid),
            )

    def read_json(self, name: str, conv_id: str | None = None) -> dict | None:
        raw = self.read_raw(name, conv_id)
        if raw is None:
            return None
        value = self._deserialize(raw)
        return value if isinstance(value, dict) else None

    def write_json(self, name: str, data: dict, conv_id: str | None = None) -> None:
        self.write_raw(name, self._serialize(data), conv_id)

    def load_history(self, conv_id: str | None = None) -> list[dict]:
        """Load full message history for a conversation."""
        cid = self._resolved_conversation_id(conv_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM messages
                WHERE conversation_id = ?
                ORDER BY idx ASC
                """,
                (cid,),
            ).fetchall()
        return [self._deserialize(row["payload_json"]) for row in rows]

    def save_history(self, history: list[dict], conv_id: str | None = None) -> None:
        cid = self._resolved_conversation_id(conv_id)
        now = self._utcnow()
        with self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (cid,))
            conn.executemany(
                """
                INSERT INTO messages (conversation_id, idx, role, content, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        cid,
                        idx,
                        msg.get("role", ""),
                        str(msg.get("content", "")),
                        self._serialize(msg),
                        now,
                    )
                    for idx, msg in enumerate(history)
                ],
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, cid),
            )

    def append_to_log(self, entry: dict, conv_id: str | None = None) -> None:
        """Append a structured entry to the daily log."""
        cid = self._resolved_conversation_id(conv_id)
        now = self._utcnow()
        today = datetime.now().strftime("%Y-%m-%d")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO event_logs (conversation_id, log_date, entry_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (cid, today, self._serialize(entry), now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, cid),
            )

    def create_conversation(self) -> str:
        """Create a new conversation and return its id."""
        import uuid

        cid = uuid.uuid4().hex[:8]
        now = self._utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations (id, created_at, updated_at, title, meta_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cid, now, now, None, "{}"),
            )
        self._set_current_conversation(cid)
        return cid

    def _set_current_conversation(self, cid: str) -> None:
        self._ensure_conversation(cid)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO session_meta (key, value)
                VALUES ('current_conversation', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (cid,),
            )

    def list_conversations(self) -> list[dict]:
        """List all conversations in this session."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, updated_at, title, meta_json
                FROM conversations
                ORDER BY updated_at DESC, created_at DESC
                """
            ).fetchall()
        result = []
        for row in rows:
            meta = self._deserialize(row["meta_json"]) or {}
            result.append(
                {
                    "id": row["id"],
                    "created": row["created_at"],
                    "updated": row["updated_at"],
                    "title": row["title"],
                    **meta,
                }
            )
        return result
