from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from typing import Dict, Optional, Tuple

from core.config import CHAT_DB_PATH
from core.utils import normalize_timestamp_to_china

_AUTH_LOCK = threading.RLock()
SESSION_COOKIE_NAME = "lark_session"
LEGACY_SESSION_COOKIE_NAME = "yunque_session"
SESSION_MAX_AGE_SECONDS = int(os.environ.get("LARK_SESSION_MAX_AGE", str(30 * 24 * 3600)) or (30 * 24 * 3600))
_PBKDF2_ITERATIONS = 200_000


def _connect() -> sqlite3.Connection:
    CHAT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CHAT_DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_store() -> None:
    with _AUTH_LOCK, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                username_lower TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_user
            ON auth_sessions(user_id, expires_at)
            """
        )


def _hash_password(password: str, salt_hex: str | None = None) -> str:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iter_str, salt_hex, expected_hex = stored_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations)
        return hmac.compare_digest(dk.hex(), expected_hex)
    except Exception:
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _validate_credentials(username: str, password: str) -> Tuple[str, str]:
    uname = (username or "").strip()
    if len(uname) < 2 or len(uname) > 32:
        raise ValueError("用户名长度需在 2 到 32 个字符之间。")
    if re.search(r"[\r\n\t]", uname):
        raise ValueError("用户名包含非法字符。")
    if not password or len(password) < 6:
        raise ValueError("密码长度至少为 6 位。")
    if len(password) > 128:
        raise ValueError("密码过长。")
    return uname, password


def _create_session(conn: sqlite3.Connection, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now_ts = int(time.time())
    expires_at = now_ts + max(3600, SESSION_MAX_AGE_SECONDS)
    conn.execute(
        """
        INSERT INTO auth_sessions (token_hash, user_id, expires_at, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (_hash_token(token), user_id, expires_at, normalize_timestamp_to_china("")),
    )
    return token


def register_user(username: str, password: str) -> Tuple[Dict[str, str], str]:
    init_auth_store()
    uname, pwd = _validate_credentials(username, password)
    uname_lower = uname.lower()
    user_id = f"u_{uuid.uuid4().hex[:16]}"
    pw_hash = _hash_password(pwd)
    ts = normalize_timestamp_to_china("")
    with _AUTH_LOCK, _connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM auth_users WHERE username_lower = ?",
            (uname_lower,),
        ).fetchone()
        if exists:
            raise ValueError("该用户名已被注册。")
        conn.execute(
            """
            INSERT INTO auth_users (id, username, username_lower, password_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, uname, uname_lower, pw_hash, ts),
        )
        token = _create_session(conn, user_id)
    return {"id": user_id, "username": uname}, token


def login_user(username: str, password: str) -> Tuple[Dict[str, str], str]:
    init_auth_store()
    uname = (username or "").strip()
    if not uname or not password:
        raise ValueError("请输入用户名和密码。")
    with _AUTH_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash FROM auth_users WHERE username_lower = ?",
            (uname.lower(),),
        ).fetchone()
        if not row or not _verify_password(password, str(row["password_hash"])):
            raise ValueError("用户名或密码错误。")
        token = _create_session(conn, str(row["id"]))
    return {"id": str(row["id"]), "username": str(row["username"])}, token


def get_session_user(token: str) -> Optional[Dict[str, str]]:
    if not token:
        return None
    init_auth_store()
    tok_hash = _hash_token(token.strip())
    now_ts = int(time.time())
    with _AUTH_LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT s.user_id, s.expires_at, u.username
            FROM auth_sessions s
            INNER JOIN auth_users u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (tok_hash,),
        ).fetchone()
        if not row:
            return None
        if int(row["expires_at"]) <= now_ts:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (tok_hash,))
            return None
        return {"id": str(row["user_id"]), "username": str(row["username"])}


def revoke_session(token: str) -> None:
    if not token:
        return
    init_auth_store()
    tok_hash = _hash_token(token.strip())
    with _AUTH_LOCK, _connect() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (tok_hash,))
