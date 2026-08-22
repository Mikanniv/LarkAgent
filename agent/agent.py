import json
import re
import ssl
from typing import Any, Dict, List, Tuple
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from core.config import API_BASE, API_KEY, MODEL

try:
    import certifi
except ImportError:
    certifi = None


def chat_api_ready() -> bool:
    return bool(API_KEY.strip() and MODEL.strip())


def api_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()


def clean_chat_response(content: str) -> str:
    text = (content or "").strip()
    if not text:
        return ""
    text = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.I | re.S).strip()
    text = re.sub(r"<thinking\b[^>]*>.*?</thinking>", "", text, flags=re.I | re.S).strip()
    text = re.sub(r"</?(?:think|thinking)\b[^>]*>", "", text, flags=re.I).strip()
    for marker in ("最终回复：", "最终回复:", "回复：", "回复:", "答案：", "答案:"):
        if marker in text:
            text = text.split(marker)[-1].strip()
    return text.strip("“”\"'`")


def extract_message_text(message: Dict) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return clean_chat_response(content)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and not any(word in str(item.get("type", "")).lower() for word in ("reason", "think")):
                value = item.get("text") or item.get("content") or ""
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
        return clean_chat_response("\n".join(parts))
    return ""


def call_chat_completion(messages: List[Dict[str, Any]], max_tokens: int, temperature: float) -> Tuple[str, str]:
    if not chat_api_ready():
        return "", "api_config_missing"
    payload: Dict[str, Any] = {"model": MODEL, "messages": messages, "max_tokens": max_tokens, "stream": False}
    if MODEL.startswith("kimi-k2.5"):
        payload["thinking"] = {"type": "disabled"}
    else:
        payload["temperature"] = temperature
    request = Request(
        f"{API_BASE.rstrip('/')}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=90, context=api_ssl_context()) as response:
            body = json.loads(response.read().decode("utf-8"))
        choices = body.get("choices") or []
        return extract_message_text((choices[0].get("message") or {}) if choices else {}), ""
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = str(exc)
        return "", detail or str(exc)
    except Exception as exc:
        return "", str(exc)
