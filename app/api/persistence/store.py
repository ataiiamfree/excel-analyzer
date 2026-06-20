"""Small SQLite repository for conversations, messages, and artifacts."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.init_db()

    def init_db(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    file_name TEXT,
                    file_size INTEGER,
                    local_file_path TEXT,
                    sheet_count INTEGER,
                    row_count INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    starred INTEGER NOT NULL DEFAULT 0,
                    archived_at TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT,
                    message_id TEXT,
                    path TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    sha256 TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id),
                    FOREIGN KEY(message_id) REFERENCES messages(id)
                )
                """
            )

    def create_conversation(
        self,
        *,
        title: str,
        file_name: str | None,
        file_size: int | None,
        local_file_path: str | None,
        sheet_count: int | None = None,
        row_count: int | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        cid = conversation_id or uuid.uuid4().hex
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO conversations
                    (id, title, file_name, file_size, local_file_path, sheet_count, row_count,
                     created_at, updated_at, starred, archived_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)
                """,
                (cid, title, file_name, file_size, local_file_path, sheet_count, row_count, now, now),
            )
        return self.get_conversation(cid)

    def list_conversations(self, include_archived: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM conversations"
        params: tuple[Any, ...] = ()
        if not include_archived:
            sql += " WHERE archived_at IS NULL"
        sql += " ORDER BY updated_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._conversation_row(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if row is None:
            raise KeyError(conversation_id)
        return self._conversation_row(row)

    def update_conversation(self, conversation_id: str, **values: Any) -> dict[str, Any]:
        allowed = {"title", "starred", "archived_at", "sheet_count", "row_count"}
        assignments = []
        params = []
        for key, value in values.items():
            if key not in allowed:
                continue
            assignments.append(f"{key} = ?")
            if key == "starred" and value is not None:
                params.append(1 if value else 0)
            else:
                params.append(value)
        assignments.append("updated_at = ?")
        params.append(utc_now_iso())
        params.append(conversation_id)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE conversations SET {', '.join(assignments)} WHERE id = ?",
                tuple(params),
            )
        return self.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM artifacts WHERE conversation_id = ?", (conversation_id,))
            self._conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            self._conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    def create_message(
        self,
        *,
        conversation_id: str,
        role: str,
        payload: dict[str, Any],
        message_id: str | None = None,
    ) -> dict[str, Any]:
        mid = message_id or uuid.uuid4().hex
        now = utc_now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO messages (id, conversation_id, role, created_at, payload) VALUES (?, ?, ?, ?, ?)",
                (mid, conversation_id, role, now, json.dumps(payload, ensure_ascii=False, default=str)),
            )
            self._conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        return self.get_message(mid)

    def update_message_payload(self, message_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE messages SET payload = ? WHERE id = ?",
                (json.dumps(payload, ensure_ascii=False, default=str), message_id),
            )
        return self.get_message(message_id)

    def get_message(self, message_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        if row is None:
            raise KeyError(message_id)
        return self._message_row(row)

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
                (conversation_id,),
            ).fetchall()
        return [self._message_row(row) for row in rows]

    def create_artifact(
        self,
        *,
        path: str,
        kind: str,
        name: str,
        size: int,
        sha256: str | None = None,
        conversation_id: str | None = None,
        message_id: str | None = None,
        artifact_id: str | None = None,
    ) -> dict[str, Any]:
        aid = artifact_id or f"art_{uuid.uuid4().hex}"
        now = utc_now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO artifacts
                    (id, conversation_id, message_id, path, kind, name, size, sha256, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (aid, conversation_id, message_id, path, kind, name, size, sha256, now),
            )
        return self.get_artifact(aid)

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return self._artifact_row(row)

    def list_artifacts(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM artifacts WHERE conversation_id = ? ORDER BY created_at ASC",
                (conversation_id,),
            ).fetchall()
        return [self._artifact_row(row) for row in rows]

    def _conversation_row(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["starred"] = bool(data.get("starred"))
        return data

    def _message_row(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["payload"] = json.loads(data["payload"])
        return data

    def _artifact_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)
