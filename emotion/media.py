import base64
import mimetypes
import tempfile
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import torch

from core.config import ENABLE_MULTIMODAL, FACE_TASK_PATH, RUNTIME_MEDIA_DIR, project_path
from emotion_model.train_self_mm_mediapipe import (
    AUDIO_DIM,
    AUDIO_SEQ_LEN,
    VIDEO_DIM,
    VIDEO_FEATURE_ORDER,
    VIDEO_SEQ_LEN,
    extract_audio_feature,
    extract_video_feature,
    prepare_face_task,
)

AUDIO_FEATURE_ORDER = ["logF0"] + [f"mfcc_{index:02d}" for index in range(1, 21)] + [
    f"cqt_{index:02d}" for index in range(1, 13)
]


def first_non_empty_text(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def resolve_text_input(payload: Dict) -> Tuple[str, str]:
    audio = payload.get("audio", {}) or {}
    typed_text = first_non_empty_text(payload.get("message"), payload.get("text"))
    speech_text = first_non_empty_text(
        payload.get("speech_text"),
        payload.get("speechText"),
        payload.get("transcript"),
        payload.get("asr_text"),
        audio.get("speech_text") if isinstance(audio, dict) else "",
        audio.get("speechText") if isinstance(audio, dict) else "",
        audio.get("transcript") if isinstance(audio, dict) else "",
        audio.get("text") if isinstance(audio, dict) else "",
    )
    if typed_text:
        return typed_text, "typed"
    if speech_text:
        return speech_text, "speech"
    return "", "empty"


def decode_base64_media(value: object) -> tuple[bytes | None, str]:
    if isinstance(value, dict):
        value = value.get("data") or value.get("base64") or value.get("content")
    if not isinstance(value, str) or not value.strip():
        return None, ""
    raw = value.strip()
    suffix = ""
    if raw.startswith("data:"):
        header, _, raw = raw.partition(",")
        mime = header[5:].split(";", 1)[0]
        suffix = mimetypes.guess_extension(mime) or ""
    try:
        return base64.b64decode(raw), suffix
    except Exception:
        return None, suffix


def resolve_payload_media_path(payload: Dict, modality: str) -> tuple[Path | None, bool]:
    nested = payload.get(modality, {}) or {}
    media = payload.get("media", {}) or {}
    path_values = [
        payload.get(f"{modality}_path"),
        payload.get(f"{modality}Path"),
        nested.get("path") if isinstance(nested, dict) else None,
        media.get(f"{modality}_path") if isinstance(media, dict) else None,
        media.get(f"{modality}Path") if isinstance(media, dict) else None,
    ]
    for value in path_values:
        if isinstance(value, str) and value.strip():
            path = project_path(value.strip())
            if path.exists():
                return path, False

    data_values = [
        payload.get(f"{modality}_data"),
        payload.get(f"{modality}Data"),
        payload.get(f"{modality}_base64"),
        payload.get(f"{modality}Base64"),
        nested.get("data") if isinstance(nested, dict) else None,
        nested.get("base64") if isinstance(nested, dict) else None,
        media.get(modality) if isinstance(media, dict) else None,
    ]
    for value in data_values:
        data, suffix = decode_base64_media(value)
        if data:
            RUNTIME_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
            default_suffix = ".wav" if modality == "audio" else ".webm"
            with tempfile.NamedTemporaryFile(
                prefix=f"{modality}_",
                suffix=suffix or default_suffix,
                dir=RUNTIME_MEDIA_DIR,
                delete=False,
            ) as handle:
                handle.write(data)
                return Path(handle.name), True
    return None, False


def zero_feature_tensor(seq_len: int, dim: int) -> torch.Tensor:
    return torch.zeros((1, seq_len, dim), dtype=torch.float32)


def tensor_from_feature(feature: np.ndarray, seq_len: int, dim: int) -> torch.Tensor:
    arr = np.asarray(feature, dtype=np.float32)
    if arr.shape != (seq_len, dim):
        arr = np.zeros((seq_len, dim), dtype=np.float32)
    return torch.from_numpy(arr).unsqueeze(0)


def build_audio_tensor_from_media(media_path: Path | None) -> tuple[torch.Tensor, Dict[str, object]]:
    if media_path is None:
        return zero_feature_tensor(AUDIO_SEQ_LEN, AUDIO_DIM), {"available": False}
    try:
        return tensor_from_feature(extract_audio_feature(media_path), AUDIO_SEQ_LEN, AUDIO_DIM), {
            "available": True,
            "source": str(media_path),
            "extractor": "LibROSA",
            "feature_dim": AUDIO_DIM,
            "seq_len": AUDIO_SEQ_LEN,
        }
    except Exception as exc:
        return zero_feature_tensor(AUDIO_SEQ_LEN, AUDIO_DIM), {
            "available": False,
            "source": str(media_path),
            "error": f"{type(exc).__name__}: {exc}",
        }


def build_video_tensor_from_media(video_path: Path | None) -> tuple[torch.Tensor, Dict[str, object]]:
    if video_path is None:
        return zero_feature_tensor(VIDEO_SEQ_LEN, VIDEO_DIM), {"available": False}
    try:
        face_task = prepare_face_task(FACE_TASK_PATH)
        return tensor_from_feature(extract_video_feature(video_path, face_task), VIDEO_SEQ_LEN, VIDEO_DIM), {
            "available": True,
            "source": str(video_path),
            "extractor": "MediaPipe FaceLandmarker",
            "feature_dim": VIDEO_DIM,
            "seq_len": VIDEO_SEQ_LEN,
            "feature_order": list(VIDEO_FEATURE_ORDER),
        }
    except Exception as exc:
        return zero_feature_tensor(VIDEO_SEQ_LEN, VIDEO_DIM), {
            "available": False,
            "source": str(video_path),
            "error": f"{type(exc).__name__}: {exc}",
        }


def summarize_video_tensor(video_tensor: torch.Tensor) -> Dict[str, float]:
    arr = video_tensor.detach().cpu().numpy()[0]
    values = arr.mean(axis=0) if arr.size else np.zeros((VIDEO_DIM,), dtype=np.float32)
    return {name: float(values[index]) for index, name in enumerate(VIDEO_FEATURE_ORDER)}


def summarize_audio_tensor(audio_tensor: torch.Tensor) -> Dict[str, float]:
    arr = audio_tensor.detach().cpu().numpy()[0]
    values = arr.mean(axis=0) if arr.size else np.zeros((AUDIO_DIM,), dtype=np.float32)
    return {name: float(values[index]) for index, name in enumerate(AUDIO_FEATURE_ORDER)}


def preload_audio_feature_extractor() -> Dict[str, object]:
    """Import and exercise LibROSA's inexpensive primitives at startup."""
    if not ENABLE_MULTIMODAL:
        return {"ready": False, "extractor": "disabled", "sample_rate": 16000}
    import librosa

    sample = np.zeros(1600, dtype=np.float32)
    librosa.feature.mfcc(y=sample, sr=16000, n_mfcc=1, n_fft=400, hop_length=160)
    return {"ready": True, "extractor": "LibROSA", "sample_rate": 16000}
