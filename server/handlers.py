import hmac
import json
import mimetypes
import os
import socket
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from core.config import ALLOWED_ORIGINS, FACE_TASK_PATH, MAX_AUDIO_BYTES, STATIC_DIR
from diary.store import get_diary_index_payload
from storage.auth_store import (
    LEGACY_SESSION_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    get_session_user,
    login_user,
    register_user,
    revoke_session,
)
from server.service import (
    DEFAULT_MEMORY_USER_ID,
    analyze_and_reply,
    handle_academic_advice_generate,
    handle_academic_profile_query,
    handle_academic_profile_save,
    handle_academic_scores_query,
    handle_academic_score_save,
    handle_chat_history,
    handle_audio_input,
    handle_asr_segment,
    handle_ai_diary_v2_query,
    handle_ai_diary_v2_review,
    handle_diary_user,
    handle_diary_user_delete,
    handle_emotion_trend_query,
    handle_memory_v2_query,
    handle_memory_v2_read,
    handle_profiles_query,
    handle_profile_create,
    handle_profile_switch,
    handle_profile_update,
    handle_profile_delete,
    handle_profile_greeting,
    handle_study_sessions_query,
    handle_study_session_create,
    handle_study_messages_query,
    handle_study_chat,
    handle_study_files_query,
    handle_study_file_upload,
    handle_study_file_delete,
    handle_study_library_query,
    handle_study_library_upload,
    handle_study_library_delete,
    handle_study_library_chunks_query,
    handle_study_session_links_update,
    handle_user_clear,
    stream_main_chat,
    stream_realtime_voice_turn,
    stream_study_chat,
)


INTERNAL_SECRET = (
    os.environ.get("LARK_INTERNAL_SECRET")
    or os.environ.get("YUNQUE_INTERNAL_SECRET")
    or ""
).strip()


