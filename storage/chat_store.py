from __future__ import annotations

import sqlite3
import threading
import uuid
import json
from typing import Dict, List

from core.config import CHAT_DB_PATH
from core.utils import normalize_timestamp_to_china


_DB_LOCK = threading.RLock()


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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_academic_profile (
                user_id TEXT PRIMARY KEY,
                stage TEXT NOT NULL DEFAULT 'high_school',
                grade TEXT DEFAULT '',
                sub_category TEXT DEFAULT '',
                province TEXT DEFAULT '',
                current_school TEXT DEFAULT '',
                target_school TEXT DEFAULT '',
                target_goal TEXT DEFAULT '',
                current_score_or_gpa TEXT DEFAULT '',
                rank_info TEXT DEFAULT '',
                extra_profile_json TEXT DEFAULT '{}',
                latest_advice TEXT DEFAULT '',
                advice_updated_at TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS academic_score_records (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                exam_date TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT 'high_school',
                total_score REAL DEFAULT 0.0,
                rank_num INTEGER DEFAULT 0,
                rank_total INTEGER DEFAULT 0,
                details_json TEXT DEFAULT '{}',
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_academic_score_user_time
            ON academic_score_records(user_id, created_at)
            """
        )
        # 支持多画像 (Multi-Profile)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_academic_profiles (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                profile_name TEXT NOT NULL,
                stage TEXT NOT NULL,
                grade TEXT DEFAULT '',
                sub_category TEXT DEFAULT '',
                province TEXT DEFAULT '',
                current_school TEXT DEFAULT '',
                target_school TEXT DEFAULT '',
                target_goal TEXT DEFAULT '',
                current_score_or_gpa TEXT DEFAULT '',
                rank_info TEXT DEFAULT '',
                extra_profile_json TEXT DEFAULT '{}',
                is_active INTEGER DEFAULT 0,
                has_chatted INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_profiles_user
            ON user_academic_profiles(user_id, is_active)
            """
        )
        # 支持独立学习页面会话 (Study Sessions)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS study_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                profile_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                subject TEXT DEFAULT '',
                prompt_seed TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_study_sessions_user
            ON study_sessions(user_id, updated_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS study_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_study_messages_session
            ON study_messages(session_id, created_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS study_files (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                mime_type TEXT NOT NULL DEFAULT '',
                file_size INTEGER NOT NULL DEFAULT 0,
                file_category TEXT NOT NULL DEFAULT 'document',
                extracted_text TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                chunk_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_study_files_session
            ON study_files(session_id, created_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS study_file_chunks (
                id TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                chunk_index INTEGER NOT NULL DEFAULT 0,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_study_chunks_session
            ON study_file_chunks(session_id, file_id, chunk_index)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS study_session_files (
                session_id TEXT NOT NULL,
                file_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                linked_at TEXT NOT NULL,
                PRIMARY KEY (session_id, file_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_study_session_files_session
            ON study_session_files(session_id, user_id)
            """
        )
        chat_columns = {row["name"] for row in connection.execute("PRAGMA table_info(chat_messages)").fetchall()}
        if "profile_id" not in chat_columns:
            connection.execute("ALTER TABLE chat_messages ADD COLUMN profile_id TEXT NOT NULL DEFAULT ''")

        study_msg_cols = {row["name"] for row in connection.execute("PRAGMA table_info(study_messages)").fetchall()}
        if "meta_json" not in study_msg_cols:
            connection.execute("ALTER TABLE study_messages ADD COLUMN meta_json TEXT NOT NULL DEFAULT '{}'")

        study_file_cols = {row["name"] for row in connection.execute("PRAGMA table_info(study_files)").fetchall()}
        if "file_type" not in study_file_cols:
            connection.execute("ALTER TABLE study_files ADD COLUMN file_type TEXT NOT NULL DEFAULT ''")
        if "topics_json" not in study_file_cols:
            connection.execute("ALTER TABLE study_files ADD COLUMN topics_json TEXT NOT NULL DEFAULT '[]'")

        study_chunk_cols = {row["name"] for row in connection.execute("PRAGMA table_info(study_file_chunks)").fetchall()}
        if "location" not in study_chunk_cols:
            connection.execute("ALTER TABLE study_file_chunks ADD COLUMN location TEXT NOT NULL DEFAULT ''")
        if "page_num" not in study_chunk_cols:
            connection.execute("ALTER TABLE study_file_chunks ADD COLUMN page_num INTEGER NOT NULL DEFAULT 1")
        if "section_title" not in study_chunk_cols:
            connection.execute("ALTER TABLE study_file_chunks ADD COLUMN section_title TEXT NOT NULL DEFAULT ''")
        if "topics_json" not in study_chunk_cols:
            connection.execute("ALTER TABLE study_file_chunks ADD COLUMN topics_json TEXT NOT NULL DEFAULT '[]'")

        # Migrate legacy session-bound files into the many-to-many study_session_files table
        connection.execute(
            """
            INSERT OR IGNORE INTO study_session_files (session_id, file_id, user_id, linked_at)
            SELECT session_id, id, user_id, created_at
            FROM study_files
            WHERE session_id IS NOT NULL AND session_id != ''
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
    profile_id: str = "",
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
        "profile_id": profile_id,
    }
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO chat_messages (
                id, user_id, role, content, created_at,
                emotion_label, valence, arousal, attachments_json, profile_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                profile_id,
            ),
        )
    return message


def list_chat_messages(user_id: str, limit: int = 20, profile_id: str = "") -> List[Dict]:
    init_chat_store()
    safe_limit = max(1, min(int(limit or 20), 100))
    clause = "AND profile_id = ?" if profile_id else ""
    params = [user_id, profile_id, safe_limit] if profile_id else [user_id, safe_limit]
    with _DB_LOCK, _connect() as connection:
        rows = connection.execute(
            f"""
            SELECT id, user_id, role, content, created_at,
                   emotion_label, valence, arousal, attachments_json, profile_id
            FROM chat_messages
            WHERE user_id = ? {clause}
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            params,
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


def _decode_academic_profile(row: sqlite3.Row | None) -> Dict | None:
    if not row:
        return None
    try:
        extra = json.loads(str(row["extra_profile_json"] or "{}"))
    except Exception:
        extra = {}
    return {
        "user_id": str(row["user_id"]),
        "stage": str(row["stage"] or "high_school"),
        "grade": str(row["grade"] or ""),
        "sub_category": str(row["sub_category"] or ""),
        "province": str(row["province"] or ""),
        "current_school": str(row["current_school"] or ""),
        "target_school": str(row["target_school"] or ""),
        "target_goal": str(row["target_goal"] or ""),
        "current_score_or_gpa": str(row["current_score_or_gpa"] or ""),
        "rank_info": str(row["rank_info"] or ""),
        "extra_profile": extra,
        "latest_advice": str(row["latest_advice"] or ""),
        "advice_updated_at": str(row["advice_updated_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }


def get_academic_profile(user_id: str) -> Dict | None:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        row = connection.execute(
            """
            SELECT user_id, stage, grade, sub_category, province,
                   current_school, target_school, target_goal,
                   current_score_or_gpa, rank_info, extra_profile_json,
                   latest_advice, advice_updated_at, updated_at
            FROM user_academic_profile
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    return _decode_academic_profile(row)


def upsert_academic_profile(user_id: str, data: Dict) -> Dict:
    init_chat_store()
    timestamp = normalize_timestamp_to_china(data.get("updated_at", ""))
    stage = str(data.get("stage") or "high_school").strip()
    grade = str(data.get("grade") or "").strip()
    sub_category = str(data.get("sub_category") or "").strip()
    province = str(data.get("province") or "").strip()
    current_school = str(data.get("current_school") or "").strip()
    target_school = str(data.get("target_school") or "").strip()
    target_goal = str(data.get("target_goal") or "").strip()
    current_score_or_gpa = str(data.get("current_score_or_gpa") or "").strip()
    rank_info = str(data.get("rank_info") or "").strip()
    extra_profile = data.get("extra_profile") or {}
    if not isinstance(extra_profile, dict):
        extra_profile = {}
    extra_json = json.dumps(extra_profile, ensure_ascii=False)

    existing = get_academic_profile(user_id)
    latest_advice = existing.get("latest_advice", "") if existing else ""
    advice_updated_at = existing.get("advice_updated_at", "") if existing else ""
    if data.get("latest_advice") is not None:
        latest_advice = str(data.get("latest_advice") or "")
        advice_updated_at = timestamp

    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO user_academic_profile (
                user_id, stage, grade, sub_category, province,
                current_school, target_school, target_goal,
                current_score_or_gpa, rank_info, extra_profile_json,
                latest_advice, advice_updated_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                stage = excluded.stage,
                grade = excluded.grade,
                sub_category = excluded.sub_category,
                province = excluded.province,
                current_school = excluded.current_school,
                target_school = excluded.target_school,
                target_goal = excluded.target_goal,
                current_score_or_gpa = excluded.current_score_or_gpa,
                rank_info = excluded.rank_info,
                extra_profile_json = excluded.extra_profile_json,
                latest_advice = excluded.latest_advice,
                advice_updated_at = excluded.advice_updated_at,
                updated_at = excluded.updated_at
            """,
            (
                user_id, stage, grade, sub_category, province,
                current_school, target_school, target_goal,
                current_score_or_gpa, rank_info, extra_json,
                latest_advice, advice_updated_at, timestamp,
            ),
        )
    return get_academic_profile(user_id) or {}


def update_academic_advice(user_id: str, advice: str) -> None:
    init_chat_store()
    timestamp = normalize_timestamp_to_china("")
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            UPDATE user_academic_profile
            SET latest_advice = ?, advice_updated_at = ?
            WHERE user_id = ?
            """,
            (advice, timestamp, user_id),
        )


def _decode_academic_score(row: sqlite3.Row) -> Dict:
    try:
        details = json.loads(str(row["details_json"] or "{}"))
    except Exception:
        details = {}
    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "title": str(row["title"] or ""),
        "exam_date": str(row["exam_date"] or ""),
        "stage": str(row["stage"] or "high_school"),
        "total_score": float(row["total_score"] or 0.0),
        "rank_num": int(row["rank_num"] or 0),
        "rank_total": int(row["rank_total"] or 0),
        "details": details,
        "notes": str(row["notes"] or ""),
        "created_at": str(row["created_at"] or ""),
    }


def add_academic_score(user_id: str, data: Dict) -> Dict:
    init_chat_store()
    score_id = str(uuid.uuid4())
    timestamp = normalize_timestamp_to_china(data.get("created_at", ""))
    exam_date = str(data.get("exam_date") or timestamp[:10]).strip()
    title = str(data.get("title") or "未命名测验").strip()
    stage = str(data.get("stage") or "high_school").strip()
    try:
        total_score = float(data.get("total_score") or 0.0)
    except (ValueError, TypeError):
        total_score = 0.0
    try:
        rank_num = int(data.get("rank_num") or 0)
    except (ValueError, TypeError):
        rank_num = 0
    try:
        rank_total = int(data.get("rank_total") or 0)
    except (ValueError, TypeError):
        rank_total = 0
    details = data.get("details") or {}
    if not isinstance(details, dict):
        details = {}
    notes = str(data.get("notes") or "").strip()

    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO academic_score_records (
                id, user_id, title, exam_date, stage,
                total_score, rank_num, rank_total,
                details_json, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                score_id, user_id, title, exam_date, stage,
                total_score, rank_num, rank_total,
                json.dumps(details, ensure_ascii=False), notes, timestamp,
            ),
        )
    return {
        "id": score_id,
        "user_id": user_id,
        "title": title,
        "exam_date": exam_date,
        "stage": stage,
        "total_score": total_score,
        "rank_num": rank_num,
        "rank_total": rank_total,
        "details": details,
        "notes": notes,
        "created_at": timestamp,
    }


def list_academic_scores(user_id: str, limit: int = 50) -> List[Dict]:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, user_id, title, exam_date, stage,
                   total_score, rank_num, rank_total,
                   details_json, notes, created_at
            FROM academic_score_records
            WHERE user_id = ?
            ORDER BY exam_date DESC, created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [_decode_academic_score(row) for row in rows]


def delete_academic_data_for_user(user_id: str) -> None:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        connection.execute("DELETE FROM user_academic_profile WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM user_academic_profiles WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM academic_score_records WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM study_sessions WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM study_messages WHERE user_id = ?", (user_id,))


# --- 多 Profile (画像) 支持 ---

def _decode_profile_row(row: sqlite3.Row | None) -> Dict | None:
    if not row:
        return None
    try:
        extra = json.loads(str(row["extra_profile_json"] or "{}"))
    except Exception:
        extra = {}
    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "profile_name": str(row["profile_name"] or "未命名画像"),
        "stage": str(row["stage"] or "high_school"),
        "grade": str(row["grade"] or ""),
        "sub_category": str(row["sub_category"] or ""),
        "province": str(row["province"] or ""),
        "current_school": str(row["current_school"] or ""),
        "target_school": str(row["target_school"] or ""),
        "target_goal": str(row["target_goal"] or ""),
        "current_score_or_gpa": str(row["current_score_or_gpa"] or ""),
        "rank_info": str(row["rank_info"] or ""),
        "extra_profile": extra,
        "is_active": bool(row["is_active"]),
        "has_chatted": bool(row["has_chatted"]),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }


def list_user_profiles(user_id: str) -> List[Dict]:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, user_id, profile_name, stage, grade, sub_category, province,
                   current_school, target_school, target_goal, current_score_or_gpa,
                   rank_info, extra_profile_json, is_active, has_chatted, created_at, updated_at
            FROM user_academic_profiles
            WHERE user_id = ?
            ORDER BY is_active DESC, updated_at DESC
            """,
            (user_id,),
        ).fetchall()
        profiles = [_decode_profile_row(r) for r in rows if r]
        if not profiles:
            old_row = connection.execute(
                """
                SELECT user_id, stage, grade, sub_category, province,
                       current_school, target_school, target_goal,
                       current_score_or_gpa, rank_info, extra_profile_json,
                       latest_advice, advice_updated_at, updated_at
                FROM user_academic_profile
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            old = _decode_academic_profile(old_row) if old_row else None
            default_id = str(uuid.uuid4())
            ts = normalize_timestamp_to_china("")
            stage = old.get("stage") if old else "high_school"
            name = "高中画像" if stage == "high_school" else ("大学画像" if stage == "undergraduate" else "成长画像")
            connection.execute(
                """
                INSERT INTO user_academic_profiles (
                    id, user_id, profile_name, stage, grade, sub_category, province,
                    current_school, target_school, target_goal, current_score_or_gpa,
                    rank_info, extra_profile_json, is_active, has_chatted, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?)
                """,
                (
                    default_id, user_id, name, stage,
                    old.get("grade", "") if old else "高三",
                    old.get("sub_category", "") if old else "",
                    old.get("province", "") if old else "",
                    old.get("current_school", "") if old else "",
                    old.get("target_school", "") if old else "",
                    old.get("target_goal", "") if old else "",
                    old.get("current_score_or_gpa", "") if old else "",
                    old.get("rank_info", "") if old else "",
                    json.dumps(old.get("extra_profile", {}) if old else {}, ensure_ascii=False),
                    ts, ts,
                ),
            )
            rows = connection.execute(
                "SELECT * FROM user_academic_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            profiles = [_decode_profile_row(r) for r in rows if r]
    return profiles


def profile_has_user_chatted(user_id: str, profile_id: str) -> bool:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        row = connection.execute(
            "SELECT has_chatted FROM user_academic_profiles WHERE user_id = ? AND id = ?",
            (user_id, profile_id),
        ).fetchone()
        if row and row["has_chatted"]:
            return True
        msg = connection.execute(
            "SELECT id FROM chat_messages WHERE user_id = ? AND profile_id = ? AND role = 'user' LIMIT 1",
            (user_id, profile_id),
        ).fetchone()
        return bool(msg)


def get_active_profile(user_id: str) -> Dict | None:
    profiles = list_user_profiles(user_id)
    for p in profiles:
        if p["is_active"]:
            return p
    return profiles[0] if profiles else None


def create_user_profile(user_id: str, data: Dict) -> Dict:
    init_chat_store()
    stage = str(data.get("stage") or "").strip()
    if not stage:
        raise ValueError("学业阶段（学历）为必填项！请选择高中、大学或成长阶段。")
    name = str(data.get("profile_name") or data.get("name") or "").strip()
    if not name:
        name = "高中画像" if stage == "high_school" else ("本科画像" if stage == "undergraduate" else "成长画像")
    profile_id = str(uuid.uuid4())
    ts = normalize_timestamp_to_china(data.get("created_at", ""))
    extra_json = json.dumps(data.get("extra_profile") or {}, ensure_ascii=False)

    with _DB_LOCK, _connect() as connection:
        connection.execute("UPDATE user_academic_profiles SET is_active = 0 WHERE user_id = ?", (user_id,))
        connection.execute(
            """
            INSERT INTO user_academic_profiles (
                id, user_id, profile_name, stage, grade, sub_category, province,
                current_school, target_school, target_goal, current_score_or_gpa,
                rank_info, extra_profile_json, is_active, has_chatted, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?)
            """,
            (
                profile_id, user_id, name, stage,
                str(data.get("grade") or "").strip(),
                str(data.get("sub_category") or "").strip(),
                str(data.get("province") or "").strip(),
                str(data.get("current_school") or "").strip(),
                str(data.get("target_school") or "").strip(),
                str(data.get("target_goal") or "").strip(),
                str(data.get("current_score_or_gpa") or "").strip(),
                str(data.get("rank_info") or "").strip(),
                extra_json, ts, ts,
            ),
        )
    return get_active_profile(user_id) or {}


def set_active_profile(user_id: str, profile_id: str) -> Dict | None:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        connection.execute("UPDATE user_academic_profiles SET is_active = 0 WHERE user_id = ?", (user_id,))
        connection.execute("UPDATE user_academic_profiles SET is_active = 1 WHERE user_id = ? AND id = ?", (user_id, profile_id))
    return get_active_profile(user_id)


def update_user_profile(user_id: str, profile_id: str, data: Dict) -> Dict | None:
    init_chat_store()
    ts = normalize_timestamp_to_china("")
    extra_json = json.dumps(data.get("extra_profile") or {}, ensure_ascii=False)
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            UPDATE user_academic_profiles
            SET profile_name = coalesce(nullif(?, ''), profile_name),
                stage = coalesce(nullif(?, ''), stage),
                grade = ?, sub_category = ?, province = ?,
                current_school = ?, target_school = ?, target_goal = ?,
                current_score_or_gpa = ?, rank_info = ?, extra_profile_json = ?,
                updated_at = ?
            WHERE user_id = ? AND id = ?
            """,
            (
                str(data.get("profile_name") or ""),
                str(data.get("stage") or ""),
                str(data.get("grade") or ""),
                str(data.get("sub_category") or ""),
                str(data.get("province") or ""),
                str(data.get("current_school") or ""),
                str(data.get("target_school") or ""),
                str(data.get("target_goal") or ""),
                str(data.get("current_score_or_gpa") or ""),
                str(data.get("rank_info") or ""),
                extra_json,
                ts,
                user_id,
                profile_id,
            ),
        )
    return get_active_profile(user_id)


def delete_user_profile(user_id: str, profile_id: str) -> bool:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        connection.execute("DELETE FROM user_academic_profiles WHERE user_id = ? AND id = ?", (user_id, profile_id))
        active = connection.execute("SELECT id FROM user_academic_profiles WHERE user_id = ? AND is_active = 1", (user_id,)).fetchone()
        if not active:
            connection.execute(
                """
                UPDATE user_academic_profiles
                SET is_active = 1
                WHERE id = (SELECT id FROM user_academic_profiles WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1)
                """,
                (user_id,),
            )
    return True


def mark_profile_chatted(user_id: str, profile_id: str) -> None:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            "UPDATE user_academic_profiles SET has_chatted = 1 WHERE user_id = ? AND id = ?",
            (user_id, profile_id),
        )


# --- 学习会话 (Study Sessions) 支持 ---

def create_study_session(user_id: str, profile_id: str, title: str, subject: str = "", prompt_seed: str = "") -> Dict:
    init_chat_store()
    session_id = str(uuid.uuid4())
    ts = normalize_timestamp_to_china("")
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO study_sessions (id, user_id, profile_id, title, subject, prompt_seed, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, user_id, profile_id, title, subject, prompt_seed, ts, ts),
        )
    return {
        "id": session_id,
        "user_id": user_id,
        "profile_id": profile_id,
        "title": title,
        "subject": subject,
        "prompt_seed": prompt_seed,
        "created_at": ts,
        "updated_at": ts,
    }


def list_study_sessions(user_id: str, profile_id: str = "") -> List[Dict]:
    init_chat_store()
    clause = "AND profile_id = ?" if profile_id else ""
    params = [user_id, profile_id] if profile_id else [user_id]
    with _DB_LOCK, _connect() as connection:
        rows = connection.execute(
            f"""
            SELECT id, user_id, profile_id, title, subject, prompt_seed, created_at, updated_at
            FROM study_sessions
            WHERE user_id = ? {clause}
            ORDER BY updated_at DESC
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def get_study_session(user_id: str, session_id: str) -> Dict | None:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        row = connection.execute(
            "SELECT * FROM study_sessions WHERE user_id = ? AND id = ?",
            (user_id, session_id),
        ).fetchone()
        return dict(row) if row else None


def add_study_message(session_id: str, user_id: str, role: str, content: str, meta: Dict | None = None) -> Dict:
    init_chat_store()
    msg_id = str(uuid.uuid4())
    ts = normalize_timestamp_to_china("")
    meta_dict = meta if isinstance(meta, dict) else {}
    meta_json = json.dumps(meta_dict, ensure_ascii=False)
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO study_messages (id, session_id, user_id, role, content, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (msg_id, session_id, user_id, role, content, meta_json, ts),
        )
        connection.execute(
            "UPDATE study_sessions SET updated_at = ? WHERE id = ?",
            (ts, session_id),
        )
    return {
        "id": msg_id,
        "session_id": session_id,
        "user_id": user_id,
        "role": role,
        "content": content,
        "meta": meta_dict,
        "created_at": ts,
    }


def list_study_messages(session_id: str) -> List[Dict]:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        rows = connection.execute(
            "SELECT id, session_id, user_id, role, content, meta_json, created_at FROM study_messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
        items: List[Dict] = []
        for r in rows:
            d = dict(r)
            try:
                d["meta"] = json.loads(d.pop("meta_json", "{}") or "{}")
            except Exception:
                d["meta"] = {}
            items.append(d)
        return items


def _deserialize_file_row(row: Any, linked_ids: set[str] | None = None) -> Dict:
    d = dict(row)
    try:
        d["topics"] = json.loads(d.pop("topics_json", "[]") or "[]")
    except Exception:
        d["topics"] = []
    if linked_ids is not None:
        d["linked"] = d["id"] in linked_ids
    return d


def _deserialize_chunk_row(row: Any) -> Dict:
    d = dict(row)
    try:
        d["topics"] = json.loads(d.pop("topics_json", "[]") or "[]")
    except Exception:
        d["topics"] = []
    if not d.get("location"):
        d["location"] = f"片段 {int(d.get('chunk_index', 0)) + 1}"
    return d


def save_library_file(
    *,
    user_id: str,
    file_name: str,
    mime_type: str,
    file_size: int,
    file_category: str,
    file_type: str,
    extracted_text: str,
    chunks: List[Dict],
    topics: List[str],
    session_id: str = "",
) -> Dict:
    init_chat_store()
    file_id = str(uuid.uuid4())
    ts = normalize_timestamp_to_china("")
    summary = (extracted_text or "").strip().replace("\n", " ")[:180]
    topics_json = json.dumps(topics or [], ensure_ascii=False)
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO study_files (
                id, session_id, user_id, file_name, mime_type, file_size,
                file_category, file_type, topics_json, extracted_text, summary, chunk_count, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                session_id or "",
                user_id,
                file_name,
                mime_type,
                int(file_size or 0),
                file_category,
                file_type or file_category,
                topics_json,
                extracted_text or "",
                summary,
                len(chunks),
                ts,
            ),
        )
        for idx, ch in enumerate(chunks):
            if isinstance(ch, str):
                ch_content = ch
                ch_loc = f"片段 {idx + 1}"
                ch_page = idx + 1
                ch_title = file_name
                ch_topics: List[str] = []
                ch_index = idx
            else:
                ch_content = str(ch.get("content") or "")
                ch_loc = str(ch.get("location") or f"片段 {idx + 1}")
                ch_page = int(ch.get("page_num") or (idx + 1))
                ch_title = str(ch.get("section_title") or file_name)
                ch_topics = list(ch.get("topics") or [])
                ch_index = int(ch.get("chunk_index", idx))
            connection.execute(
                """
                INSERT INTO study_file_chunks (
                    id, file_id, session_id, user_id, file_name, chunk_index,
                    location, page_num, section_title, topics_json, content, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    file_id,
                    session_id or "",
                    user_id,
                    file_name,
                    ch_index,
                    ch_loc,
                    ch_page,
                    ch_title,
                    json.dumps(ch_topics, ensure_ascii=False),
                    ch_content,
                    ts,
                ),
            )
        if session_id:
            connection.execute(
                """
                INSERT OR IGNORE INTO study_session_files (session_id, file_id, user_id, linked_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, file_id, user_id, ts),
            )
            connection.execute("UPDATE study_sessions SET updated_at = ? WHERE id = ?", (ts, session_id))
    return {
        "id": file_id,
        "session_id": session_id or "",
        "file_name": file_name,
        "mime_type": mime_type,
        "file_size": int(file_size or 0),
        "file_category": file_category,
        "file_type": file_type or file_category,
        "topics": topics or [],
        "summary": summary,
        "chunk_count": len(chunks),
        "linked": bool(session_id),
        "created_at": ts,
    }


def save_study_file(
    *,
    session_id: str,
    user_id: str,
    file_name: str,
    mime_type: str,
    file_size: int,
    file_category: str,
    extracted_text: str,
    chunks: List[Any],
    file_type: str = "",
    topics: List[str] | None = None,
) -> Dict:
    return save_library_file(
        user_id=user_id,
        file_name=file_name,
        mime_type=mime_type,
        file_size=file_size,
        file_category=file_category,
        file_type=file_type or file_category,
        extracted_text=extracted_text,
        chunks=chunks,
        topics=topics or [],
        session_id=session_id,
    )


def list_library_files(user_id: str, session_id: str = "") -> List[Dict]:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        linked_ids: set[str] | None = None
        if session_id:
            lrows = connection.execute(
                "SELECT file_id FROM study_session_files WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            ).fetchall()
            linked_ids = {r["file_id"] for r in lrows}
        rows = connection.execute(
            """
            SELECT id, session_id, file_name, mime_type, file_size, file_category,
                   file_type, topics_json, summary, chunk_count, created_at
            FROM study_files
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        ).fetchall()
        return [_deserialize_file_row(r, linked_ids) for r in rows]


def list_session_linked_files(user_id: str, session_id: str) -> List[Dict]:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        rows = connection.execute(
            """
            SELECT f.id, f.session_id, f.file_name, f.mime_type, f.file_size, f.file_category,
                   f.file_type, f.topics_json, f.summary, f.chunk_count, f.created_at
            FROM study_files f
            INNER JOIN study_session_files ssf
              ON ssf.file_id = f.id AND ssf.user_id = f.user_id
            WHERE ssf.user_id = ? AND ssf.session_id = ?
            ORDER BY ssf.linked_at DESC
            """,
            (user_id, session_id),
        ).fetchall()
        out = []
        for r in rows:
            item = _deserialize_file_row(r)
            item["linked"] = True
            out.append(item)
        return out


def set_session_file_link(user_id: str, session_id: str, file_id: str, linked: bool) -> bool:
    init_chat_store()
    ts = normalize_timestamp_to_china("")
    with _DB_LOCK, _connect() as connection:
        exists = connection.execute(
            "SELECT 1 FROM study_files WHERE id = ? AND user_id = ?",
            (file_id, user_id),
        ).fetchone()
        if not exists:
            return False
        if linked:
            connection.execute(
                """
                INSERT OR IGNORE INTO study_session_files (session_id, file_id, user_id, linked_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, file_id, user_id, ts),
            )
        else:
            connection.execute(
                "DELETE FROM study_session_files WHERE session_id = ? AND file_id = ? AND user_id = ?",
                (session_id, file_id, user_id),
            )
        connection.execute("UPDATE study_sessions SET updated_at = ? WHERE id = ?", (ts, session_id))
        return True


def set_session_linked_files(user_id: str, session_id: str, file_ids: List[str]) -> List[Dict]:
    init_chat_store()
    ts = normalize_timestamp_to_china("")
    clean_ids = list(dict.fromkeys(str(fid).strip() for fid in (file_ids or []) if str(fid).strip()))
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            "DELETE FROM study_session_files WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        )
        for fid in clean_ids:
            exists = connection.execute(
                "SELECT 1 FROM study_files WHERE id = ? AND user_id = ?",
                (fid, user_id),
            ).fetchone()
            if exists:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO study_session_files (session_id, file_id, user_id, linked_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (session_id, fid, user_id, ts),
                )
        connection.execute("UPDATE study_sessions SET updated_at = ? WHERE id = ?", (ts, session_id))
    return list_session_linked_files(user_id, session_id)


def get_session_linked_chunks(user_id: str, session_id: str) -> List[Dict]:
    """严格仅返回当前自习室 session 已关联资料的切片。"""
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        rows = connection.execute(
            """
            SELECT c.id, c.file_id, c.file_name, c.chunk_index,
                   c.location, c.page_num, c.section_title, c.topics_json, c.content
            FROM study_file_chunks c
            INNER JOIN study_session_files ssf
              ON ssf.file_id = c.file_id AND ssf.user_id = c.user_id
            WHERE ssf.user_id = ? AND ssf.session_id = ?
            ORDER BY ssf.linked_at ASC, c.file_id ASC, c.chunk_index ASC
            """,
            (user_id, session_id),
        ).fetchall()
        return [_deserialize_chunk_row(r) for r in rows]


def get_library_file_chunks(user_id: str, file_id: str) -> List[Dict]:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, file_id, file_name, chunk_index,
                   location, page_num, section_title, topics_json, content
            FROM study_file_chunks
            WHERE user_id = ? AND file_id = ?
            ORDER BY chunk_index ASC
            """,
            (user_id, file_id),
        ).fetchall()
        return [_deserialize_chunk_row(r) for r in rows]


def delete_library_file(user_id: str, file_id: str) -> bool:
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        cur = connection.execute(
            "DELETE FROM study_files WHERE id = ? AND user_id = ?",
            (file_id, user_id),
        )
        connection.execute(
            "DELETE FROM study_file_chunks WHERE file_id = ? AND user_id = ?",
            (file_id, user_id),
        )
        connection.execute(
            "DELETE FROM study_session_files WHERE file_id = ? AND user_id = ?",
            (file_id, user_id),
        )
        return cur.rowcount > 0


def list_study_files(user_id: str, session_id: str) -> List[Dict]:
    return list_session_linked_files(user_id, session_id)


def get_study_file_chunks(session_id: str, user_id: str = "") -> List[Dict]:
    if user_id:
        return get_session_linked_chunks(user_id, session_id)
    init_chat_store()
    with _DB_LOCK, _connect() as connection:
        rows = connection.execute(
            """
            SELECT c.id, c.file_id, c.file_name, c.chunk_index,
                   c.location, c.page_num, c.section_title, c.topics_json, c.content
            FROM study_file_chunks c
            INNER JOIN study_session_files ssf ON ssf.file_id = c.file_id
            WHERE ssf.session_id = ?
            ORDER BY ssf.linked_at ASC, c.file_id ASC, c.chunk_index ASC
            """,
            (session_id,),
        ).fetchall()
        return [_deserialize_chunk_row(r) for r in rows]


def delete_study_file(user_id: str, session_id: str, file_id: str) -> bool:
    # Unlink from session without deleting from global library unless explicitly deleted via library API
    return set_session_file_link(user_id, session_id, file_id, False)


def delete_study_and_profile_data_for_user(user_id: str) -> Dict[str, int]:
    """按 user_id 彻底清理该用户的自习室会话、消息、学习资料库、切片关联与角色档案。"""
    init_chat_store()
    counts: Dict[str, int] = {}
    with _DB_LOCK, _connect() as connection:
        for table in (
            "study_session_files",
            "study_file_chunks",
            "study_files",
            "study_messages",
            "study_sessions",
            "user_academic_profiles",
        ):
            cur = connection.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            counts[table] = int(cur.rowcount or 0)
    return counts
