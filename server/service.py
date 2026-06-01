import re
import threading
import time
from difflib import SequenceMatcher
from typing import Any, Dict, List

from agent.replies import agent_payload, decide_memory_update, generate_agent_reply
from core.config import (
    AI_DIARY_UPDATE_INTERVAL,
    CHAT_CONTEXT_LIMIT,
    CHAT_DISPLAY_LIMIT,
    DAILY_MEMORY_DECAY_THRESHOLD,
    SELF_MM_MODEL_PATH,
)
from core.utils import memory_date_from_payload, normalize_timestamp_to_china
from diary.generator import refresh_ai_diary_from_snapshot
from diary.store import (
    delete_diary_data,
    get_diary_index_payload,
    get_diary_payload,
    mark_ai_diary_reviewed,
    read_ai_diary_meta,
    save_user_diary,
)
from emotion.mapping import derive_architecture_emotion, make_emotion_bars
from emotion.media import (
    build_audio_tensor_from_media,
    build_video_tensor_from_media,
    resolve_payload_media_path,
    resolve_text_input,
    summarize_audio_tensor,
    summarize_video_tensor,
)
from emotion.models import SelfMMRunner
from memory import schema as long_memory
from storage.chat_store import (
    add_chat_message,
    clear_pending_ai_diary_date,
    delete_chat_messages,
    delete_pending_ai_diary_dates,
    list_chat_messages,
    list_chat_messages_for_date,
    list_context_messages,
    list_pending_ai_diary_dates,
    get_runtime_state,
    mark_pending_ai_diary_date,
    set_runtime_state,
)


EMOTION_RUNNER = None
MEMORY_LOCK = threading.Lock()
LONG_MEMORY_LOCK = threading.Lock()
DEFAULT_MEMORY_USER_ID = "local_user"
MEMORY_STATE = {
    "pending_diary_dates": set(),
    "latest_by_date": {},
}
EMOTION_STATE = {
    "recent_va": [],
    "smoothed": None,
}


def current_user_id(payload: Dict | None = None) -> str:
    payload = payload or {}
    user_id = (payload.get("user_id") or payload.get("userId") or DEFAULT_MEMORY_USER_ID)
    return str(user_id).strip() or DEFAULT_MEMORY_USER_ID


def memory_snapshot_key(user_id: str, date_key: str) -> str:
    return f"{user_id}:{date_key}"


def normalize_memory_document(document: str) -> str:
    text = (document or "").strip()
    text = re.sub(r"^(用户表达了陪伴偏好|用户提到重要关系线索|用户当前重要状态或事件)[：:]\s*", "", text)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。！？、；：,.!?;:\"'“”‘’（）()【】\\[\\]{}<>《》]", "", text)
    return text.lower()


def memory_topic_tokens(document: str) -> set[str]:
    text = normalize_memory_document(document)
    tokens: set[str] = set()
    domain_terms = [
        "保研",
        "考研",
        "复试",
        "答辩",
        "考试",
        "项目",
        "大创",
        "论文",
        "实习",
        "工作",
        "面试",
        "朋友",
        "家人",
        "室友",
        "对象",
        "老师",
        "同学",
        "睡眠",
        "失眠",
    ]
    for term in domain_terms:
        if term in text:
            tokens.add(term)
    for match in re.finditer(r"[\u4e00-\u9fff]{2,6}", text):
        word = match.group(0)
        if word not in {"用户", "当前", "重要", "状态", "事件", "相关", "事情", "事宜", "已经", "曾经", "提及"}:
            tokens.add(word)
    return tokens


def memory_specificity(document: str) -> int:
    text = normalize_memory_document(document)
    score = len(text)
    for term in ("成功", "失败", "通过", "确定", "已经", "拿到", "确认", "录取", "完成"):
        if term in text:
            score += 20
    for term in ("待确认", "是否", "记得", "相关事宜", "事情"):
        if term in text:
            score -= 12
    return score


def find_merge_candidate_locked(document: str, user_id: str, memory_type: str) -> Dict | None:
    if memory_type not in {"event", "relationship", "preference", "routine"}:
        return None
    new_topics = memory_topic_tokens(document)
    if not new_topics:
        return None
    limit = max(long_memory.collection.count(), 1)
    existing_items = long_memory.list_memories(limit=limit, user_id=user_id or None, memory_type=memory_type or None)
    for item in existing_items:
        old_topics = memory_topic_tokens(item.get("document", ""))
        if not old_topics or not (new_topics & old_topics):
            continue
        if memory_specificity(document) >= memory_specificity(item.get("document", "")):
            return item
    return None


def find_duplicate_memory_locked(document: str, user_id: str, memory_type: str) -> Dict | None:
    normalized = normalize_memory_document(document)
    if not normalized:
        return None
    limit = max(long_memory.collection.count(), 1)
    existing_items = long_memory.list_memories(limit=limit, user_id=user_id or None, memory_type=memory_type or None)
    for item in existing_items:
        existing = normalize_memory_document(item.get("document", ""))
        if not existing:
            continue
        if existing == normalized or SequenceMatcher(None, existing, normalized).ratio() >= 0.94:
            return item
    return None


