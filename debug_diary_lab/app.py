from __future__ import annotations

import json
import mimetypes
import sqlite3
import uuid
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DB_PATH = ROOT / "debug_diary.sqlite3"
HOST = "127.0.0.1"
PORT = 8011


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def init_db() -> None:
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                date_key TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_date
            ON chat_messages(date_key, created_at)
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_ai_diary_dates (
                date_key TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_diaries (
                date_key TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                status TEXT NOT NULL,
                generated_at TEXT NOT NULL
            )
            """
        )
        if get_current_date(db) is None:
            set_current_date(date.today().isoformat(), db)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_date_key(value: str) -> str:
    parsed = date.fromisoformat(value)
    return parsed.isoformat()


def get_current_date(db: sqlite3.Connection | None = None) -> str | None:
    owns_connection = db is None
    db = db or connect()
    try:
        row = db.execute("SELECT value FROM app_state WHERE key = 'current_date'").fetchone()
        return row["value"] if row else None
    finally:
        if owns_connection:
            db.close()


def set_current_date(date_key: str, db: sqlite3.Connection | None = None) -> None:
    owns_connection = db is None
    db = db or connect()
    try:
        db.execute(
            """
            INSERT INTO app_state (key, value)
            VALUES ('current_date', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (parse_date_key(date_key),),
        )
    finally:
        if owns_connection:
            db.commit()
            db.close()


def mark_pending(date_key: str) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO pending_ai_diary_dates (date_key, updated_at)
            VALUES (?, ?)
            ON CONFLICT(date_key) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (date_key, now_iso()),
        )


def list_messages(date_key: str) -> list[dict]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT id, date_key, role, content, created_at
            FROM chat_messages
            WHERE date_key = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (date_key,),
        ).fetchall()
    return [dict(row) for row in rows]


