import ctypes.util
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def project_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else ROOT / candidate


def configure_python_runtime_paths() -> None:
    python_bin_dir = Path(sys.executable).resolve().parent
    python_env_dir = python_bin_dir if (python_bin_dir / "Library" / "bin").exists() else python_bin_dir.parent
    library_bin = python_env_dir / "Library" / "bin"
    path_parts = [str(p) for p in (python_bin_dir, library_bin) if p.exists()]
    if path_parts:
        os.environ["PATH"] = os.pathsep.join(path_parts + [os.environ.get("PATH", "")])
    if library_bin.exists() and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(library_bin))
    sndfile_dll = library_bin / "sndfile.dll"
    if sndfile_dll.exists():
        original_find_library = ctypes.util.find_library

        def find_library_with_conda_env(name: str) -> str | None:
            if name == "sndfile":
                return str(sndfile_dll)
            return original_find_library(name)

        ctypes.util.find_library = find_library_with_conda_env


def load_env_file(path: Path) -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(path)
        return
    except ImportError:
        pass
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


configure_python_runtime_paths()
load_env_file(ROOT / ".env")

STATIC_DIR = ROOT / "static"
SELF_MM_MODEL_PATH = project_path(os.getenv("SELF_MM_MODEL_PATH", "models/self_mm_mediapipe_best.pth"))
BERT_MODEL_PATH = project_path(os.getenv("BERT_MODEL_PATH", "models/bert-base-chinese"))
FACE_TASK_PATH = project_path(os.getenv("FACE_TASK_PATH", "face_landmarker.task"))
RUNTIME_MEDIA_DIR = project_path(os.getenv("RUNTIME_MEDIA_DIR", ".cache/runtime_media"))
MEMORY_DIR = project_path(os.getenv("MEMORY_DIR", "memories"))
DIARY_DIR = project_path(os.getenv("DIARY_DIR", str(MEMORY_DIR / "diaries")))
CHROMA_DIR = project_path(os.getenv("CHROMA_DIR", str(MEMORY_DIR / "chroma")))
CHAT_DB_PATH = project_path(os.getenv("CHAT_DB_PATH", str(MEMORY_DIR / "chat.sqlite3")))
CHAT_CONTEXT_LIMIT = int(os.getenv("CHAT_CONTEXT_LIMIT", "6"))
CHAT_DISPLAY_LIMIT = int(os.getenv("CHAT_DISPLAY_LIMIT", "20"))
DAILY_MEMORY_DECAY_THRESHOLD = float(os.getenv("DAILY_MEMORY_DECAY_THRESHOLD", "0.05"))

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8001"))
AI_DIARY_UPDATE_INTERVAL = int(os.getenv("AI_DIARY_UPDATE_INTERVAL", "180"))
ALLOWED_ORIGINS = [
    item.strip()
    for item in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8001,http://localhost:8001").split(",")
    if item.strip()
]
API_KEY = (os.getenv("SILICON_FLOW_API_KEY") or os.getenv("API_KEY") or "").strip()
MODEL = (os.getenv("MODEL") or "Qwen/Qwen3-8B").strip()
API_BASE = (os.getenv("SILICON_FLOW_BASE_URL") or os.getenv("API_BASE") or "https://api.siliconflow.cn/v1").strip().rstrip("/")
ENABLE_MULTIMODAL = os.getenv("ENABLE_MULTIMODAL", "0").strip().lower() in {"1", "true", "yes", "on"}
API_IMAGE_INPUT = os.getenv("API_IMAGE_INPUT", "0" if not ENABLE_MULTIMODAL else "1").strip().lower() in {"1", "true", "yes", "on"}
API_AUDIO_INPUT = os.getenv("API_AUDIO_INPUT", "0").strip().lower() in {"1", "true", "yes", "on"}

FUNASR_MODEL = os.getenv(
    "FUNASR_MODEL",
    "paraformer-zh",
).strip()
FUNASR_DEVICE = os.getenv("FUNASR_DEVICE", "cpu").strip() or "cpu"
FUNASR_MODEL_REVISION = os.getenv("FUNASR_MODEL_REVISION", "").strip()
FUNASR_VAD_MODEL = os.getenv("FUNASR_VAD_MODEL", "fsmn-vad").strip() or "fsmn-vad"
FUNASR_PUNC_MODEL = os.getenv("FUNASR_PUNC_MODEL", "ct-punc").strip() or "ct-punc"
MAX_AUDIO_BYTES = int(os.getenv("MAX_AUDIO_BYTES", str(12 * 1024 * 1024)))

R2_ENABLED = os.getenv("R2_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
R2_BUCKET = os.getenv("R2_BUCKET", "").strip()
R2_ENDPOINT = os.getenv("R2_ENDPOINT", "").strip()
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
R2_REGION = os.getenv("R2_REGION", "auto").strip() or "auto"
R2_PREFIX = os.getenv("R2_PREFIX", "diaries").strip().strip("/")

# === Realtime Voice Call (Route 1: Cascaded ASR -> Stream LLM -> Stream TTS) ===
# ASR providers: "auto" | "openai_compat" (SiliconFlow SenseVoiceSmall / Groq Whisper / OpenAI) | "local_funasr"
LARK_ASR_PROVIDER = os.getenv("LARK_ASR_PROVIDER", "auto").strip().lower()
LARK_ASR_API_BASE = (os.getenv("LARK_ASR_API_BASE") or (API_BASE if API_KEY else "")).strip().rstrip("/")
LARK_ASR_API_KEY = (os.getenv("LARK_ASR_API_KEY") or API_KEY or "").strip()
LARK_ASR_MODEL = os.getenv(
    "LARK_ASR_MODEL",
    "FunAudioLLM/SenseVoiceSmall" if "siliconflow" in LARK_ASR_API_BASE.lower() else "whisper-large-v3-turbo",
).strip()

# TTS providers: "auto" (cloud API -> edge-tts -> browser) | "edge" | "openai_compat" | "browser"
LARK_TTS_PROVIDER = os.getenv("LARK_TTS_PROVIDER", "auto").strip().lower()
LARK_TTS_API_BASE = (os.getenv("LARK_TTS_API_BASE") or "").strip().rstrip("/")
LARK_TTS_API_KEY = (os.getenv("LARK_TTS_API_KEY") or "").strip()
LARK_TTS_MODEL = os.getenv("LARK_TTS_MODEL", "gpt-4o-mini-tts").strip()
LARK_TTS_VOICE = os.getenv("LARK_TTS_VOICE", "zh-CN-XiaoyiNeural").strip()
LARK_TTS_FORMAT = os.getenv("LARK_TTS_FORMAT", "mp3").strip().lower() or "mp3"
