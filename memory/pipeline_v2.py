from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List

from agent.agent import call_chat_completion, chat_api_ready
from core.utils import memory_date_from_payload, normalize_timestamp_to_china
from memory import v2 as memory_v2
from storage.chat_store import (
    create_ai_diary_v2_batch,
    get_ai_diary_v2_batch,
    get_runtime_state,
    list_ai_diary_v2_batches,
    list_chat_messages,
    mark_ai_diary_v2_batch_reviewed,
    set_runtime_state,
)


INTERACTIONS_PER_OBSERVATION = 10
OBSERVATIONS_PER_DIARY = 3
REFLECTION_IMPORTANCE_THRESHOLD = 50.0
STRATEGY_IMPORTANCE_THRESHOLD = 50.0
MAX_SOURCE_MEMORIES = 10


def _extract_json(text: str) -> Dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _conversation_text(messages: Iterable[Dict[str, Any]]) -> str:
    lines = []
    for item in messages:
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        role = "用户" if item.get("role") == "user" else "云雀"
        lines.append(f"{role}：{content}")
    return "\n".join(lines)


def _fallback_topics(text: str) -> List[str]:
    topics: List[str] = []
    if any(token in text for token in ("喜欢", "讨厌", "偏好", "更愿意", "不想")):
        topics.append("preference")
    if any(token in text for token in ("每天", "经常", "总是", "习惯", "常常", "每次")):
        topics.append("routine")
    if any(token in text for token in ("朋友", "家人", "老师", "同学", "室友", "对象", "同事")):
        topics.append("relationship")
    if not topics or any(token in text for token in ("今天", "最近", "项目", "考试", "工作", "发生")):
        topics.append("event")
    return memory_v2.normalize_topics(topics)


