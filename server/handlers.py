import json
import mimetypes
import os
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from core.config import ALLOWED_ORIGINS, FACE_TASK_PATH, STATIC_DIR
from diary.store import get_diary_index_payload
from server.service import (
    DEFAULT_MEMORY_USER_ID,
    analyze_and_reply,
    handle_chat_history,
    handle_diary_refresh,
    handle_diary_review,
    handle_diary_user,
    handle_diary_user_delete,
    handle_memory_clear,
    handle_memory_decay,
    handle_memory_delete,
    handle_memory_query,
    handle_user_clear,
)


INTERNAL_SECRET = os.environ.get("YUNQUE_INTERNAL_SECRET", "").strip()


class AppHandler(BaseHTTPRequestHandler):
    @staticmethod
    def is_allowed_origin(origin: str) -> bool:
        if not origin:
            return False
        if "*" in ALLOWED_ORIGINS or origin in ALLOWED_ORIGINS:
            return True
        parsed = urlparse(origin)
        hostname = parsed.hostname or ""
        return parsed.scheme == "https" and (
            hostname == "irises.me"
            or hostname.endswith(".irises.me")
            or hostname.endswith(".pages.dev")
        )

    @staticmethod
    def asset_version() -> str:
        candidates = [
            STATIC_DIR / "app.js",
            STATIC_DIR / "memory.js",
            STATIC_DIR / "styles.css",
        ]
        latest_mtime = 0
        for candidate in candidates:
            try:
                latest_mtime = max(latest_mtime, int(candidate.stat().st_mtime))
            except FileNotFoundError:
                continue
        return str(latest_mtime or 1)

    @staticmethod
    def _is_client_disconnect(exc: Exception) -> bool:
        return isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.timeout))

    def safe_write(self, data: bytes):
        try:
            self.wfile.write(data)
        except Exception as exc:
            # 浏览器刷新、跳页或取消请求时，客户端可能先断开连接。
            if not self._is_client_disconnect(exc):
                raise

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        if route in {"/", "/index.html"}:
            self.serve_html(STATIC_DIR / "index.html")
            return
        if route in {"/memory", "/memory.html"}:
            self.serve_html(STATIC_DIR / "memory.html")
            return
        if route == "/api/diary":
            user_id = self.api_user_id()
            if user_id is None:
                return
            query = parse_qs(parsed.query)
            requested_date = (query.get("date") or [""])[0]
            self.send_json(get_diary_index_payload(requested_date, user_id=user_id))
            return
        if route == "/api/memory":
            user_id = self.api_user_id()
            if user_id is None:
                return
            query = parse_qs(parsed.query)
            query["_auth_user_id"] = [user_id]
            self.send_json(handle_memory_query(query))
            return
        if route == "/api/chat/history":
            user_id = self.api_user_id()
            if user_id is None:
                return
            query = parse_qs(parsed.query)
            query["_auth_user_id"] = [user_id]
            self.send_json(handle_chat_history(query))
            return
        if route == "/face_landmarker.task":
            self.serve_file(FACE_TASK_PATH)
            return
        if route.startswith("/static/"):
            relative = route.replace("/static/", "", 1)
            self.serve_file(STATIC_DIR / relative)
            return
        static_asset = STATIC_DIR / route.lstrip("/")
        if static_asset.exists() and static_asset.is_file():
            self.serve_file(static_asset)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self):
        route = unquote(urlparse(self.path).path)
        if route not in {
            "/api/analyze",
            "/api/chat",
            "/api/diary/user",
            "/api/diary/user/delete",
            "/api/diary/refresh",
            "/api/diary/review",
            "/api/memory/clear",
            "/api/memory/delete",
            "/api/memory/decay",
            "/api/user/clear",
        }:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length or 0)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON payload"}, status=HTTPStatus.BAD_REQUEST)
            return

        user_id = self.api_user_id()
        if user_id is None:
            return
        payload["user_id"] = user_id

        try:
            if route == "/api/analyze":
                response = analyze_and_reply(payload, should_reply=False)
            elif route == "/api/chat":
                response = analyze_and_reply(payload, should_reply=True)
            elif route == "/api/diary/user":
                response = handle_diary_user(payload)
            elif route == "/api/diary/user/delete":
                response = handle_diary_user_delete(payload)
            elif route == "/api/diary/refresh":
                response = handle_diary_refresh(payload)
            elif route == "/api/diary/review":
                response = handle_diary_review(payload)
            elif route == "/api/memory/clear":
                response = handle_memory_clear(payload)
            elif route == "/api/memory/delete":
                response = handle_memory_delete(payload)
            elif route == "/api/user/clear":
                response = handle_user_clear(payload)
            else:
                response = handle_memory_decay(payload)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_json(response)

    def api_user_id(self) -> str | None:
        if INTERNAL_SECRET:
            received = self.headers.get("X-Yunque-Internal-Secret", "")
            if received != INTERNAL_SECRET:
                self.send_json({"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
                return None
        user_id = (self.headers.get("X-Yunque-User-Id") or DEFAULT_MEMORY_USER_ID).strip()
        return user_id or DEFAULT_MEMORY_USER_ID

    def serve_file(self, path: Path):
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        mime_type, _ = mimetypes.guess_type(path.name)
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_cors_headers()
        self.send_header("Content-Type", mime_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.safe_write(data)

    def serve_html(self, path: Path):
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        html = path.read_text(encoding="utf-8").replace("{{asset_version}}", self.asset_version())
        data = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_cors_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.safe_write(data)

    def send_json(self, payload, status=HTTPStatus.OK):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.safe_write(data)

    def send_cors_headers(self):
        origin = self.headers.get("Origin", "")
        if "*" in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", "*")
            return
        if self.is_allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def log_message(self, fmt, *args):
        return