class AppHandler(BaseHTTPRequestHandler):
    def is_local_direct_request(self) -> bool:
        client_host = self.client_address[0]
        if client_host not in {"127.0.0.1", "::1"}:
            return False
        if any(
            self.headers.get(name)
            for name in ("CF-Connecting-IP", "Forwarded", "X-Forwarded-For", "X-Real-IP")
        ):
            return False
        host = self.headers.get("Host", "")
        host_name = urlparse(f"//{host}").hostname or ""
        if host_name not in {"127.0.0.1", "localhost", "::1"}:
            return False
        origin = self.headers.get("Origin", "")
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}

    @staticmethod
    def is_allowed_origin(origin: str) -> bool:
        if not origin:
            return False
        if "*" in ALLOWED_ORIGINS or origin in ALLOWED_ORIGINS:
            return True
        parsed = urlparse(origin)
        hostname = parsed.hostname or ""
        if parsed.scheme == "http" and hostname in {"127.0.0.1", "localhost"}:
            return True
        return parsed.scheme == "https" and (
            hostname == "irises.me"
            or hostname.endswith(".irises.me")
        )

    @staticmethod
    def asset_version() -> str:
        candidates = [
            STATIC_DIR / "app.js",
            STATIC_DIR / "companion.js",
            STATIC_DIR / "realtime-voice.js",
            STATIC_DIR / "character.js",
            STATIC_DIR / "styles.css",
            STATIC_DIR / "companion.css",
            STATIC_DIR / "live2d" / "runtime" / "p2l.js",
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
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def _extract_session_token(self) -> str:
        auth_header = (self.headers.get("Authorization") or "").strip()
        if auth_header.lower().startswith("bearer "):
            tok = auth_header[7:].strip()
            if tok:
                return tok
        raw_cookie = self.headers.get("Cookie") or ""
        if raw_cookie:
            cookie = SimpleCookie()
            try:
                cookie.load(raw_cookie)
            except Exception:
                return ""
            if SESSION_COOKIE_NAME in cookie and cookie[SESSION_COOKIE_NAME].value:
                return cookie[SESSION_COOKIE_NAME].value.strip()
            if LEGACY_SESSION_COOKIE_NAME in cookie and cookie[LEGACY_SESSION_COOKIE_NAME].value:
                return cookie[LEGACY_SESSION_COOKIE_NAME].value.strip()
        return ""

    def _is_https_request(self) -> bool:
        proto = (self.headers.get("X-Forwarded-Proto") or "").strip().lower()
        origin = (self.headers.get("Origin") or "").strip().lower()
        return proto == "https" or origin.startswith("https://")

    def _build_session_cookie_header(self, token: str, clear: bool = False) -> str:
        parts = [
            f"{SESSION_COOKIE_NAME}={'deleted' if clear else token}",
            "Path=/",
            "HttpOnly",
            f"Max-Age={0 if clear else SESSION_MAX_AGE_SECONDS}",
        ]
        if self._is_https_request():
            parts.append("SameSite=None")
            parts.append("Secure")
        else:
            parts.append("SameSite=Lax")
        return "; ".join(parts)

    def do_GET(self):
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        if route in {"/", "/index.html"}:
            self.serve_html(STATIC_DIR / "index.html")
            return
        if route == "/api/auth/me":
            token = self._extract_session_token()
            user = get_session_user(token) if token else None
            self.send_json({"ok": True, "user": user})
            return
        if route == "/api/diary":
            user_id = self.api_user_id()
            if user_id is None:
                return
            query = parse_qs(parsed.query)
            requested_date = (query.get("date") or [""])[0]
            self.send_json(get_diary_index_payload(requested_date, user_id=user_id))
            return
        if route == "/api/memory/v2":
            user_id = self.api_user_id()
            if user_id is None:
                return
            query = parse_qs(parsed.query)
            query["_auth_user_id"] = [user_id]
            self.send_json(handle_memory_v2_query(query))
            return
        if route == "/api/emotion/trends":
            user_id = self.api_user_id()
            if user_id is None:
                return
            query = parse_qs(parsed.query)
            query["_auth_user_id"] = [user_id]
            self.send_json(handle_emotion_trend_query(query))
            return
        if route == "/api/ai-diary/v2":
            user_id = self.api_user_id()
            if user_id is None:
                return
            query = parse_qs(parsed.query)
            query["_auth_user_id"] = [user_id]
            self.send_json(handle_ai_diary_v2_query(query))
            return
        if route == "/api/chat/history":
            user_id = self.api_user_id()
            if user_id is None:
                return
            query = parse_qs(parsed.query)
            query["_auth_user_id"] = [user_id]
            self.send_json(handle_chat_history(query))
            return
        if route == "/api/academic/profile":
            user_id = self.api_user_id()
            if user_id is None:
                return
            query = parse_qs(parsed.query)
            query["_auth_user_id"] = [user_id]
            self.send_json(handle_academic_profile_query(query))
            return
        if route == "/api/academic/scores":
            user_id = self.api_user_id()
            if user_id is None:
                return
            query = parse_qs(parsed.query)
            query["_auth_user_id"] = [user_id]
            self.send_json(handle_academic_scores_query(query))
            return
        if route == "/api/profiles":
            user_id = self.api_user_id()
            if user_id is None:
                return
            query = parse_qs(parsed.query)
            query["_auth_user_id"] = [user_id]
            self.send_json(handle_profiles_query(query))
            return
        if route == "/api/study/sessions":
            user_id = self.api_user_id()
            if user_id is None:
                return
            query = parse_qs(parsed.query)
            query["_auth_user_id"] = [user_id]
            self.send_json(handle_study_sessions_query(query))
            return
        if route == "/api/study/messages":
            user_id = self.api_user_id()
            if user_id is None:
                return
            query = parse_qs(parsed.query)
            query["_auth_user_id"] = [user_id]
            self.send_json(handle_study_messages_query(query))
            return
        if route == "/api/study/files":
            user_id = self.api_user_id()
            if user_id is None:
                return
            query = parse_qs(parsed.query)
            query["_auth_user_id"] = [user_id]
            self.send_json(handle_study_files_query(query))
            return
        if route == "/api/study/library":
            user_id = self.api_user_id()
            if user_id is None:
                return
            query = parse_qs(parsed.query)
            query["_auth_user_id"] = [user_id]
            self.send_json(handle_study_library_query(query))
            return
        if route == "/api/study/library/chunks":
            user_id = self.api_user_id()
            if user_id is None:
                return
            query = parse_qs(parsed.query)
            query["_auth_user_id"] = [user_id]
            self.send_json(handle_study_library_chunks_query(query))
            return
        if route == "/face_landmarker.task":
            self.serve_file(FACE_TASK_PATH, allowed_root=FACE_TASK_PATH.parent)
            return
        if route.startswith("/static/"):
            relative = route.replace("/static/", "", 1)
            self.serve_file(STATIC_DIR / relative, allowed_root=STATIC_DIR)
            return
        static_asset = STATIC_DIR / route.lstrip("/")
        if static_asset.exists() and static_asset.is_file():
            self.serve_file(static_asset, allowed_root=STATIC_DIR)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self):
        route = unquote(urlparse(self.path).path)
        if route in {"/api/auth/register", "/api/auth/login", "/api/auth/logout"}:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 64 * 1024:
                self.send_json({"ok": False, "error": "Payload too large"}, status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
            raw = self.rfile.read(length or 0)
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self.send_json({"ok": False, "error": "Invalid JSON payload"}, status=HTTPStatus.BAD_REQUEST)
                return
            if route == "/api/auth/logout":
                tok = self._extract_session_token()
                if tok:
                    revoke_session(tok)
                self.send_json(
                    {"ok": True},
                    extra_headers={"Set-Cookie": self._build_session_cookie_header("", clear=True)},
                )
                return
            try:
                username = str(payload.get("username") or "")
                password = str(payload.get("password") or "")
                if route == "/api/auth/register":
                    user, token = register_user(username, password)
                else:
                    user, token = login_user(username, password)
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self.send_json(
                {"ok": True, "user": user, "token": token},
                extra_headers={"Set-Cookie": self._build_session_cookie_header(token)},
            )
            return

        if route not in {
            "/api/chat",
            "/api/chat/stream",
            "/api/voice/turn/stream",
            "/api/voice/tts",
            "/api/asr/segment",
            "/api/audio/input",
            "/api/diary/user",
            "/api/diary/user/delete",
            "/api/ai-diary/v2/review",
            "/api/memory/v2/read",
            "/api/academic/profile",
            "/api/academic/scores",
            "/api/academic/advice",
            "/api/profiles",
            "/api/profiles/switch",
            "/api/profiles/update",
            "/api/profiles/delete",
            "/api/profiles/greeting",
            "/api/study/sessions",
            "/api/study/chat",
            "/api/study/chat/stream",
            "/api/study/files",
            "/api/study/files/delete",
            "/api/study/library",
            "/api/study/library/delete",
            "/api/study/session/links",
            "/api/user/clear",
        }:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        length = int(self.headers.get("Content-Length", "0"))
        max_request_bytes = max(MAX_AUDIO_BYTES * 2, 40 * 1024 * 1024)
        if length > max_request_bytes:
            self.send_json({"error": "Request payload is too large"}, status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
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
            if route == "/api/chat/stream":
                self.send_sse_stream(stream_main_chat(payload))
                return
            if route == "/api/study/chat/stream":
                self.send_sse_stream(stream_study_chat(payload))
                return
            if route == "/api/voice/turn/stream":
                self.send_sse_stream(stream_realtime_voice_turn(payload))
                return
            if route == "/api/voice/tts":
                import base64
                from agent.realtime_voice import synthesize_sentence_tts

                text = str(payload.get("text") or "").strip()
                voice = str(payload.get("voice") or "").strip()
                audio_bytes, mime, provider = synthesize_sentence_tts(text, voice=voice)
                self.send_json({
                    "ok": True,
                    "tts_provider": provider,
                    "mime": mime,
                    "audio_b64": base64.b64encode(audio_bytes).decode("ascii") if audio_bytes else "",
                })
                return
            if route == "/api/chat":
                response = analyze_and_reply(payload, should_reply=True)
            elif route == "/api/asr/segment":
                response = handle_asr_segment(payload)
            elif route == "/api/audio/input":
                response = handle_audio_input(payload)
            elif route == "/api/diary/user":
                response = handle_diary_user(payload)
            elif route == "/api/diary/user/delete":
                response = handle_diary_user_delete(payload)
            elif route == "/api/ai-diary/v2/review":
                response = handle_ai_diary_v2_review(payload)
            elif route == "/api/memory/v2/read":
                response = handle_memory_v2_read(payload)
            elif route == "/api/academic/profile":
                response = handle_academic_profile_save(payload)
            elif route == "/api/academic/scores":
                response = handle_academic_score_save(payload)
            elif route == "/api/academic/advice":
                response = handle_academic_advice_generate(payload)
            elif route == "/api/profiles":
                response = handle_profile_create(payload)
            elif route == "/api/profiles/switch":
                response = handle_profile_switch(payload)
            elif route == "/api/profiles/update":
                response = handle_profile_update(payload)
            elif route == "/api/profiles/delete":
                response = handle_profile_delete(payload)
            elif route == "/api/profiles/greeting":
                response = handle_profile_greeting(payload)
            elif route == "/api/study/sessions":
                response = handle_study_session_create(payload)
            elif route == "/api/study/chat":
                response = handle_study_chat(payload)
            elif route == "/api/study/files":
                response = handle_study_file_upload(payload)
            elif route == "/api/study/files/delete":
                response = handle_study_file_delete(payload)
            elif route == "/api/study/library":
                response = handle_study_library_upload(payload)
            elif route == "/api/study/library/delete":
                response = handle_study_library_delete(payload)
            elif route == "/api/study/session/links":
                response = handle_study_session_links_update(payload)
            else:
                response = handle_user_clear(payload)
        except Exception as exc:
            status = HTTPStatus.BAD_REQUEST if isinstance(exc, ValueError) else HTTPStatus.INTERNAL_SERVER_ERROR
            self.send_json({"error": str(exc)}, status=status)
            return
        self.send_json(response)

    def send_sse_stream(self, event_iter):
        self.send_response(HTTPStatus.OK)
        self.send_cors_headers()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for item in event_iter:
                line = f"data: {json.dumps(item, ensure_ascii=False)}\n\n".encode("utf-8")
                self.wfile.write(line)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            err_line = f"data: {json.dumps({'type': 'error', 'error': str(exc)}, ensure_ascii=False)}\n\n".encode("utf-8")
            try:
                self.wfile.write(err_line)
                self.wfile.flush()
            except Exception:
                pass

    def api_user_id(self) -> str | None:
        # 1. 优先校验后端原生会话（Cookie: lark_session 或 Authorization: Bearer）
        token = self._extract_session_token()
        if token:
            session_user = get_session_user(token)
            if session_user:
                return session_user["id"]

        # 2. 兼容经受信任内部网关（如 Worker）带密钥转发的请求
        if INTERNAL_SECRET:
            received = (
                self.headers.get("X-Lark-Internal-Secret")
                or self.headers.get("X-Yunque-Internal-Secret")
                or ""
            ).strip()
            if received and hmac.compare_digest(received, INTERNAL_SECRET):
                forwarded_uid = (
                    self.headers.get("X-Lark-User-Id")
                    or self.headers.get("X-Yunque-User-Id")
                    or ""
                ).strip()
                if forwarded_uid:
                    return forwarded_uid
                self.send_json({"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
                return None

        # 3. 本机直连开发模式：严格锁定为 DEFAULT_MEMORY_USER_ID，不信任客户端伪造头
        if self.is_local_direct_request():
            return DEFAULT_MEMORY_USER_ID

        self.send_json({"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        return None

    def serve_file(self, path: Path, allowed_root: Path | None = None):
        try:
            resolved = path.resolve()
            root = (allowed_root or STATIC_DIR).resolve()
            if not resolved.is_relative_to(root):
                self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
                return
        except Exception:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid path")
            return
        if not resolved.exists() or not resolved.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        mime_type, _ = mimetypes.guess_type(resolved.name)
        data = resolved.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_cors_headers()
        self.send_header("Content-Type", mime_type or "application/octet-stream")
        if resolved.suffix in {".js", ".css", ".html"}:
            self.send_header("Cache-Control", "no-cache")
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

    def send_json(self, payload, status=HTTPStatus.OK, extra_headers=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.safe_write(data)

    def send_cors_headers(self):
        origin = self.headers.get("Origin", "")
        if "*" in ALLOWED_ORIGINS and not origin:
            self.send_header("Access-Control-Allow-Origin", "*")
            return
        if self.is_allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")

    def log_message(self, fmt, *args):
        return