def normalize_recall_results(results: Dict) -> list[Dict]:
    ids = (results.get("ids") or [[]])[0]
    documents = (results.get("documents") or [[]])[0]
    metadatas = (results.get("metadatas") or [[]])[0]
    distances = (results.get("distances") or [[]])[0]
    scores = (results.get("scores") or [[]])[0]
    semantic_similarities = (results.get("semantic_similarities") or [[]])[0]
    recencies = (results.get("recencies") or [[]])[0]
    items = []
    for index, document in enumerate(documents):
        item = {
            "id": ids[index] if index < len(ids) else "",
            "document": document,
            "metadata": metadatas[index] if index < len(metadatas) else {},
            "distance": distances[index] if index < len(distances) else None,
            "score": scores[index] if index < len(scores) else None,
        }
        if index < len(semantic_similarities):
            item["semantic_similarity"] = semantic_similarities[index]
        if index < len(recencies):
            item["recency"] = recencies[index]
        items.append(item)
    return items


def recall_long_memories(
    query: str,
    k: int = 3,
    user_id: str | None = DEFAULT_MEMORY_USER_ID,
    memory_type: str | None = None,
) -> list[Dict]:
    if not query.strip():
        return []
    recall_types = memory_type or ["event", "routine", "preference", "relationship"]
    with LONG_MEMORY_LOCK:
        results = long_memory.recall(
            query,
            k=k,
            user_id=user_id or None,
            memory_type=recall_types,
        )
    return normalize_recall_results(results)


def list_long_memories(
    limit: int = 50,
    offset: int = 0,
    user_id: str | None = DEFAULT_MEMORY_USER_ID,
    memory_type: str | None = None,
) -> list[Dict]:
    with LONG_MEMORY_LOCK:
        return long_memory.list_memories(
            limit=limit,
            offset=offset,
            user_id=user_id or None,
            memory_type=memory_type or None,
        )


def count_long_memories(user_id: str | None = DEFAULT_MEMORY_USER_ID, memory_type: str | None = None) -> int:
    with LONG_MEMORY_LOCK:
        return long_memory.count_memories(user_id=user_id or None, memory_type=memory_type or None)


def write_memory_from_decision(
    decision: Dict,
    user_id: str,
    date_key: str,
    timestamp: str | None,
    emotion: Dict[str, float],
    modalities: Dict[str, bool],
) -> Dict:
    if not decision.get("should_write"):
        return {"written": False, "decision": decision}
    document = (decision.get("document") or "").strip()
    if not document:
        return {"written": False, "decision": {**decision, "reason": "缺少可写入内容"}}

    memory_source = decision.get("source") if decision.get("source") in {"conversation", "inference"} else "conversation"
    memory_type = decision.get("type") if decision.get("type") in {"event", "routine", "preference", "relationship", "summary"} else "event"
    memory_owner = "ai" if memory_source == "inference" else "user"
    memory = long_memory.create_memory(
        document=document,
        date=date_key,
        timestamp=timestamp,
        user=memory_owner,
        user_id=user_id,
        type=memory_type,
        source=memory_source,
        has_emotion=True,
        valence=emotion.get("valence", 0.0),
        arousal=emotion.get("arousal", 0.0),
        confidence=decision.get("confidence", 0.7),
        text=modalities.get("text", False),
        audio=modalities.get("audio", False),
        video=modalities.get("video", False),
    )
    with LONG_MEMORY_LOCK:
        duplicate = find_duplicate_memory_locked(document, user_id=user_id, memory_type=memory_type)
        if duplicate:
            return {
                "written": False,
                "duplicate": True,
                "duplicate_id": duplicate.get("id"),
                "document": document,
                "decision": {**decision, "reason": "已存在相同或高度相似的长期记忆，跳过写入"},
            }
        merge_candidate = find_merge_candidate_locked(document, user_id=user_id, memory_type=memory_type)
        if merge_candidate:
            memory_id = merge_candidate["id"]
            old_metadata = merge_candidate.get("metadata") or {}
            old_importance = float(old_metadata.get("importance_0", old_metadata.get("importance", 0.0)))
            memory["metadata"]["importance_0"] = max(old_importance, float(memory["metadata"].get("importance_0", 0.0)))
            memory["metadata"]["importance"] = memory["metadata"]["importance_0"]
            long_memory.update_memory(memory_id, document=document, metadata_updates=memory["metadata"])
            return {
                "written": True,
                "merged": True,
                "id": memory_id,
                "old_document": merge_candidate.get("document", ""),
                "document": document,
                "metadata": memory["metadata"],
                "decision": {**decision, "reason": "已合并同主题长期记忆，使用更新且更明确的状态"},
            }
        memory_id = long_memory.add_memory(memory)
    return {
        "written": True,
        "id": memory_id,
        "document": document,
        "metadata": memory["metadata"],
        "decision": decision,
    }


def update_emotion_state(emotion: Dict[str, float]) -> Dict[str, object]:
    current = {
        "valence": float(emotion["valence"]),
        "arousal": float(emotion["arousal"]),
        "timestamp": time.time(),
    }
    previous_smoothed = EMOTION_STATE["smoothed"]
    if previous_smoothed is None:
        delta = 0.0
        smoothed = {"valence": current["valence"], "arousal": current["arousal"]}
    else:
        delta = (
            (current["valence"] - previous_smoothed["valence"]) ** 2
            + (current["arousal"] - previous_smoothed["arousal"]) ** 2
        ) ** 0.5
        smoothed = {
            "valence": previous_smoothed["valence"] * 0.65 + current["valence"] * 0.35,
            "arousal": previous_smoothed["arousal"] * 0.65 + current["arousal"] * 0.35,
        }
    recent = [*EMOTION_STATE["recent_va"], current][-3:]
    EMOTION_STATE["recent_va"] = recent
    EMOTION_STATE["smoothed"] = smoothed
    return {
        "recent_va": recent,
        "smoothed_va": smoothed,
        "delta": round(delta, 4),
        "significant_change": delta >= 0.45,
        "threshold": 0.45,
    }


