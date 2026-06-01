from __future__ import annotations

import sqlite3
import threading
import uuid
from typing import Dict, List

from core.config import CHAT_DB_PATH
from core.utils import normalize_timestamp_to_china


_DB_LOCK = threading.Lock()


def _connect() -> sqlite3.Connection:
    CHAT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(CHAT_DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def init_chat_store() -> None:
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                emotion_label TEXT,
                valence REAL,
                arousal REAL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_user_time
            ON chat_messages(user_id, created_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_ai_diary_dates (
                user_id TEXT NOT NULL,
                date_key TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, date_key)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def normalize_chat_role(role: str) -> str:
    return "assistant" if role in {"assistant", "agent"} else "user"


def add_chat_message(
    user_id: str,
    role: str,
    content: str,
    *,
    created_at: str = "",
    emotion: Dict | None = None,
) -> Dict:
    text = (content or "").strip()
    if not text:
        return {}
    init_chat_store()
    emotion = emotion or {}
    message = {
        "id": uuid.uuid4().hex,
        "user_id": user_id,
        "role": normalize_chat_role(role),
        "content": text,
        "created_at": normalize_timestamp_to_china(created_at),
        "emotion_label": emotion.get("label"),
        "valence": emotion.get("valence"),
        "arousal": emotion.get("arousal"),
    }
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO chat_messages (
                id, user_id, role, content, created_at,
                emotion_label, valence, arousal
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message["id"],
                message["user_id"],
                message["role"],
                message["content"],
                message["created_at"],
                message["emotion_label"],
                message["valence"],
                message["arousal"],
            ),
        )
    return message


def list_chat_messages(user_id: str, limit: int = 20) -> List[Dict]:
    init_chat_store()
    safe_limit = max(1, min(int(limit or 20), 100))
    with _DB_LOCK, _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, user_id, role, content, created_at,
                   emotion_label, valence, arousal
            FROM chat_messages
            WHERE user_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (user_id, safe_limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def list_chat_messages_for_date(user_id: str, date_key: str, limit: int = 80) -> List[Dict]:
    init_chat_store()
    safe_limit = max(1, min(int(limit or 80), 500))
    start = f"{date_key}T00:00:00"
    end = f"{date_key}T23:59:59"
    with _DB_LOCK, _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, user_id, role, content, created_at,
                   emotion_label, valence, arousal
            FROM chat_messages
            WHERE user_id = ?
              AND substr(created_at, 1, 19) BETWEEN ? AND ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (user_id, start, end, safe_limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def list_context_messages(user_id: str, limit: int = 6) -> List[Dict]:
    return [
        {"role": item["role"], "content": item["content"]}
        for item in list_chat_messages(user_id, limit=limit)
    ]


def delete_chat_messages(user_id: str) -> int:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        cursor = connection.execute("DELETE FROM chat_messages WHERE user_id = ?", (user_id,))
        return int(cursor.rowcount or 0)


def mark_pending_ai_diary_date(user_id: str, date_key: str) -> None:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO pending_ai_diary_dates (user_id, date_key, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, date_key)
            DO UPDATE SET updated_at = excluded.updated_at
            """,
            (user_id, date_key, normalize_timestamp_to_china("")),
        )


def clear_pending_ai_diary_date(user_id: str, date_key: str) -> None:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            "DELETE FROM pending_ai_diary_dates WHERE user_id = ? AND date_key = ?",
            (user_id, date_key),
        )


def delete_pending_ai_diary_dates(user_id: str) -> int:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        cursor = connection.execute("DELETE FROM pending_ai_diary_dates WHERE user_id = ?", (user_id,))
        return int(cursor.rowcount or 0)


def list_pending_ai_diary_dates(before_date: str = "") -> List[tuple[str, str]]:
    init_chat_store()
    clause = "WHERE date_key < ?" if before_date else ""
    params = (before_date,) if before_date else ()
    with _DB_LOCK, _connect() as connection:
        rows = connection.execute(
            f"""
            SELECT user_id, date_key
            FROM pending_ai_diary_dates
            {clause}
            ORDER BY date_key ASC, updated_at ASC
            """,
            params,
        ).fetchall()
    return [(str(row["user_id"]), str(row["date_key"])) for row in rows]


def get_runtime_state(key: str, default: str = "") -> str:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        row = connection.execute(
            "SELECT value FROM runtime_state WHERE key = ?",
            (key,),
        ).fetchone()
    return str(row["value"]) if row else default


def set_runtime_state(key: str, value: str) -> None:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO runtime_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, normalize_timestamp_to_china("")),
        )
