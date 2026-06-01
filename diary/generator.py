import json
import re
from typing import Dict, List

from agent.kimi import call_kimi_chat
from diary.store import get_diary_payload, mark_ai_diary_pending, write_diary_markdown


MEMORY_LINK_KEYS = {
    "event": "events",
    "routine": "routines",
    "preference": "preferences",
    "relationship": "relationships",
    "summary": "summary",
}


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def average_emotion(snapshot: Dict) -> Dict:
    recent = snapshot.get("recent_va") or []
    emotion = snapshot.get("emotion") or {}
    scores = snapshot.get("scores") or {}
    if recent:
        valence = sum(_safe_float(item.get("valence")) for item in recent) / len(recent)
        arousal = sum(_safe_float(item.get("arousal")) for item in recent) / len(recent)
    else:
        valence = _safe_float(emotion.get("valence"))
        arousal = _safe_float(emotion.get("arousal"))
    return {
        "emotion_label": emotion.get("label") or "中性",
        "valence": valence,
        "arousal": arousal,
        "fusion_score": _safe_float(scores.get("fusion"), valence),
    }


def default_memory_links() -> Dict[str, List[str]]:
    return {"preferences": [], "events": [], "routines": [], "relationships": [], "summary": []}


def evidence_for(content: str, user_markdown: str, snapshot: Dict) -> Dict:
    modalities = snapshot.get("modalities") or {}
    return {
        "conversation": [content] if content else [],
        "user_diary": user_markdown.strip(),
        "availability": {
            "text": bool(modalities.get("text", True)),
            "audio": bool(modalities.get("audio", False)),
            "video": bool(modalities.get("video", False)),
        },
    }


def classify_user_content(content: str) -> str:
    text = re.sub(r"\s+", "", content)
    if any(token in text for token in ["喜欢", "希望", "不想", "不要", "偏好", "更愿意", "讨厌"]):
        return "preference"
    if any(token in text for token in ["每天", "经常", "总是", "习惯", "最近一直", "常常"]):
        return "routine"
    if any(token in text for token in ["老师", "朋友", "同学", "室友", "家人", "妈妈", "爸爸", "对象"]):
        return "relationship"
    return "event"


def append_structured_item(container: Dict, item_type: str, content: str, evidence: Dict) -> None:
    key = MEMORY_LINK_KEYS[item_type]
    prefix = {"event": "E", "routine": "R", "preference": "P", "relationship": "L"}[item_type]
    container[key].append(
        {
            "id": f"{prefix}{len(container[key]) + 1}",
            "content": content,
            "evidence": evidence,
        }
    )


def build_structured_ai_diary(date_key: str, snapshot: Dict, user_markdown: str) -> Dict:
    averages = average_emotion(snapshot)
    history = snapshot.get("history", [])[-16:]
    content = {"events": [], "routines": [], "preferences": [], "relationships": []}
    for item in history:
        if item.get("role") != "user":
            continue
        raw = (item.get("content") or "").strip()
        if not raw:
            continue
        memory_type = classify_user_content(raw)
        document = raw if raw.startswith("用户") else f"用户提到：{raw}"
        append_structured_item(content, memory_type, document, evidence_for(raw, user_markdown, snapshot))
    if user_markdown.strip():
        append_structured_item(
            content,
            "event",
            f"用户在日记中记录：{user_markdown.strip()[:120]}",
            evidence_for("", user_markdown, snapshot),
        )
    if not any(content.values()):
        append_structured_item(
            content,
            "event",
            "当天对话信息不足，暂不形成明确长期记忆。",
            evidence_for("", user_markdown, snapshot),
        )
    return {
        "date": date_key,
        "version": "v1.1",
        "summary": {
            "overall_state": f"今天整体更接近“{averages['emotion_label']}”状态。",
            **averages,
        },
        "content": content,
        "review": {
            "status": "pending",
            "items": [],
            "review_text": "",
            "review_timestamp": "",
            "memory_links": default_memory_links(),
        },
    }