def get_emotion_runner() -> SelfMMRunner:
    global EMOTION_RUNNER
    if EMOTION_RUNNER is not None:
        return EMOTION_RUNNER
    if not SELF_MM_MODEL_PATH.exists():
        raise FileNotFoundError(f"SELF_MM MediaPipe 权重文件不存在：{SELF_MM_MODEL_PATH}")
    EMOTION_RUNNER = SelfMMRunner(SELF_MM_MODEL_PATH)
    return EMOTION_RUNNER


def mark_memory_snapshot(user_id: str, date_key: str, snapshot: Dict) -> None:
    key = memory_snapshot_key(user_id, date_key)
    with MEMORY_LOCK:
        MEMORY_STATE["latest_by_date"][key] = snapshot
        MEMORY_STATE["pending_diary_dates"].add((user_id, date_key))
    mark_pending_ai_diary_date(user_id, date_key)


def snapshot_from_chat_history(user_id: str, date_key: str) -> Dict | None:
    messages = list_chat_messages_for_date(user_id, date_key, limit=80)
    if not messages:
        return None
    emotion_messages = [
        item
        for item in messages
        if item.get("valence") is not None or item.get("arousal") is not None or item.get("emotion_label")
    ]
    latest_emotion = emotion_messages[-1] if emotion_messages else {}
    valence_values = [float(item["valence"]) for item in emotion_messages if item.get("valence") is not None]
    arousal_values = [float(item["arousal"]) for item in emotion_messages if item.get("arousal") is not None]
    valence = sum(valence_values) / len(valence_values) if valence_values else 0.0
    arousal = sum(arousal_values) / len(arousal_values) if arousal_values else 0.0
    return {
        "emotion": {
            "label": latest_emotion.get("emotion_label") or "中性",
            "valence": valence,
            "arousal": arousal,
            "confidence": 0.5,
        },
        "scores": {
            "fusion": valence,
            "text": valence,
            "audio": 0.0,
            "video": 0.0,
        },
        "history": [{"role": item["role"], "content": item["content"]} for item in messages],
        "audio": {},
        "video": {},
        "modalities": {"text": True, "audio": False, "video": False},
        "recent_va": [{"valence": valence, "arousal": arousal}],
        "timestamp": messages[-1].get("created_at") or normalize_timestamp_to_china(f"{date_key}T23:59:59+08:00"),
        "user_id": user_id,
        "source": "sqlite_chat_history",
    }


def refresh_ai_diary(date_key: str, user_id: str = DEFAULT_MEMORY_USER_ID) -> bool:
    if date_key >= memory_date_from_payload(""):
        return False
    if read_ai_diary_meta(date_key, user_id=user_id).get("status") in {"pending", "confirmed", "corrected"}:
        with MEMORY_LOCK:
            MEMORY_STATE["pending_diary_dates"].discard((user_id, date_key))
        clear_pending_ai_diary_date(user_id, date_key)
        return False
    with MEMORY_LOCK:
        snapshot = MEMORY_STATE["latest_by_date"].get(memory_snapshot_key(user_id, date_key))
    if snapshot is None:
        snapshot = snapshot_from_chat_history(user_id, date_key)
        if snapshot is None:
            return False
    refreshed = refresh_ai_diary_from_snapshot(date_key, snapshot, user_id=user_id)
    with MEMORY_LOCK:
        MEMORY_STATE["pending_diary_dates"].discard((user_id, date_key))
    clear_pending_ai_diary_date(user_id, date_key)
    return refreshed


def apply_daily_memory_decay(today: str | None = None) -> Dict:
    today = today or memory_date_from_payload("")
    state_key = "last_memory_decay_date"
    if get_runtime_state(state_key) == today:
        return {"ran": False, "date": today, "reason": "already applied"}
    with LONG_MEMORY_LOCK:
        actions = long_memory.apply_decay(threshold=DAILY_MEMORY_DECAY_THRESHOLD, dry_run=False)
        count = long_memory.collection.count()
    set_runtime_state(state_key, today)
    return {
        "ran": True,
        "date": today,
        "threshold": DAILY_MEMORY_DECAY_THRESHOLD,
        "actions": actions,
        "count": count,
    }


def run_ai_diary_maintenance() -> None:
    today = memory_date_from_payload("")
    apply_daily_memory_decay(today)
    pending_dates = set(list_pending_ai_diary_dates(before_date=today))
    with MEMORY_LOCK:
        pending_dates.update(
            (user_id, date_key)
            for user_id, date_key in MEMORY_STATE["pending_diary_dates"]
            if date_key < today
        )
    for user_id, date_key in sorted(pending_dates, key=lambda item: item[1]):
        try:
            refresh_ai_diary(date_key, user_id=user_id)
        except Exception:
            continue


def ai_diary_worker() -> None:
    while True:
        try:
            run_ai_diary_maintenance()
        except Exception:
            pass
        time.sleep(max(20, AI_DIARY_UPDATE_INTERVAL))


