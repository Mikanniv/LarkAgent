import json
import re
import ssl
from typing import Any, Dict, Iterator, List, Tuple
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
    payload: Dict[str, Any] = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
        "temperature": temperature,
    }
    # 关闭 thinking 思考过程（兼容 Qwen3 / DeepSeek / Kimi 等模型与平台）
    payload["enable_thinking"] = False
    payload["thinking"] = {"type": "disabled"}

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


def call_chat_completion_with_tools(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    max_tokens: int,
    temperature: float,
    tool_choice: str = "auto",
) -> Tuple[str, List[Dict[str, Any]], str]:
    if not chat_api_ready():
        return "", [], "api_config_missing"
    if not tools:
        text, err = call_chat_completion(messages, max_tokens=max_tokens, temperature=temperature)
        return text, [], err

    payload: Dict[str, Any] = {
        "model": MODEL,
        "messages": messages,
        "tools": tools,
        "tool_choice": tool_choice,
        "max_tokens": max_tokens,
        "stream": False,
        "temperature": temperature,
        "enable_thinking": False,
        "thinking": {"type": "disabled"},
    }
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
        message = (choices[0].get("message") or {}) if choices else {}
        tool_calls = message.get("tool_calls") or []
        text = extract_message_text(message)
        return text, tool_calls if isinstance(tool_calls, list) else [], ""
    except HTTPError:
        # 平台或模型不支持 tools 时优雅降级为普通对话
        text, err = call_chat_completion(messages, max_tokens=max_tokens, temperature=temperature)
        return text, [], err
    except Exception as exc:
        return "", [], str(exc)


def stream_chat_completion(
    messages: List[Dict[str, Any]],
    max_tokens: int,
    temperature: float,
) -> Iterator[str]:
    """流式调用 OpenAI 兼容 /chat/completions，过滤 <think> 思考过程并逐段产出文本。"""
    if not chat_api_ready():
        return

    payload: Dict[str, Any] = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
        "temperature": temperature,
        "enable_thinking": False,
        "thinking": {"type": "disabled"},
    }
    request = Request(
        f"{API_BASE.rstrip('/')}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    in_think = False
    pending = ""
    with urlopen(request, timeout=120, context=api_ssl_context()) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line or not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if not isinstance(piece, str) or not piece:
                continue

            pending += piece
            while pending:
                if in_think:
                    end_match = re.search(r"</(?:think|thinking)>", pending, flags=re.I)
                    if not end_match:
                        if len(pending) > 32:
                            pending = pending[-16:]
                        break
                    pending = pending[end_match.end():]
                    in_think = False
                else:
                    start_match = re.search(r"<(?:think|thinking)\b[^>]*>", pending, flags=re.I)
                    if start_match:
                        before = pending[:start_match.start()]
                        if before:
                            yield before
                        pending = pending[start_match.end():]
                        in_think = True
                    else:
                        # 保留可能是不完整标签的末尾 '<...'
                        last_lt = pending.rfind("<")
                        if last_lt != -1 and len(pending) - last_lt <= 14:
                            safe_out = pending[:last_lt]
                            if safe_out:
                                yield safe_out
                            pending = pending[last_lt:]
                            break
                        yield pending
                        pending = ""
    if pending and not in_think:
        yield pending
