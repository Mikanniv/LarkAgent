import threading
from http.server import ThreadingHTTPServer

from core.config import HOST, PORT
from core.config import CHAT_DB_PATH, CHROMA_DIR, DIARY_DIR, MEMORY_DIR, RUNTIME_MEDIA_DIR
from diary.store import ensure_diary_dir
from server.handlers import AppHandler
from server.service import ai_diary_worker, get_emotion_runner


def ensure_runtime_dirs() -> None:
    for path in (MEMORY_DIR, DIARY_DIR, CHROMA_DIR, RUNTIME_MEDIA_DIR, CHAT_DB_PATH.parent):
        path.mkdir(parents=True, exist_ok=True)
    ensure_diary_dir()


def main():
    ensure_runtime_dirs()
    get_emotion_runner()
    worker = threading.Thread(target=ai_diary_worker, daemon=True)
    worker.start()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    display_host = "127.0.0.1" if HOST in {"0.0.0.0", "::"} else HOST
    print(f"Server running at http://{display_host}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