def analyze_and_reply(payload: Dict, should_reply: bool = True) -> Dict:
    user_id = current_user_id(payload)
    user_text, text_source = resolve_text_input(payload)
    history = list_context_messages(user_id, limit=CHAT_CONTEXT_LIMIT)
    if not history:
        history = (payload.get("history", []) or [])[-CHAT_CONTEXT_LIMIT:]
    proactive = bool(payload.get("proactive"))
    timestamp = normalize_timestamp_to_china(payload.get("timestamp", ""))
    date_key = memory_date_from_payload(timestamp)
    temp_paths = []
    audio_path, audio_is_temp = resolve_payload_media_path(payload, "audio")
    video_path, video_is_temp = resolve_payload_media_path(payload, "video")
    if audio_is_temp and audio_path is not None:
        temp_paths.append(audio_path)
    if video_is_temp and video_path is not None:
        temp_paths.append(video_path)

    try:
        audio_tensor, audio_meta = build_audio_tensor_from_media(audio_path or video_path)
        video_tensor, video_meta = build_video_tensor_from_media(video_path)
        audio_summary = summarize_audio_tensor(audio_tensor)
        video_summary = summarize_video_tensor(video_tensor)
        modalities = {
            "text": bool(user_text),
            "audio": bool(audio_meta.get("available")),
            "video": bool(video_meta.get("available")),
        }

        runner = get_emotion_runner()
        raw_scores = runner.predict(user_text, audio_tensor, video_tensor)
        emotion = derive_architecture_emotion(raw_scores, video_summary, modalities)
        emotion_state = update_emotion_state(emotion.__dict__)
        agent_reply = ""
        agent_source = "none"
        agent_error = ""
        long_memory_payload = {
            "user_id": user_id,
            "recalled": [],
            "update": {"written": False, "decision": {"should_write": False, "reason": "未触发文本回复"}},
        }
        if should_reply:
            if proactive:
                raw_scores = {
                    **raw_scores,
                    "recent_va": [
                        {
                            "valence": round(item["valence"], 4),
                            "arousal": round(item["arousal"], 4),
                        }
                        for item in emotion_state["recent_va"]
                    ],
                    "proactive_reason": payload.get("proactive_reason") or payload.get("proactiveReason") or "主动回应",
                }
            memory_query = user_text or raw_scores.get("proactive_reason") or "主动关心当前状态"
            recalled_memories = recall_long_memories(memory_query, k=3, user_id=user_id)
            agent_reply, agent_source, agent_error = generate_agent_reply(
                user_text,
                emotion,
                raw_scores,
                history,
                memories=recalled_memories,
                proactive=proactive,
            )
            decision, decision_source = decide_memory_update(
                user_text,
                agent_reply,
                emotion,
                raw_scores,
                recalled_memories,
                history,
                use_llm=agent_source == "kimi",
            )
            memory_update = write_memory_from_decision(
                decision,
                user_id=user_id,
                date_key=date_key,
                timestamp=timestamp,
                emotion=emotion.__dict__,
                modalities=modalities,
            )
            memory_update["decision_source"] = decision_source
            long_memory_payload = {
                "user_id": user_id,
                "recalled": recalled_memories,
                "update": memory_update,
            }
        if should_reply:
            if user_text:
                add_chat_message(user_id, "user", user_text, created_at=timestamp, emotion=emotion.__dict__)
            if agent_reply:
                add_chat_message(user_id, "assistant", agent_reply, created_at=timestamp, emotion=emotion.__dict__)
        chat_history = list_chat_messages(user_id, limit=CHAT_DISPLAY_LIMIT)
        predicted_history = [
            {"role": item["role"], "content": item["content"]}
            for item in chat_history[-CHAT_CONTEXT_LIMIT:]
        ]
        if not predicted_history:
            predicted_history = history + ([{"role": "user", "content": user_text}] if user_text else [])
            if should_reply and agent_reply:
                predicted_history.append({"role": "assistant", "content": agent_reply})
        mark_memory_snapshot(
            user_id,
            date_key,
            {
                "emotion": emotion.__dict__,
                "scores": raw_scores,
                "history": predicted_history,
                "audio": audio_summary,
                "video": video_summary,
                "modalities": modalities,
                "recent_va": emotion_state["recent_va"],
                "timestamp": timestamp,
                "user_id": user_id,
            },
        )

        return {
            "model": runner.metadata(),
            "scores": raw_scores,
            "emotion": emotion.__dict__,
            "emotion_state": emotion_state,
            "emotion_bars": make_emotion_bars(emotion),
            "agent": agent_payload(agent_reply, agent_source, agent_error),
            "memory": get_diary_payload(date_key, user_id=user_id),
            "long_memory": long_memory_payload,
            "modal_inputs": {
                "text_available": modalities["text"],
                "text_source": text_source,
                "audio_available": modalities["audio"],
                "video_available": modalities["video"],
                "audio": audio_meta,
                "video": video_meta,
            },
            "media_features": {
                "audio": audio_summary,
                "video": video_summary,
            },
            "chat_history": chat_history,
            "timestamp": timestamp,
        }
    finally:
        for path in temp_paths:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass


