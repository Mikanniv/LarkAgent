from __future__ import annotations

import asyncio
import json
import os
import re
import ssl
import tempfile
import uuid
from pathlib import Path
from typing import List, Tuple
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from core.config import (
    LARK_ASR_API_BASE,
    LARK_ASR_API_KEY,
    LARK_ASR_MODEL,
    LARK_ASR_PROVIDER,
    LARK_TTS_API_BASE,
    LARK_TTS_API_KEY,
    LARK_TTS_FORMAT,
    LARK_TTS_MODEL,
    LARK_TTS_PROVIDER,
    LARK_TTS_VOICE,
)

EDGE_TTS_VOICES = {
    "zh-CN-XiaoyiNeural",
    "zh-CN-XiaoxiaoNeural",
}

try:
    import certifi  # type: ignore

    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()


def clean_text_for_speech(text: str) -> str:
    """移除 Markdown / 代码块 / 引用编号 / 表情符号，保留自然口语文本用于 TTS 播报。"""
    s = str(text or "")
    s = re.sub(r"```[\s\S]*?```", " ", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\[S\d+\]", "", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"[#*_~>|]+", " ", s)
    # 过滤掉纯表情符号与不可朗读符号，避免 edge-tts 返回 NoAudioReceived
    s = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\ufe0f]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", s):
        return ""
    return s


def split_spoken_sentences(buffer: str, *, flush: bool = False, min_chars: int = 8) -> Tuple[List[str], str]:
    """将流式 LLM 文本增量化切分为适合实时 TTS 播放的自然短句。"""
    if not buffer:
        return [], ""
    sentences: List[str] = []
    rest = buffer
    pattern = re.compile(r"([。！？!?；;\n]+)")
    while True:
        match = pattern.search(rest)
        if not match:
            break
        end_pos = match.end()
        candidate = rest[:end_pos].strip()
        if len(clean_text_for_speech(candidate)) < min_chars and not flush:
            # 太短的片段合并到下一句，避免 TTS 碎片化
            next_match = pattern.search(rest, end_pos)
            if not next_match:
                break
            end_pos = next_match.end()
            candidate = rest[:end_pos].strip()
        cleaned = clean_text_for_speech(candidate)
        if cleaned:
            sentences.append(cleaned)
        rest = rest[end_pos:]
    if flush and rest.strip():
        cleaned = clean_text_for_speech(rest)
        if cleaned:
            sentences.append(cleaned)
        rest = ""
    return sentences, rest


def _should_use_cloud_asr() -> bool:
    if LARK_ASR_PROVIDER == "local_funasr":
        return False
    if LARK_ASR_PROVIDER == "openai_compat":
        return bool(LARK_ASR_API_BASE and LARK_ASR_API_KEY)
    return bool(LARK_ASR_API_BASE and LARK_ASR_API_KEY)


def _should_use_cloud_tts() -> bool:
    if LARK_TTS_PROVIDER == "browser":
        return False
    if LARK_TTS_PROVIDER == "openai_compat":
        return bool(LARK_TTS_API_BASE and LARK_TTS_API_KEY)
    return bool(LARK_TTS_API_BASE and LARK_TTS_API_KEY)


def _encode_multipart_form(
    fields: dict[str, str],
    file_field: str,
    filename: str,
    file_bytes: bytes,
    content_type: str,
) -> Tuple[bytes, str]:
    boundary = f"----LarkVoiceBoundary{uuid.uuid4().hex}"
    chunks: List[bytes] = []
    for k, v in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("utf-8"))
        chunks.append(f"{v}\r\n".encode("utf-8"))
    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode("utf-8")
    )
    chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
    chunks.append(file_bytes)
    chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _transcribe_openai_compat(audio_bytes: bytes, mime_type: str, filename: str) -> Tuple[str, str]:
    url = f"{LARK_ASR_API_BASE}/audio/transcriptions"
    body, content_type = _encode_multipart_form(
        fields={"model": LARK_ASR_MODEL, "language": "zh", "response_format": "json"},
        file_field="file",
        filename=filename or "voice.webm",
        file_bytes=audio_bytes,
        content_type=mime_type or "audio/webm",
    )
    req = Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {LARK_ASR_API_KEY}",
            "Content-Type": content_type,
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=25, context=_SSL_CTX) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw or "{}")
        return str(data.get("text") or "").strip(), ""
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        return "", f"ASR HTTP {exc.code}: {detail}"
    except Exception as exc:
        return "", str(exc)


