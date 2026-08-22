from __future__ import annotations

import sqlite3
import threading
import uuid
import json
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
        chat_columns = {row["name"] for row in connection.execute("PRAGMA table_info(chat_messages)").fetchall()}
        if "attachments_json" not in chat_columns:
            connection.execute("ALTER TABLE chat_messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT '[]'")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS emotion_records (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                text_score REAL NOT NULL,
                audio_score REAL NOT NULL,
                fusion_score REAL NOT NULL,
                audio_available INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_emotion_records_user_time
            ON emotion_records(user_id, created_at)
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_diary_v2_batches (
                batch_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                date_key TEXT NOT NULL,
                observation_ids_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                PRIMARY KEY (user_id, batch_id)
            )
            """
        )
        batch_columns = connection.execute(
            "PRAGMA table_info(ai_diary_v2_batches)"
        ).fetchall()
        batch_primary_key = [
            str(row["name"])
            for row in sorted(batch_columns, key=lambda row: int(row["pk"] or 0))
            if int(row["pk"] or 0) > 0
        ]
        if batch_primary_key != ["user_id", "batch_id"]:
            # v2 uses user-local display IDs such as diary_YYYYMMDD_001.
            # Development data is intentionally reset instead of migrated.
            connection.execute("DROP TABLE ai_diary_v2_batches")
            connection.execute(
                """
                CREATE TABLE ai_diary_v2_batches (
                    batch_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    date_key TEXT NOT NULL,
                    observation_ids_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    PRIMARY KEY (user_id, batch_id)
                )
                """
            )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ai_diary_v2_user_time
            ON ai_diary_v2_batches(user_id, created_at)
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
    attachments: List[Dict] | None = None,
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
        "attachments": attachments or [],
    }
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO chat_messages (
                id, user_id, role, content, created_at,
                emotion_label, valence, arousal, attachments_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(message["attachments"], ensure_ascii=False),
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
                   emotion_label, valence, arousal, attachments_json
            FROM chat_messages
            WHERE user_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (user_id, safe_limit),
        ).fetchall()
    items = []
    for row in reversed(rows):
        item = dict(row)
        item["attachments"] = json.loads(item.pop("attachments_json") or "[]")
        items.append(item)
    return items


def list_chat_messages_for_date(user_id: str, date_key: str, limit: int = 80) -> List[Dict]:
    init_chat_store()
    safe_limit = max(1, min(int(limit or 80), 500))
    start = f"{date_key}T00:00:00"
    end = f"{date_key}T23:59:59"
    with _DB_LOCK, _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, user_id, role, content, created_at,
                   emotion_label, valence, arousal, attachments_json
            FROM chat_messages
            WHERE user_id = ?
              AND substr(created_at, 1, 19) BETWEEN ? AND ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (user_id, start, end, safe_limit),
        ).fetchall()
    items = []
    for row in reversed(rows):
        item = dict(row)
        item["attachments"] = json.loads(item.pop("attachments_json") or "[]")
        items.append(item)
    return items


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


def add_emotion_record(user_id: str, scores: Dict, *, audio_available: bool = False, created_at: str = "") -> Dict:
    init_chat_store()
    item = {
        "id": uuid.uuid4().hex,
        "user_id": user_id,
        "text": float(scores.get("text", 0.0)),
        "audio": float(scores.get("audio", 0.0)) if audio_available else 0.0,
        "fusion": float(scores.get("fusion", 0.0)),
        "audio_available": bool(audio_available),
        "created_at": normalize_timestamp_to_china(created_at),
    }
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """INSERT INTO emotion_records
            (id,user_id,text_score,audio_score,fusion_score,audio_available,created_at)
            VALUES (?,?,?,?,?,?,?)""",
            (item["id"], user_id, item["text"], item["audio"], item["fusion"], int(audio_available), item["created_at"]),
        )
    return item


def list_emotion_records(user_id: str, start_at: str, limit: int = 1000, end_at: str = "") -> List[Dict]:
    init_chat_store()
    safe_limit = max(1, min(int(limit or 1000), 5000))
    end_clause = " AND created_at < ?" if end_at else ""
    parameters: list[object] = [user_id, start_at]
    if end_at:
        parameters.append(end_at)
    parameters.append(safe_limit)
    with _DB_LOCK, _connect() as connection:
        rows = connection.execute(
            f"""SELECT id,user_id,text_score,audio_score,fusion_score,audio_available,created_at
            FROM emotion_records WHERE user_id = ? AND created_at >= ?{end_clause}
            ORDER BY created_at ASC,rowid ASC LIMIT ?""",
            tuple(parameters),
        ).fetchall()
    return [{
        "id": row["id"], "user_id": row["user_id"], "text": float(row["text_score"]),
        "audio": float(row["audio_score"]), "fusion": float(row["fusion_score"]),
        "audio_available": bool(row["audio_available"]), "created_at": row["created_at"],
    } for row in rows]


def delete_emotion_records(user_id: str) -> int:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        cursor = connection.execute("DELETE FROM emotion_records WHERE user_id = ?", (user_id,))
        return int(cursor.rowcount or 0)


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


def create_ai_diary_v2_batch(
    batch_id: str,
    user_id: str,
    date_key: str,
    observation_ids: List[str],
    *,
    created_at: str = "",
) -> Dict:
    init_chat_store()
    timestamp = normalize_timestamp_to_china(created_at)
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO ai_diary_v2_batches (
                batch_id, user_id, date_key, observation_ids_json,
                status, created_at, reviewed_at
            )
            VALUES (?, ?, ?, ?, 'pending', ?, NULL)
            """,
            (
                batch_id,
                user_id,
                date_key,
                json.dumps(observation_ids, ensure_ascii=False),
                timestamp,
            ),
        )
    return {
        "batch_id": batch_id,
        "user_id": user_id,
        "date": date_key,
        "observation_ids": list(observation_ids),
        "status": "pending",
        "created_at": timestamp,
        "reviewed_at": "",
    }