def handle_diary_user(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    date_key = payload.get("date") or memory_date_from_payload("")
    response = save_user_diary(date_key, payload.get("markdown", ""), user_id=user_id)
    if date_key == memory_date_from_payload(""):
        with MEMORY_LOCK:
            MEMORY_STATE["pending_diary_dates"].add((user_id, date_key))
        mark_pending_ai_diary_date(user_id, date_key)
    return response


def handle_chat_history(params: Dict[str, list[str]]) -> Dict:
    user_id = (params.get("_auth_user_id") or params.get("user_id") or params.get("userId") or [DEFAULT_MEMORY_USER_ID])[0]
    try:
        limit = int((params.get("limit") or [CHAT_DISPLAY_LIMIT])[0])
    except (TypeError, ValueError):
        limit = CHAT_DISPLAY_LIMIT
    limit = max(1, min(limit, 50))
    return {
        "ok": True,
        "user_id": user_id,
        "limit": limit,
        "items": list_chat_messages(user_id, limit=limit),
    }


def handle_diary_refresh(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    date_key = payload.get("date") or memory_date_from_payload("")
    refreshed = refresh_ai_diary(date_key, user_id=user_id)
    return {"ok": refreshed, **get_diary_index_payload(date_key, user_id=user_id)}


def snapshot_for_diary_review(date_key: str, user_id: str = DEFAULT_MEMORY_USER_ID) -> Dict:
    with MEMORY_LOCK:
        snapshot = MEMORY_STATE["latest_by_date"].get(memory_snapshot_key(user_id, date_key)) or {}
    return snapshot or snapshot_from_chat_history(user_id, date_key) or {}


def emotion_for_memory_write(snapshot: Dict) -> Dict[str, float]:
    recent = snapshot.get("recent_va") or []
    if recent:
        valence_values = [float(item.get("valence", 0.0)) for item in recent]
        arousal_values = [float(item.get("arousal", 0.0)) for item in recent]
        return {
            "valence": sum(valence_values) / len(valence_values),
            "arousal": sum(arousal_values) / len(arousal_values),
        }
    emotion = snapshot.get("emotion") or {}
    return {
        "valence": float(emotion.get("valence", 0.0)),
        "arousal": float(emotion.get("arousal", 0.0)),
    }


REVIEW_CONTENT_KEYS = {
    "event": "events",
    "events": "events",
    "routine": "routines",
    "routines": "routines",
    "preference": "preferences",
    "preferences": "preferences",
    "relationship": "relationships",
    "relationships": "relationships",
}

REVIEW_MEMORY_TYPES = {
    "events": "event",
    "routines": "routine",
    "preferences": "preference",
    "relationships": "relationship",
}


def default_review_memory_links() -> Dict[str, List[str]]:
    return {"preferences": [], "events": [], "routines": [], "relationships": [], "summary": []}


def normalized_review_content_key(value: str) -> str:
    return REVIEW_CONTENT_KEYS.get((value or "").strip().lower(), "events")


def review_memory_type(value: str) -> str:
    return REVIEW_MEMORY_TYPES[normalized_review_content_key(value)]


def structured_diary_items(structured: Dict | None) -> List[Dict[str, Any]]:
    content = (structured or {}).get("content") or {}
    items: List[Dict[str, Any]] = []
    for content_key, memory_type in REVIEW_MEMORY_TYPES.items():
        for item in content.get(content_key) or []:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "type": memory_type,
                    "content_key": content_key,
                    "id": str(item.get("id") or ""),
                    "before": str(item.get("content") or "").strip(),
                    "evidence": item.get("evidence") or {},
                }
            )
    return items


def find_structured_diary_item(structured: Dict | None, memory_type: str, item_id: str) -> Dict[str, Any]:
    target_key = normalized_review_content_key(memory_type)
    target_id = (item_id or "").strip()
    for item in structured_diary_items(structured):
        if item["content_key"] != target_key:
            continue
        if not target_id or item["id"] == target_id:
            return item
    return {}


def memory_links_from_payload(diary_payload: Dict) -> Dict[str, List[str]]:
    links = default_review_memory_links()
    raw = diary_payload.get("memory_links") or {}
    if isinstance(raw, dict):
        for key in links:
            values = raw.get(key) or []
            if isinstance(values, list):
                links[key] = [str(item) for item in values if item]
    return links


def add_memory_link(memory_links: Dict[str, List[str]], memory_type: str, memory_id: str) -> None:
    content_key = normalized_review_content_key(memory_type)
    if memory_id and memory_id not in memory_links[content_key]:
        memory_links[content_key].append(memory_id)


def review_document_is_writable(document: str) -> bool:
    text = (document or "").strip()
    if not text:
        return False
    return "暂不形成明确长期记忆" not in text and "信息不足" not in text


def evidence_source_and_modalities(evidence: Dict, fallback_modalities: Dict) -> tuple[str, Dict[str, bool]]:
    evidence = evidence or {}
    availability = evidence.get("availability") if isinstance(evidence.get("availability"), dict) else {}
    source = "diary_user" if (evidence.get("user_diary") or "").strip() else "conversation"
    return (
        source,
        {
            "text": bool(availability.get("text", fallback_modalities.get("text", True))),
            "audio": bool(availability.get("audio", fallback_modalities.get("audio", False))),
            "video": bool(availability.get("video", fallback_modalities.get("video", False))),
        },
    )


def linked_memory_locked(
    memory_ids: List[str],
    user_id: str,
    memory_type: str,
    document: str,
    before: str = "",
) -> Dict | None:
    candidates = [item for item in (document, before) if item]
    for memory_id in memory_ids:
        current = long_memory.collection.get(ids=[memory_id], include=["documents", "metadatas"])
        if not current.get("ids"):
            continue
        metadata = dict((current.get("metadatas") or [{}])[0] or {})
        if metadata.get("user_id") != user_id or metadata.get("type") != memory_type:
            continue
        old_document = (current.get("documents") or [""])[0]
        if len(memory_ids) == 1:
            return {"id": memory_id, "document": old_document, "metadata": metadata}
        old_normalized = normalize_memory_document(old_document)
        for candidate in candidates:
            candidate_normalized = normalize_memory_document(candidate)
            if candidate_normalized and SequenceMatcher(None, old_normalized, candidate_normalized).ratio() >= 0.82:
                return {"id": memory_id, "document": old_document, "metadata": metadata}
    return None