def add_message(date_key: str, role: str, content: str) -> dict:
    text = (content or "").strip()
    if not text:
        raise ValueError("empty message")
    message = {
        "id": uuid.uuid4().hex,
        "date_key": parse_date_key(date_key),
        "role": "assistant" if role in {"assistant", "agent"} else "user",
        "content": text,
        "created_at": now_iso(),
    }
    with connect() as db:
        db.execute(
            """
            INSERT INTO chat_messages (id, date_key, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (message["id"], message["date_key"], message["role"], message["content"], message["created_at"]),
        )
    mark_pending(message["date_key"])
    return message


def build_ai_diary(date_key: str, messages: list[dict]) -> str:
    user_messages = [item["content"] for item in messages if item["role"] == "user"]
    assistant_messages = [item["content"] for item in messages if item["role"] == "assistant"]
    user_summary = "；".join(user_messages[-4:]) if user_messages else "这一天还没有用户输入。"
    support_summary = "；".join(assistant_messages[-3:]) if assistant_messages else "云雀还没有形成明显回应线索。"
    return "\n".join(
        [
            f"# AI记 {date_key}",
            "",
            "## 今日概览",
            f"这一天共有 {len(messages)} 条调试对话，其中用户输入 {len(user_messages)} 条。",
            "",
            "## 用户状态",
            f"- 用户主要提到：{user_summary}",
            "",
            "## 日记线索",
            "这是调试环境自动生成的 AI记，不会写入正式数据。",
            "",
            "## 陪伴观察",
            f"云雀回应线索：{support_summary}",
        ]
    )


def generate_diary_for_date(date_key: str) -> bool:
    messages = list_messages(date_key)
    if not messages:
        return False
    content = build_ai_diary(date_key, messages)
    with connect() as db:
        db.execute(
            """
            INSERT INTO ai_diaries (date_key, content, status, generated_at)
            VALUES (?, ?, 'pending', ?)
            ON CONFLICT(date_key)
            DO UPDATE SET content = excluded.content,
                          status = excluded.status,
                          generated_at = excluded.generated_at
            """,
            (date_key, content, now_iso()),
        )
        db.execute("DELETE FROM pending_ai_diary_dates WHERE date_key = ?", (date_key,))
    return True


def generate_pending_before(today_key: str) -> list[str]:
    today_key = parse_date_key(today_key)
    with connect() as db:
        rows = db.execute(
            """
            SELECT date_key
            FROM pending_ai_diary_dates
            WHERE date_key < ?
            ORDER BY date_key ASC
            """,
            (today_key,),
        ).fetchall()
    generated: list[str] = []
    for row in rows:
        if generate_diary_for_date(row["date_key"]):
            generated.append(row["date_key"])
    return generated


def get_ai_diary(date_key: str) -> dict:
    with connect() as db:
        row = db.execute(
            """
            SELECT date_key, content, status, generated_at
            FROM ai_diaries
            WHERE date_key = ?
            """,
            (date_key,),
        ).fetchone()
        pending = db.execute(
            "SELECT date_key FROM pending_ai_diary_dates WHERE date_key = ?",
            (date_key,),
        ).fetchone()
    if row:
        return dict(row)
    return {
        "date_key": date_key,
        "content": "这一天暂时还没有 AI记。若该日期有聊天记录，请切到下一天触发生成。",
        "status": "pending_generation" if pending else "not_ready",
        "generated_at": "",
    }


def month_payload(year: int, month: int) -> dict:
    prefix = f"{year:04d}-{month:02d}-"
    with connect() as db:
        message_dates = {
            row["date_key"]
            for row in db.execute(
                "SELECT DISTINCT date_key FROM chat_messages WHERE date_key LIKE ?",
                (f"{prefix}%",),
            ).fetchall()
        }
        diary_dates = {
            row["date_key"]
            for row in db.execute(
                "SELECT DISTINCT date_key FROM ai_diaries WHERE date_key LIKE ?",
                (f"{prefix}%",),
            ).fetchall()
        }
        pending_dates = {
            row["date_key"]
            for row in db.execute(
                "SELECT DISTINCT date_key FROM pending_ai_diary_dates WHERE date_key LIKE ?",
                (f"{prefix}%",),
            ).fetchall()
        }
    return {
        "year": year,
        "month": month,
        "message_dates": sorted(message_dates),
        "diary_dates": sorted(diary_dates),
        "pending_dates": sorted(pending_dates),
    }


def state_payload(selected_date: str = "") -> dict:
    current_date = get_current_date() or date.today().isoformat()
    date_key = parse_date_key(selected_date or current_date)
    selected = date.fromisoformat(date_key)
    return {
        "current_date": current_date,
        "selected_date": date_key,
        "messages": list_messages(date_key),
        "ai_diary": get_ai_diary(date_key),
        "month": month_payload(selected.year, selected.month),
        "db_path": str(DB_PATH),
    }


class DebugHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        if route in {"/", "/index.html"}:
            return self.serve_file(STATIC_DIR / "index.html")
        if route == "/api/state":
            query = parse_qs(parsed.query)
            return self.send_json(state_payload((query.get("date") or [""])[0]))
        asset = STATIC_DIR / route.lstrip("/")
        if asset.exists() and asset.is_file():
            return self.serve_file(asset)
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        payload = self.read_json()
        try:
            if route == "/api/chat":
                date_key = parse_date_key(payload.get("date") or get_current_date() or date.today().isoformat())
                user_message = add_message(date_key, "user", payload.get("message", ""))
                reply = add_message(date_key, "assistant", f"我记下了：{user_message['content']}")
                return self.send_json({"ok": True, "messages": [user_message, reply], **state_payload(date_key)})
            if route == "/api/day":
                date_key = parse_date_key(payload.get("date") or date.today().isoformat())
                set_current_date(date_key)
                generated = generate_pending_before(date_key)
                return self.send_json({"ok": True, "generated": generated, **state_payload(date_key)})
            if route == "/api/generate":
                date_key = parse_date_key(payload.get("date") or get_current_date() or date.today().isoformat())
                generated = generate_diary_for_date(date_key)
                return self.send_json({"ok": generated, "generated": [date_key] if generated else [], **state_payload(date_key)})
            if route == "/api/reset":
                if DB_PATH.exists():
                    DB_PATH.unlink()
                for suffix in ("-wal", "-shm"):
                    path = Path(f"{DB_PATH}{suffix}")
                    if path.exists():
                        path.unlink()
                init_db()
                return self.send_json({"ok": True, **state_payload()})
        except Exception as exc:
            return self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length or 0)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def serve_file(self, path: Path):
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        data = path.read_bytes()
        mime_type, _ = mimetypes.guess_type(path.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), DebugHandler)
    print(f"AI记调试小站：http://{HOST}:{PORT}")
    print(f"调试数据库：{DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()

