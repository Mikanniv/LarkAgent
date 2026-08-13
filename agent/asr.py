from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict

import imageio_ffmpeg

from core.config import FUNASR_DEVICE, FUNASR_MODEL, FUNASR_MODEL_REVISION, RUNTIME_MEDIA_DIR


_MODEL: Any = None
_MODEL_LOCK = threading.RLock()


def _get_model() -> Any:
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        try:
            from funasr import AutoModel
        except ImportError as exc:
            raise RuntimeError(
                "FunASR 尚未安装，请在后端环境中执行 pip install funasr modelscope。"
            ) from exc
        kwargs: Dict[str, Any] = {
            "model": FUNASR_MODEL,
            "vad_model": "fsmn-vad",
            "punc_model": "ct-punc",
            "device": FUNASR_DEVICE,
            "disable_update": True,
        }
        if FUNASR_MODEL_REVISION:
            kwargs["model_revision"] = FUNASR_MODEL_REVISION
        _MODEL = AutoModel(**kwargs)
        return _MODEL


def _to_wav_16k(audio_path: Path) -> Path:
    RUNTIME_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    output = RUNTIME_MEDIA_DIR / f"{audio_path.stem}_16k.wav"
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-y",
        "-i",
        str(audio_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(output),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=45)
    if completed.returncode != 0 or not output.exists():
        detail = (completed.stderr or "音频转换失败").strip().splitlines()[-1]
        raise RuntimeError(f"无法将录音转换为 16 kHz WAV：{detail}")
    return output


def _clean_transcript(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"<\|[^|]+\|>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def transcribe_audio(audio_path: Path) -> Dict[str, Any]:
    wav_path = _to_wav_16k(audio_path)
    try:
        result = _get_model().generate(
            input=str(wav_path),
            cache={},
            language="zh",
            use_itn=True,
            batch_size_s=60,
        )
        first = result[0] if isinstance(result, list) and result else result
        text = _clean_transcript(first.get("text") if isinstance(first, dict) else first)
        if not text:
            raise RuntimeError("Paraformer 未识别出有效文本。")
        return {
            "text": text,
            "model": f"{FUNASR_MODEL}+fsmn-vad+ct-punc",
            "language": "zh",
            "wav_path": str(wav_path),
        }
    finally:
        wav_path.unlink(missing_ok=True)