def find_existing_review_memory_locked(
    document: str,
    user_id: str,
    memory_type: str,
    memory_links: Dict[str, List[str]],
    before: str = "",
) -> Dict | None:
    content_key = normalized_review_content_key(memory_type)
    linked = linked_memory_locked(memory_links.get(content_key, []), user_id, memory_type, document, before=before)
    if linked:
        return linked
    if before:
        duplicate = find_duplicate_memory_locked(before, user_id=user_id, memory_type=memory_type)
        if duplicate:
            return duplicate
    duplicate = find_duplicate_memory_locked(document, user_id=user_id, memory_type=memory_type)
    if duplicate:
        return duplicate
    return find_merge_candidate_locked(document, user_id=user_id, memory_type=memory_type)


def max_importance_for_type_locked(user_id: str, memory_type: str, fallback: float) -> float:
    items = long_memory.list_memories(
        limit=max(long_memory.collection.count(), 1),
        user_id=user_id or None,
        memory_type=memory_type,
    )
    values = [
        float((item.get("metadata") or {}).get("importance_0", (item.get("metadata") or {}).get("importance", fallback)))
        for item in items
    ]
    return max(values, fallback) if values else fallback


def update_review_memory_metadata(
    memory_id: str,
    existing: Dict,
    *,
    document: str | None = None,
    confidence: float | None = None,
    importance_0: float | None = None,
    confirmation: str | None = None,
    source: str | None = None,
    emotion: Dict[str, float] | None = None,
    modalities: Dict[str, bool] | None = None,
) -> Dict:
    metadata = dict(existing.get("metadata") or {})
    if confidence is not None:
        metadata["confidence"] = long_memory.clamp(confidence)
    if importance_0 is not None:
        metadata["importance_0"] = long_memory.clamp(importance_0)
        metadata["importance"] = metadata["importance_0"]
    if confirmation:
        metadata["confirmation"] = confirmation
    if source:
        metadata["source"] = source
    if emotion is not None:
        metadata["has_emotion"] = True
        metadata["valence"] = max(-1.0, min(1.0, float(emotion.get("valence", 0.0))))
        metadata["arousal"] = long_memory.clamp(emotion.get("arousal", 0.0))
    if modalities is not None:
        for key in ("text", "audio", "video"):
            metadata[key] = bool(modalities.get(key, False))
            metadata[f"{key}_available"] = bool(modalities.get(key, False))
    long_memory.update_memory(memory_id, document=document, metadata_updates=metadata)
    return metadata


def create_review_memory(
    *,
    document: str,
    date_key: str,
    timestamp: str,
    user_id: str,
    memory_type: str,
    source: str,
    emotion: Dict[str, float],
    modalities: Dict[str, bool],
    confirmation: str,
    confidence: float = 0.9,
    importance: float | None = None,
) -> Dict:
    memory = long_memory.create_memory(
        document=document,
        date=date_key,
        timestamp=timestamp,
        user="user",
        user_id=user_id,
        type=memory_type,
        source=source,
        has_emotion=True,
        valence=emotion.get("valence", 0.0),
        arousal=emotion.get("arousal", 0.0),
        confidence=confidence,
        importance=importance,
        text=modalities.get("text", False),
        audio=modalities.get("audio", False),
        video=modalities.get("video", False),
        confirmation=confirmation,
    )
    memory_id = long_memory.add_memory(memory)
    return {"id": memory_id, "document": document, "metadata": memory["metadata"]}


