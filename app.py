from http.server import ThreadingHTTPServer

from core.config import HOST, PORT
from core.config import CHAT_DB_PATH, CHROMA_DIR, DIARY_DIR, MEMORY_DIR, RUNTIME_MEDIA_DIR
from diary.store import ensure_diary_dir
from server.handlers import AppHandler
from server.service import get_emotion_runner
from agent.asr import preload_asr_model
from emotion.media import preload_audio_feature_extractor


def ensure_runtime_dirs() -> None:
    for path in (MEMORY_DIR, DIARY_DIR, CHROMA_DIR, RUNTIME_MEDIA_DIR, CHAT_DB_PATH.parent):
        path.mkdir(parents=True, exist_ok=True)
    ensure_diary_dir()


def main():
    ensure_runtime_dirs()
    print("Preloading emotion, audio, and ASR models...")
    get_emotion_runner()
    preload_audio_feature_extractor()
    preload_asr_model()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    display_host = "127.0.0.1" if HOST in {"0.0.0.0", "::"} else HOST
    print(f"Server running at http://{display_host}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
