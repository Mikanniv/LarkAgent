import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from core.config import ALLOWED_ORIGINS, FACE_TASK_PATH, STATIC_DIR
from diary.store import get_diary_index_payload
from server.service import analyze_and_reply, handle_diary_refresh, handle_diary_user


class AppHandler(BaseHTTPRequestHandler):
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
        if route == "/":
            self.serve_file(STATIC_DIR / "index.html")
            return
        if route == "/api/diary":
            query = parse_qs(parsed.query)
            requested_date = (query.get("date") or [""])[0]
            self.send_json(get_diary_index_payload(requested_date))
            return
        if route == "/face_landmarker.task":
            self.serve_file(FACE_TASK_PATH)
            return
        if route.startswith("/static/"):
            relative = route.replace("/static/", "", 1)
            self.serve_file(STATIC_DIR / relative)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self):
        route = unquote(urlparse(self.path).path)
        if route not in {"/api/analyze", "/api/chat", "/api/diary/user", "/api/diary/refresh"}:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length or 0)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON payload"}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            if route == "/api/analyze":
                response = analyze_and_reply(payload, should_reply=False)
            elif route == "/api/chat":
                response = analyze_and_reply(payload, should_reply=True)
            elif route == "/api/diary/user":
                response = handle_diary_user(payload)
            else:
                response = handle_diary_refresh(payload)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_json(response)

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
        self.wfile.write(data)

    def send_json(self, payload, status=HTTPStatus.OK):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_cors_headers(self):
        origin = self.headers.get("Origin", "")
        if "*" in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", "*")
            return
        if origin and origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def log_message(self, fmt, *args):
        return