def process_diary_review_item_locked(
    item: Dict,
    *,
    date_key: str,
    timestamp: str,
    user_id: str,
    emotion: Dict[str, float],
    fallback_modalities: Dict[str, bool],
    memory_links: Dict[str, List[str]],
) -> Dict:
    action = (item.get("action") or "confirm").strip().lower()
    memory_type = review_memory_type(item.get("type") or "event")
    content_key = normalized_review_content_key(memory_type)
    before = str(item.get("before") or "").strip()
    after = str(item.get("after") or before).strip()
    document = after if action in {"correct", "append"} else before
    evidence = item.get("evidence") or {}
    source, modalities = evidence_source_and_modalities(evidence, fallback_modalities)
    result = {
        "type": memory_type,
        "content_key": content_key,
        "id": str(item.get("id") or ""),
        "action": action,
        "before": before,
        "after": after,
        "memory_id": "",
        "written": False,
        "skipped": False,
    }
    if action not in {"confirm", "correct", "delete", "append"}:
        result.update({"skipped": True, "reason": "invalid action"})
        return result
    if action != "delete" and not review_document_is_writable(document):
        result.update({"skipped": True, "reason": "empty or low-information document"})
        return result

    existing = find_existing_review_memory_locked(
        document,
        user_id=user_id,
        memory_type=memory_type,
        memory_links=memory_links,
        before=before,
    )
    if action == "delete":
        if not existing:
            result.update({"skipped": True, "reason": "no linked memory to reduce"})
            return result
        memory_id = existing["id"]
        old_metadata = existing.get("metadata") or {}
        confidence = float(old_metadata.get("confidence", 0.7)) * 0.5
        importance_0 = float(old_metadata.get("importance_0", old_metadata.get("importance", 0.5))) * 0.5
        metadata = update_review_memory_metadata(
            memory_id,
            existing,
            confidence=confidence,
            importance_0=importance_0,
            confirmation="corrected",
        )
        add_memory_link(memory_links, memory_type, memory_id)
        result.update({"written": True, "memory_id": memory_id, "metadata": metadata})
        return result

    if action == "confirm":
        if existing:
            memory_id = existing["id"]
            old_metadata = existing.get("metadata") or {}
            old_importance = float(old_metadata.get("importance_0", old_metadata.get("importance", 0.0)))
            old_confidence = float(old_metadata.get("confidence", 0.0))
            metadata = update_review_memory_metadata(
                memory_id,
                existing,
                confidence=max(old_confidence, 0.9),
                importance_0=min(1.0, old_importance + 0.05),
                confirmation="confirmed",
                source=source,
                emotion=emotion,
                modalities=modalities,
            )
            add_memory_link(memory_links, memory_type, memory_id)
            result.update({"written": True, "memory_id": memory_id, "metadata": metadata, "merged": True})
            return result
        created = create_review_memory(
            document=document,
            date_key=date_key,
            timestamp=timestamp,
            user_id=user_id,
            memory_type=memory_type,
            source=source,
            emotion=emotion,
            modalities=modalities,
            confirmation="confirmed",
            confidence=0.9,
        )
        add_memory_link(memory_links, memory_type, created["id"])
        result.update({"written": True, "memory_id": created["id"], "metadata": created["metadata"]})
        return result

    confirmation = "corrected"
    if existing and action == "correct":
        memory_id = existing["id"]
        old_metadata = existing.get("metadata") or {}
        fallback_importance = float(old_metadata.get("importance_0", old_metadata.get("importance", 0.0)))
        importance_0 = max_importance_for_type_locked(user_id, memory_type, fallback=fallback_importance)
        metadata = update_review_memory_metadata(
            memory_id,
            existing,
            document=document,
            confidence=0.9,
            importance_0=importance_0,
            confirmation=confirmation,
            source=source,
            emotion=emotion,
            modalities=modalities,
        )
        add_memory_link(memory_links, memory_type, memory_id)
        result.update({"written": True, "memory_id": memory_id, "metadata": metadata, "merged": True})
        return result

    duplicate = find_duplicate_memory_locked(document, user_id=user_id, memory_type=memory_type)
    if duplicate:
        memory_id = duplicate["id"]
        add_memory_link(memory_links, memory_type, memory_id)
        result.update({"written": False, "memory_id": memory_id, "duplicate": True})
        return result
    created = create_review_memory(
        document=document,
        date_key=date_key,
        timestamp=timestamp,
        user_id=user_id,
        memory_type=memory_type,
        source=source,
        emotion=emotion,
        modalities=modalities,
        confirmation=confirmation,
        confidence=0.9,
    )
    add_memory_link(memory_links, memory_type, created["id"])
    result.update({"written": True, "memory_id": created["id"], "metadata": created["metadata"]})
    return result


def build_review_items(payload: Dict, diary_payload: Dict) -> List[Dict]:
    structured = diary_payload.get("ai_structured") or {}
    payload_items = payload.get("items")
    if isinstance(payload_items, list) and payload_items:
        items = []
        for raw in payload_items:
            if not isinstance(raw, dict):
                continue
            memory_type = review_memory_type(raw.get("type") or "event")
            existing = find_structured_diary_item(structured, memory_type, str(raw.get("id") or ""))
            before = str(raw.get("before") or existing.get("before") or "").strip()
            after = str(raw.get("after") or raw.get("correction") or before).strip()
            evidence = raw.get("evidence") or existing.get("evidence") or {}
            items.append({**raw, "type": memory_type, "before": before, "after": after, "evidence": evidence})
        return items

    action = (payload.get("action") or "").strip().lower()
    correction = (payload.get("correction") or payload.get("after") or "").strip()
    memory_type = review_memory_type(payload.get("type") or "event")
    item_id = str(payload.get("id") or "").strip()
    if action == "confirm":
        return [
            {
                "type": item["type"],
                "id": item["id"],
                "action": "confirm",
                "before": item["before"],
                "after": item["before"],
                "evidence": item.get("evidence") or {},
            }
            for item in structured_diary_items(structured)
        ]
    existing = find_structured_diary_item(structured, memory_type, item_id)
    return [
        {
            "type": memory_type,
            "id": item_id or existing.get("id", ""),
            "action": action,
            "before": existing.get("before", ""),
            "after": correction,
            "evidence": existing.get("evidence") or {},
        }
    ]