def _decode_ai_diary_v2_batch(row: sqlite3.Row) -> Dict:
    try:
        observation_ids = json.loads(row["observation_ids_json"])
    except (TypeError, json.JSONDecodeError):
        observation_ids = []
    return {
        "batch_id": str(row["batch_id"]),
        "user_id": str(row["user_id"]),
        "date": str(row["date_key"]),
        "observation_ids": observation_ids if isinstance(observation_ids, list) else [],
        "status": str(row["status"]),
        "created_at": str(row["created_at"]),
        "reviewed_at": str(row["reviewed_at"] or ""),
    }


def list_ai_diary_v2_batches(
    user_id: str,
    *,
    date_key: str = "",
    limit: int = 100,
) -> List[Dict]:
    init_chat_store()
    safe_limit = max(1, min(int(limit or 100), 500))
    clause = "AND date_key = ?" if date_key else ""
    params = (user_id, date_key, safe_limit) if date_key else (user_id, safe_limit)
    with _DB_LOCK, _connect() as connection:
        rows = connection.execute(
            f"""
            SELECT batch_id, user_id, date_key, observation_ids_json,
                   status, created_at, reviewed_at
            FROM ai_diary_v2_batches
            WHERE user_id = ?
            {clause}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [_decode_ai_diary_v2_batch(row) for row in rows]


def get_ai_diary_v2_batch(user_id: str, batch_id: str) -> Dict | None:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        row = connection.execute(
            """
            SELECT batch_id, user_id, date_key, observation_ids_json,
                   status, created_at, reviewed_at
            FROM ai_diary_v2_batches
            WHERE user_id = ? AND batch_id = ?
            """,
            (user_id, batch_id),
        ).fetchone()
    return _decode_ai_diary_v2_batch(row) if row else None


def mark_ai_diary_v2_batch_reviewed(user_id: str, batch_id: str) -> Dict | None:
    init_chat_store()
    reviewed_at = normalize_timestamp_to_china("")
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            UPDATE ai_diary_v2_batches
            SET status = 'reviewed', reviewed_at = ?
            WHERE user_id = ? AND batch_id = ?
            """,
            (reviewed_at, user_id, batch_id),
        )
    return get_ai_diary_v2_batch(user_id, batch_id)


def delete_ai_diary_v2_batches(user_id: str) -> int:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM ai_diary_v2_batches WHERE user_id = ?",
            (user_id,),
        )
        return int(cursor.rowcount or 0)


def delete_runtime_state_for_user(user_id: str) -> int:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM runtime_state WHERE key LIKE ?",
            (f"v2:%:{user_id}",),
        )
        return int(cursor.rowcount or 0)
