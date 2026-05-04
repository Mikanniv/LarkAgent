import json
import os
from typing import Dict, List
from urllib.request import Request, urlopen
from llm.prompt import build_ai_diary_prompt, build_reply_prompt
from memory import schema


OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
OLLAMA_API_BASE = os.getenv("OLLAMA_API_BASE", "http://127.0.0.1:11434")


def call_ollama(messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
    endpoint = f"{OLLAMA_API_BASE.rstrip('/')}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": temperature},
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=90) as response:
        body = json.loads(response.read().decode("utf-8"))
    return ((body.get("message") or {}).get("content") or "").strip()


def normalize_recall_results(results: Dict) -> List[Dict]:
    documents = (results.get("documents") or [[]])[0]
    metadatas = (results.get("metadatas") or [[]])[0]
    distances = (results.get("distances") or [[]])[0]
    normalized = []
    for index, document in enumerate(documents):
        metadata = metadatas[index] if index < len(metadatas) else {}
        item = {
            "document": document,
            "metadata": metadata or {},
        }
        if index < len(distances):
            item["distance"] = distances[index]
        normalized.append(item)
    return normalized

def detect_emotion(user_input: str) -> Dict[str, float]:
    normalized = (user_input or "").strip()
    if not normalized:
        return {"valence": 0.0, "arousal": 0.2}
    negative_cues = ["难过", "焦虑", "烦", "累", "撑不住", "崩溃", "生气"]
    positive_cues = ["开心", "轻松", "期待", "放心", "满足"]
    valence = 0.0
    arousal = 0.35
    if any(token in normalized for token in negative_cues):
        valence -= 0.45
        arousal += 0.25
    if any(token in normalized for token in positive_cues):
        valence += 0.45
        arousal += 0.15
    if "！" in normalized or "!" in normalized:
        arousal += 0.1
    return {
        "valence": max(-1.0, min(1.0, valence)),
        "arousal": max(0.0, min(1.0, arousal)),
    }


def generate_reply(user_input: str, recent_dialogue: List[Dict] | None = None) -> str:
    emotion = detect_emotion(user_input)
    recalled = normalize_recall_results(schema.recall(user_input, k=5))
    messages = build_reply_prompt(user_input, recalled, emotion, recent_dialogue=recent_dialogue)
    return call_ollama(messages, temperature=0.7)


def generate_diary(conversations: List[Dict], memories: List[Dict] | None = None, emotion: Dict[str, float] | None = None) -> str:
    messages = build_ai_diary_prompt(conversations, memories=memories, emotion=emotion)
    return call_ollama(messages, temperature=0.5)


def main() -> None:
    history: List[Dict] = []
    while True:
        user_input = input("> ").strip()
        if not user_input:
            continue
        if user_input in {"/quit", "/exit"}:
            break
        reply = generate_reply(user_input, recent_dialogue=history)
        print(reply)
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    main()