def handle_diary_review(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    date_key = payload.get("date") or memory_date_from_payload("")
    action = (payload.get("action") or "").strip().lower()
    correction = (payload.get("correction") or "").strip()
    if action not in {"confirm", "correct", "delete", "append"}:
        return {"ok": False, "error": "invalid action", **get_diary_index_payload(date_key, user_id=user_id)}
    if action in {"correct", "append"} and not correction and not payload.get("items"):
        return {"ok": False, "error": "missing correction", **get_diary_index_payload(date_key, user_id=user_id)}

    diary_payload = get_diary_payload(date_key, user_id=user_id)
    if not diary_payload.get("ai_review_available"):
        return {"ok": False, "error": "ai diary is not pending review", **get_diary_index_payload(date_key, user_id=user_id)}

    snapshot = snapshot_for_diary_review(date_key, user_id=user_id)
    emotion = emotion_for_memory_write(snapshot)
    modalities = snapshot.get("modalities") or {"text": True, "audio": False, "video": False}
    timestamp = snapshot.get("timestamp") or normalize_timestamp_to_china("")
    memory_links = memory_links_from_payload(diary_payload)
    review_items = build_review_items(payload, diary_payload)
    if not review_items:
        return {"ok": False, "error": "missing review items", **get_diary_index_payload(date_key, user_id=user_id)}

    with LONG_MEMORY_LOCK:
        results = [
            process_diary_review_item_locked(
                item,
                date_key=date_key,
                timestamp=timestamp,
                user_id=user_id,
                emotion=emotion,
                fallback_modalities=modalities,
                memory_links=memory_links,
            )
            for item in review_items
        ]
    final_status = "corrected" if any(item.get("action") != "confirm" for item in results) else "confirmed"
    mark_ai_diary_reviewed(
        date_key,
        final_status,
        correction=correction,
        memory_links=memory_links,
        review_items=results,
        user_id=user_id,
    )
    with MEMORY_LOCK:
        MEMORY_STATE["pending_diary_dates"].discard((user_id, date_key))
    clear_pending_ai_diary_date(user_id, date_key)
    return {
        "ok": True,
        "action": action,
        "memory": {"links": memory_links, "items": results},
        **get_diary_index_payload(date_key, user_id=user_id),
    }


def handle_memory_query(params: Dict[str, list[str]]) -> Dict:
    query = (params.get("query") or [""])[0].strip()
    user_id = (params.get("_auth_user_id") or params.get("user_id") or params.get("userId") or [DEFAULT_MEMORY_USER_ID])[0]
    memory_type = (params.get("type") or [""])[0]
    try:
        k = int((params.get("k") or ["10"])[0])
    except ValueError:
        k = 10
    k = max(1, min(k, 50))
    if query:
        items = recall_long_memories(query, k=k, user_id=user_id, memory_type=memory_type)
        mode = "recall"
    else:
        items = list_long_memories(limit=k, user_id=user_id, memory_type=memory_type)
        mode = "list"
    with LONG_MEMORY_LOCK:
        count = long_memory.collection.count()
    filtered_count = count_long_memories(user_id=user_id, memory_type=memory_type)
    return {
        "mode": mode,
        "query": query,
        "k": k,
        "user_id": user_id,
        "count": count,
        "filtered_count": filtered_count,
        "items": items,
    }


def handle_memory_delete(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    memory_id = (payload.get("id") or "").strip()
    if not memory_id:
        return {"ok": False, "error": "missing id"}
    with LONG_MEMORY_LOCK:
        current = long_memory.collection.get(ids=[memory_id], include=["metadatas"])
        metadata = dict((current.get("metadatas") or [{}])[0] or {}) if current.get("ids") else {}
        if not metadata or metadata.get("user_id") != user_id:
            return {"ok": False, "error": "memory not found"}
        long_memory.delete_memory(memory_id)
        count = long_memory.collection.count()
    return {"ok": True, "id": memory_id, "user_id": user_id, "count": count}


def handle_memory_clear(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    memory_type = (payload.get("type") or "").strip()
    with LONG_MEMORY_LOCK:
        items = long_memory.list_memories(
            limit=max(long_memory.collection.count(), 1),
            user_id=user_id or None,
            memory_type=memory_type or None,
        )
        for item in items:
            long_memory.delete_memory(item["id"])
        count = long_memory.collection.count()
    return {
        "ok": True,
        "deleted": len(items),
        "user_id": user_id,
        "type": memory_type,
        "count": count,
    }


def clear_memories_for_user(user_id: str) -> Dict:
    with LONG_MEMORY_LOCK:
        items = long_memory.list_memories(
            limit=max(long_memory.collection.count(), 1),
            user_id=user_id,
        )
        for item in items:
            long_memory.delete_memory(item["id"])
        count = long_memory.collection.count()
    return {"user_id": user_id, "deleted": len(items), "count": count}


def handle_user_clear(payload: Dict) -> Dict:
    user_ids = [current_user_id(payload)]
    if payload.get("include_local_user", True) and DEFAULT_MEMORY_USER_ID not in user_ids:
        user_ids.append(DEFAULT_MEMORY_USER_ID)

    memory_results = [clear_memories_for_user(user_id) for user_id in user_ids]
    diary_results = [delete_diary_data(user_id) for user_id in user_ids]
    chat_results = [{"user_id": user_id, "deleted": delete_chat_messages(user_id)} for user_id in user_ids]
    pending_diary_results = [
        {"user_id": user_id, "deleted": delete_pending_ai_diary_dates(user_id)}
        for user_id in user_ids
    ]

    with MEMORY_LOCK:
        for user_id in user_ids:
            for key in list(MEMORY_STATE["latest_by_date"].keys()):
                if key.startswith(f"{user_id}:"):
                    MEMORY_STATE["latest_by_date"].pop(key, None)
            MEMORY_STATE["pending_diary_dates"] = {
                item
                for item in MEMORY_STATE["pending_diary_dates"]
                if not (isinstance(item, tuple) and item[0] == user_id)
            }

    return {
        "ok": True,
        "user_ids": user_ids,
        "memory": memory_results,
        "diary": diary_results,
        "chat": chat_results,
        "pending_diary": pending_diary_results,
    }


def handle_memory_decay(payload: Dict) -> Dict:
    threshold = payload.get("threshold", 0.05)
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        threshold = 0.05
    with LONG_MEMORY_LOCK:
        actions = long_memory.apply_decay(threshold=threshold, dry_run=False)
        count = long_memory.collection.count()
    return {"ok": True, "threshold": threshold, "actions": actions, "count": count}
