import json
import re
import shutil
from typing import Dict, List, Tuple
from urllib.request import Request, urlopen

from core.config import OLLAMA_API_BASE, OLLAMA_MODEL


def ollama_ready() -> bool:
    return bool(shutil.which("ollama"))


def strip_think_blocks(content: str) -> str:
    text = (content or "").strip()
    if not text:
        return ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if paragraphs and ("关键点：" in text or "首先，用户" in text or "最终回复" in text):
        text = paragraphs[-1]
    if text.startswith("```") and text.endswith("```"):
        text = text.strip("`").strip()
    return text


def call_ollama_chat(messages: List[Dict[str, str]], max_tokens: int, temperature: float) -> Tuple[str, str]:
    if not ollama_ready():
        return "", "ollama_missing"

    endpoint = f"{OLLAMA_API_BASE.rstrip('/')}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = strip_think_blocks((body.get("message") or {}).get("content") or "")
        return content, ""
    except Exception as exc:
        return "", str(exc)