def _fallback_observation(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    user_messages = [
        str(item.get("content") or "").strip()
        for item in messages
        if item.get("role") == "user" and str(item.get("content") or "").strip()
    ]
    joined = "；".join(user_messages[-4:])
    description = f"用户近期的互动主要涉及：{joined[:180]}" if joined else "用户近期完成了一段持续对话。"
    return {
        "topics": _fallback_topics(joined),
        "description": description,
        "importance": 6,
        "confidence": 5,
    }


def generate_observation(user_id: str, timestamp: str = "") -> Dict[str, Any] | None:
    messages = list_chat_messages(user_id, limit=INTERACTIONS_PER_OBSERVATION * 2)
    if not messages:
        return None
    fallback = _fallback_observation(messages)
    parsed: Dict[str, Any] = {}
    if chat_api_ready():
        system = (
            "你是陪伴智能体的观察记忆整理器。"
            "根据最近十个完整交互轮次，只总结用户明确表达或有充分上下文支持的信息。"
            "主题只能从event、preference、routine、relationship中选择一个或多个。"
            "description必须是简洁、自然、可独立理解的第三人称用户观察，不能记录模型的推理过程。"
            "importance与confidence是0到10之间的整数。只输出JSON。"
        )
        user = (
            f"最近对话：\n{_conversation_text(messages)}\n\n"
            "输出格式："
            '{"topics":["event"],"description":"","importance":6,"confidence":6}'
        )
        content, _ = call_chat_completion(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=500,
            temperature=0.1,
        )
        parsed = _extract_json(content)
    description = str(parsed.get("description") or fallback["description"]).strip()
    if not description:
        return None
    return memory_v2.create_memory(
        layer="observation",
        user_id=user_id,
        description=description[:240],
        topics=parsed.get("topics") or parsed.get("topic") or fallback["topics"],
        importance=parsed.get("importance", fallback["importance"]),
        confidence=parsed.get("confidence", fallback["confidence"]),
        review_status="pending",
        created_at=timestamp,
    )


def _next_batch_id(user_id: str, date_key: str) -> str:
    prefix = f"diary_{date_key.replace('-', '')}_"
    maximum = 0
    for batch in list_ai_diary_v2_batches(user_id, date_key=date_key, limit=500):
        batch_id = str(batch.get("batch_id") or "")
        if batch_id.startswith(prefix):
            try:
                maximum = max(maximum, int(batch_id.rsplit("_", 1)[-1]))
            except ValueError:
                continue
    return f"{prefix}{maximum + 1:03d}"


def maybe_create_ai_diary_batch(user_id: str, timestamp: str = "") -> Dict[str, Any] | None:
    pending = memory_v2.list_pending_observations(user_id, unbatched_only=True)
    if len(pending) < OBSERVATIONS_PER_DIARY:
        return None
    selected = pending[:OBSERVATIONS_PER_DIARY]
    timestamp = normalize_timestamp_to_china(timestamp)
    date_key = memory_date_from_payload(timestamp)
    batch_id = _next_batch_id(user_id, date_key)
    batch = create_ai_diary_v2_batch(
        batch_id,
        user_id,
        date_key,
        [item["display_id"] for item in selected],
        created_at=timestamp,
    )
    memory_v2.assign_diary_batch(
        user_id,
        [item["display_id"] for item in selected],
        batch_id,
    )
    return batch_payload(user_id, batch)


def record_complete_interaction(user_id: str, timestamp: str = "") -> Dict[str, Any]:
    state_key = f"v2:interaction_count:{user_id}"
    try:
        count = int(get_runtime_state(state_key, "0"))
    except ValueError:
        count = 0
    count += 1
    observation = None
    batch = None
    if count >= INTERACTIONS_PER_OBSERVATION:
        observation = generate_observation(user_id, timestamp)
        count = 0
        if observation:
            batch = maybe_create_ai_diary_batch(user_id, timestamp)
    set_runtime_state(state_key, str(count))
    return {
        "interaction_count": count,
        "observation": observation,
        "ai_diary_batch": batch,
    }


def _batch_observations(user_id: str, batch: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for memory_id in batch.get("observation_ids") or []:
        item = memory_v2.get_memory("observation", user_id, str(memory_id))
        if item:
            items.append(item)
    return items


def batch_payload(user_id: str, batch: Dict[str, Any]) -> Dict[str, Any]:
    items = _batch_observations(user_id, batch)
    return {
        **batch,
        "items": [
            {
                "id": item["display_id"],
                "topics": item["topics"],
                "description": item["description"],
                "importance": item["importance"],
                "confidence": item["confidence"],
                "review_status": item["review_status"],
            }
            for item in items
        ],
        "pending_count": sum(1 for item in items if item["review_status"] == "pending"),
    }


def list_ai_diary_batches(user_id: str, date_key: str = "") -> Dict[str, Any]:
    batches = [
        batch_payload(user_id, batch)
        for batch in list_ai_diary_v2_batches(user_id, date_key=date_key, limit=200)
    ]
    return {
        "user_id": user_id,
        "date": date_key,
        "batches": batches,
        "pending_count": sum(batch["pending_count"] for batch in batches),
    }


def _source_lines(items: Iterable[Dict[str, Any]]) -> str:
    return "\n".join(
        f"- {item['display_id']}：{item['description']}（重要度{item['importance']:.1f}，置信度{item['confidence']:.1f}）"
        for item in items
    )


def _generate_reflection(user_id: str, topic: str, observations: List[Dict[str, Any]]) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    recent_reflections = [
        item
        for item in memory_v2.list_memories(user_id, layer="reflection")
        if topic in item["topics"]
    ][:MAX_SOURCE_MEMORIES]
    if chat_api_ready():
        system = (
            "你是陪伴智能体的反思记忆生成器。"
            "根据已经由用户审查确认的观察，形成一条更高层但仍有证据支持的用户理解。"
            "不能引入观察中不存在的事实，不能把一次事件泛化为稳定习惯。"
            "主题只能是event、preference、routine、relationship中的一个。"
            "importance与confidence是0到10之间的整数。只输出JSON。"
        )
        user = (
            f"主题：{topic}\n"
            f"已审查观察：\n{_source_lines(observations)}\n\n"
            f"已有同主题反思：\n{_source_lines(recent_reflections) or '暂无'}\n\n"
            '输出格式：{"description":"","importance":7,"confidence":7}'
        )
        content, _ = call_chat_completion(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=500,
            temperature=0.1,
        )
        parsed = _extract_json(content)
    description = str(parsed.get("description") or "").strip()
    if not description:
        description = f"多次已审查观察共同表明：{observations[-1]['description']}"
    confidence = parsed.get(
        "confidence",
        sum(item["confidence"] for item in observations) / max(len(observations), 1),
    )
    importance = parsed.get(
        "importance",
        max(item["importance"] for item in observations),
    )
    reflection = memory_v2.create_memory(
        layer="reflection",
        user_id=user_id,
        description=description[:260],
        topics=[topic],
        importance=importance,
        confidence=confidence,
        linked_memory_ids=[item["display_id"] for item in observations],
    )
    memory_v2.mark_observations_reflected(
        user_id,
        [item["display_id"] for item in observations],
        topic,
    )
    return reflection


def _generate_strategy(user_id: str, reflections: List[Dict[str, Any]]) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    if chat_api_ready():
        system = (
            "你是陪伴智能体的互动策略生成器。"
            "根据有来源的用户反思，概括在某种具体陪伴场景下应如何回应用户。"
            "策略必须克制、可执行，不能虚构用户偏好。"
            "importance与confidence是0到10之间的整数。只输出JSON。"
        )
        user = (
            f"反思：\n{_source_lines(reflections)}\n\n"
            '输出格式：{"scene":"","description":"","importance":7,"confidence":7}'
        )
        content, _ = call_chat_completion(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=500,
            temperature=0.1,
        )
        parsed = _extract_json(content)
    scene = str(parsed.get("scene") or "用户需要被理解和陪伴时").strip()
    description = str(parsed.get("description") or "").strip()
    if not description:
        description = "先结合已经确认的用户背景回应，再以克制的方式询问用户当前最需要的支持。"
    strategy = memory_v2.create_memory(
        layer="strategy",
        user_id=user_id,
        description=description[:260],
        importance=parsed.get("importance", max(item["importance"] for item in reflections)),
        confidence=parsed.get(
            "confidence",
            sum(item["confidence"] for item in reflections) / max(len(reflections), 1),
        ),
        linked_memory_ids=[item["display_id"] for item in reflections],
        scene=scene[:100],
    )
    memory_v2.mark_reflections_used(
        user_id,
        [item["display_id"] for item in reflections],
    )
    return strategy


def run_hierarchy_updates(user_id: str) -> Dict[str, List[Dict[str, Any]]]:
    created_reflections: List[Dict[str, Any]] = []
    for topic in memory_v2.TOPICS:
        candidates = memory_v2.reviewed_observations_for_topic(user_id, topic)
        while sum(item["importance"] for item in candidates) >= REFLECTION_IMPORTANCE_THRESHOLD:
            selected = candidates[:MAX_SOURCE_MEMORIES]
            created_reflections.append(_generate_reflection(user_id, topic, selected))
            candidates = memory_v2.reviewed_observations_for_topic(user_id, topic)

    created_strategies: List[Dict[str, Any]] = []
    candidates = memory_v2.unused_reflections(user_id)
    while sum(item["importance"] for item in candidates) >= STRATEGY_IMPORTANCE_THRESHOLD:
        selected = candidates[:MAX_SOURCE_MEMORIES]
        created_strategies.append(_generate_strategy(user_id, selected))
        candidates = memory_v2.unused_reflections(user_id)
    return {
        "reflections": created_reflections,
        "strategies": created_strategies,
    }


def review_ai_diary_item(
    user_id: str,
    batch_id: str,
    observation_id: str,
    action: str,
    *,
    revised_content: str = "",
) -> Dict[str, Any]:
    batch = get_ai_diary_v2_batch(user_id, batch_id)
    if not batch:
        raise ValueError("AI记批次不存在")
    if observation_id not in batch.get("observation_ids", []):
        raise ValueError("观察不属于该AI记批次")
    reviewed = memory_v2.review_observation(
        user_id,
        observation_id,
        action,
        revised_content=revised_content,
    )
    if not reviewed:
        raise ValueError("该观察已审查或不存在")
    refreshed_batch = get_ai_diary_v2_batch(user_id, batch_id) or batch
    payload = batch_payload(user_id, refreshed_batch)
    if payload["pending_count"] == 0:
        refreshed_batch = mark_ai_diary_v2_batch_reviewed(user_id, batch_id) or refreshed_batch
        payload = batch_payload(user_id, refreshed_batch)
    hierarchy_updates = run_hierarchy_updates(user_id)
    return {
        "ok": True,
        "batch": payload,
        "reviewed_item": {
            "id": reviewed["display_id"],
            "review_status": reviewed["review_status"],
            "description": reviewed["description"],
        },
        "created": hierarchy_updates,
        "memory": memory_v2.hierarchy_payload(user_id),
    }