def transcribe_voice_audio(
    audio_bytes: bytes,
    *,
    mime_type: str = "audio/webm",
    filename: str = "voice.webm",
) -> Tuple[str, str, str]:
    """返回 (transcript, provider, error)。"""
    if not audio_bytes:
        return "", "none", "音频为空"

    if _should_use_cloud_asr():
        text, err = _transcribe_openai_compat(audio_bytes, mime_type, filename)
        if text or not err:
            return text, "openai_compat", err
        # 云端失败时尝试本地兜底
        cloud_err = err
    else:
        cloud_err = ""

    # 本地 FunASR 兜底
    ext = os.path.splitext(filename or "")[1] or ".webm"
    tmp_path = None
    try:
        from agent.asr import transcribe_audio

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
            tf.write(audio_bytes)
            tmp_path = Path(tf.name)
        text = transcribe_audio(tmp_path)
        return (text or "").strip(), "local_funasr", ""
    except Exception as exc:
        return "", "none", cloud_err or f"本地 ASR 不可用: {exc}"
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


def _synthesize_edge_tts(text: str, voice: str) -> bytes | None:
    try:
        import edge_tts  # type: ignore
    except Exception:
        return None

    chosen = voice if voice in EDGE_TTS_VOICES else (
        LARK_TTS_VOICE if LARK_TTS_VOICE in EDGE_TTS_VOICES else "zh-CN-XiaoyiNeural"
    )

    async def _run() -> bytes:
        comm = edge_tts.Communicate(text=text, voice=chosen)
        parts: List[bytes] = []
        async for chunk in comm.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                parts.append(chunk["data"])
        return b"".join(parts)

    import time as _time

    last_err = None
    for attempt in range(3):
        try:
            loop = asyncio.new_event_loop()
            try:
                data = loop.run_until_complete(asyncio.wait_for(_run(), timeout=20.0))
            finally:
                loop.close()
            if data:
                return data
        except Exception as exc:
            last_err = exc
            if attempt < 2:
                _time.sleep(0.35 * (attempt + 1))
    if last_err is not None:
        print(f"[edge-tts warn] voice={chosen} failed after 3 attempts: {last_err}")
    return None


def synthesize_sentence_tts(text: str, *, voice: str = "") -> Tuple[bytes | None, str, str]:
    """返回 (audio_bytes_or_none, mime_type, provider)。"""
    spoken = clean_text_for_speech(text)
    if not spoken:
        return None, "", "none"

    if LARK_TTS_PROVIDER == "browser":
        return None, "", "browser"

    if _should_use_cloud_tts():
        url = f"{LARK_TTS_API_BASE}/audio/speech"
        fmt = LARK_TTS_FORMAT if LARK_TTS_FORMAT in {"mp3", "wav", "opus", "aac", "flac"} else "mp3"
        mime_map = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "opus": "audio/ogg",
            "aac": "audio/aac",
            "flac": "audio/flac",
        }
        payload = json.dumps(
            {
                "model": LARK_TTS_MODEL,
                "voice": voice or LARK_TTS_VOICE,
                "input": spoken,
                "response_format": fmt,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {LARK_TTS_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=25, context=_SSL_CTX) as resp:
                audio_data = resp.read()
            if audio_data:
                return audio_data, mime_map.get(fmt, "audio/mpeg"), "openai_compat"
        except Exception:
            pass

    if LARK_TTS_PROVIDER in {"auto", "edge"}:
        edge_audio = _synthesize_edge_tts(spoken, voice)
        if edge_audio:
            return edge_audio, "audio/mpeg", "edge_tts"

    return None, "", "browser"