def build_ai_diary_markdown_from_structured(data: Dict) -> str:
    summary = data.get("summary") or {}
    content = data.get("content") or {}
    lines = [
        f"# AI记 {data.get('date', '')}",
        "",
        "今天聊完之后，云雀想先把对你的理解记下来。如果哪里不对，你直接改我就好。",
        "",
        "## 今天的整体感觉",
        str(summary.get("overall_state") or "云雀今天还没有足够的状态线索。"),
        (
            f"云雀记录到的主情绪是“{summary.get('emotion_label', '中性')}”，"
            f"平均 valence 为 {_safe_float(summary.get('valence')):.2f}，"
            f"平均 arousal 为 {_safe_float(summary.get('arousal')):.2f}。"
        ),
    ]
    section_labels = [
        ("events", "云雀觉得今天比较重要的事"),
        ("routines", "云雀观察到的状态模式"),
        ("preferences", "云雀现在记下来的你的偏好"),
        ("relationships", "云雀留意到的关系线索"),
    ]
    for key, label in section_labels:
        items = content.get(key) or []
        if not items:
            continue
        lines.extend(["", f"## {label}"])
        for item in items:
            if isinstance(item, dict):
                lines.append(f"- {item.get('id', '-')}. {item.get('content', '')}")
            else:
                lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## 如果云雀理解错了",
            "你可以直接这样告诉我：",
            "- “P1 不对，应改成……”",
            "- “E2 可以删掉”",
            "- “补充一条偏好：……”",
        ]
    )
    return "\n".join(lines)


def build_ai_diary_markdown(date_key: str, snapshot: Dict, user_markdown: str) -> str:
    return build_ai_diary_markdown_from_structured(build_structured_ai_diary(date_key, snapshot, user_markdown))


def extract_json_object(text: str) -> Dict | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json|jsonc)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None


def validate_structured_ai_diary(data: Dict | None) -> bool:
    if not isinstance(data, dict):
        return False
    return isinstance(data.get("content"), dict) and isinstance(data.get("summary"), dict)


def sanitize_structured_ai_diary(data: Dict, date_key: str, snapshot: Dict, user_markdown: str) -> Dict:
    fallback = build_structured_ai_diary(date_key, snapshot, user_markdown)
    summary = {**fallback["summary"], **(data.get("summary") or {})}
    raw_content = data.get("content") or {}
    content = {"events": [], "routines": [], "preferences": [], "relationships": []}
    prefixes = {"events": "E", "routines": "R", "preferences": "P", "relationships": "L"}
    for key in content:
        for raw_item in raw_content.get(key) or []:
            if isinstance(raw_item, dict):
                item_content = str(raw_item.get("content") or "").strip()
                evidence = raw_item.get("evidence") or evidence_for(item_content, user_markdown, snapshot)
                item_id = str(raw_item.get("id") or "").strip()
            else:
                item_content = str(raw_item).strip()
                evidence = evidence_for(item_content, user_markdown, snapshot)
                item_id = ""
            if not item_content:
                continue
            content[key].append(
                {
                    "id": item_id or f"{prefixes[key]}{len(content[key]) + 1}",
                    "content": item_content,
                    "evidence": evidence,
                }
            )
    if not any(content.values()):
        content = fallback["content"]
    review = data.get("review") if isinstance(data.get("review"), dict) else {}
    review = {
        "status": review.get("status") or "pending",
        "items": review.get("items") if isinstance(review.get("items"), list) else [],
        "review_text": review.get("review_text") or "",
        "review_timestamp": review.get("review_timestamp") or "",
        "memory_links": review.get("memory_links") if isinstance(review.get("memory_links"), dict) else default_memory_links(),
    }
    return {
        "date": date_key,
        "version": "v1.1",
        "summary": summary,
        "content": content,
        "review": review,
    }


