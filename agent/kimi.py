import json
import re
from typing import Dict, List, Tuple
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from core.config import KIMI_API_BASE, KIMI_API_KEY, KIMI_MODEL


def kimi_ready() -> bool:
    return bool(KIMI_API_KEY.strip() and KIMI_MODEL.strip())


def clean_kimi_response(content: str) -> str:
    text = (content or "").strip()
    if not text:
        return ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL).strip()
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()
    if "</thinking>" in text:
        text = text.split("</thinking>")[-1].strip()
    text = re.sub(r"^(思考过程|分析过程|推理过程)[：:]\s*", "", text).strip()
    final_markers = ["最终回复：", "最终回复:", "回复：", "回复:", "答复：", "答复:"]
    for marker in final_markers:
        if marker in text:
            text = text.split(marker)[-1].strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.strip("`").strip()
    text = re.sub(r"^(最终回复|回复)[：:]\s*", "", text).strip()
    return text.strip("“”\"'`")


def extract_message_text(message: Dict) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return clean_kimi_response(content)
    if isinstance(content, list):
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").lower()
            if "reason" in item_type or "think" in item_type:
                continue
            text = item.get("text") or item.get("content") or ""
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return clean_kimi_response("\n".join(parts))
    reasoning = message.get("reasoning_content") or message.get("reasoning")
    if isinstance(reasoning, str) and reasoning.strip():
        return ""
    return clean_kimi_response(str(content or ""))


def call_kimi_chat(messages: List[Dict[str, str]], max_tokens: int, temperature: float) -> Tuple[str, str]:
    if not kimi_ready():
        return "", "kimi_api_missing"
    endpoint = f"{KIMI_API_BASE.rstrip('/')}/chat/completions"
    payload = {
        "model": KIMI_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if KIMI_MODEL.startswith("kimi-k2.5"):
        payload["thinking"] = {"type": "disabled"}
    else:
        payload["temperature"] = temperature
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {KIMI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
        choices = body.get("choices") or []
        message = (choices[0].get("message") or {}) if choices else {}
        return extract_message_text(message), ""
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = str(exc)
        return "", detail or str(exc)
    except Exception as exc:
        return "", str(exc)
