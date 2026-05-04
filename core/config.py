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

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8001"))
AI_DIARY_UPDATE_INTERVAL = int(os.getenv("AI_DIARY_UPDATE_INTERVAL", "180"))
ALLOWED_ORIGINS = [
    item.strip()
    for item in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8001,http://localhost:8001").split(",")
    if item.strip()
]
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
OLLAMA_API_BASE = os.getenv("OLLAMA_API_BASE", "http://127.0.0.1:11434")