def build_ai_diary_prompt(date_key: str, snapshot: Dict, user_markdown: str) -> List[Dict[str, str]]:
    averages = average_emotion(snapshot)
    history = snapshot.get("history", [])[-16:]
    history_text = "\n".join(
        [
            f"{'用户' if item.get('role') == 'user' else 'AI'}：{(item.get('content') or '').strip()}"
            for item in history
            if (item.get("content") or "").strip()
        ]
    ) or "今天还没有足够的对话。"
    diary_text = (user_markdown or "").strip() or "今天用户还没有手动写日记。"
    system = (
        "你是长期陪伴系统中的结构化记忆整理助手。"
        "请只输出合法 JSON，不要 Markdown，不要代码块。"
        "把当天用户日记、情绪状态和对话内容整理成 AI记结构。"
        "content.events/routines/preferences/relationships 中每条 content 都要能直接作为长期记忆。"
        "summary 只用于归档，不作为主召回记忆。"
        "最终展示会使用“今天聊完之后，云雀想先把对你的理解记下来”的模板，"
        "所以 content 里的内容要短、具体、像记忆条目，不要写检测过程。"
    )
    user = (
        f"日期：{date_key}\n"
        f"主状态：{averages['emotion_label']}，平均valence={averages['valence']:.2f}，"
        f"平均arousal={averages['arousal']:.2f}，平均融合分数={averages['fusion_score']:.2f}\n\n"
        f"用户日记：\n{diary_text}\n\n"
        f"最近对话：\n{history_text}\n\n"
        "输出 schema："
        "{\"date\":\"YYYY-MM-DD\",\"version\":\"v1.1\",\"summary\":{\"overall_state\":\"\","
        "\"emotion_label\":\"\",\"valence\":0,\"arousal\":0,\"fusion_score\":0},"
        "\"content\":{\"events\":[],\"routines\":[],\"preferences\":[],\"relationships\":[]},"
        "\"review\":{\"status\":\"pending\",\"items\":[],\"review_text\":\"\","
        "\"review_timestamp\":\"\",\"memory_links\":{\"preferences\":[],\"events\":[],"
        "\"routines\":[],\"relationships\":[],\"summary\":[]}}}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def diary_looks_bad(text: str) -> bool:
    if not text:
        return True
    banned_fragments = ["作为AI", "客服", "官方渠道"]
    if any(fragment in text for fragment in banned_fragments):
        return True
    required_sections = [
        "## 今天的整体感觉",
        "## 如果云雀理解错了",
    ]
    return any(section not in text for section in required_sections)


def generate_structured_ai_diary(date_key: str, snapshot: Dict, user_markdown: str) -> Dict:
    content, _ = call_kimi_chat(
        build_ai_diary_prompt(date_key, snapshot, user_markdown),
        max_tokens=900,
        temperature=0.5,
    )
    parsed = extract_json_object(content)
    if validate_structured_ai_diary(parsed):
        return sanitize_structured_ai_diary(parsed, date_key, snapshot, user_markdown)
    return build_structured_ai_diary(date_key, snapshot, user_markdown)


def generate_ai_diary_markdown(date_key: str, snapshot: Dict, user_markdown: str) -> str:
    return build_ai_diary_markdown_from_structured(generate_structured_ai_diary(date_key, snapshot, user_markdown))


def refresh_ai_diary_from_snapshot(date_key: str, snapshot: Dict, user_id: str | None = None) -> bool:
    payload = get_diary_payload(date_key, user_id=user_id)
    structured = generate_structured_ai_diary(date_key, snapshot, payload["user_markdown"])
    ai_markdown = build_ai_diary_markdown_from_structured(structured)
    write_diary_markdown(date_key, "ai", ai_markdown, user_id=user_id)
    mark_ai_diary_pending(
        date_key,
        user_id=user_id,
        structured=structured,
        memory_links=structured.get("review", {}).get("memory_links"),
    )
    return True
