import re
import threading
import time
from difflib import SequenceMatcher
from typing import Dict

from agent.replies import agent_payload, decide_memory_update, generate_agent_reply
from core.config import AI_DIARY_UPDATE_INTERVAL, SELF_MM_MODEL_PATH
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


EMOTION_RUNNER = None
MEMORY_LOCK = threading.Lock()
LONG_MEMORY_LOCK = threading.Lock()
DEFAULT_MEMORY_USER_ID = "local_user"
MEMORY_STATE = {
    "dirty_dates": set(),
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
    with LONG_MEMORY_LOCK:
        results = long_memory.recall(
            query,
            k=k,
            user_id=user_id or None,
            memory_type=memory_type or None,
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
        MEMORY_STATE["dirty_dates"].add((user_id, date_key))


def refresh_ai_diary(date_key: str, user_id: str = DEFAULT_MEMORY_USER_ID) -> bool:
    if date_key >= memory_date_from_payload(""):
        return False
    if read_ai_diary_meta(date_key, user_id=user_id).get("status") in {"pending", "confirmed", "corrected"}:
        with MEMORY_LOCK:
            MEMORY_STATE["dirty_dates"].discard((user_id, date_key))
        return False
    with MEMORY_LOCK:
        snapshot = MEMORY_STATE["latest_by_date"].get(memory_snapshot_key(user_id, date_key))
        if snapshot is None:
            return False
    refreshed = refresh_ai_diary_from_snapshot(date_key, snapshot, user_id=user_id)
    with MEMORY_LOCK:
        MEMORY_STATE["dirty_dates"].discard((user_id, date_key))
    return refreshed


def ai_diary_worker() -> None:
    while True:
        time.sleep(max(20, AI_DIARY_UPDATE_INTERVAL))
        today = memory_date_from_payload("")
        with MEMORY_LOCK:
            dirty_dates = [(user_id, date_key) for user_id, date_key in MEMORY_STATE["dirty_dates"] if date_key < today]
        for user_id, date_key in dirty_dates:
            try:
                refresh_ai_diary(date_key, user_id=user_id)
            except Exception:
                continue


def analyze_and_reply(payload: Dict, should_reply: bool = True) -> Dict:
    user_id = current_user_id(payload)
    user_text, text_source = resolve_text_input(payload)
    history = payload.get("history", []) or []
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
            MEMORY_STATE["dirty_dates"].add((user_id, date_key))
    return response


def handle_diary_refresh(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    date_key = payload.get("date") or memory_date_from_payload("")
    refreshed = refresh_ai_diary(date_key, user_id=user_id)
    return {"ok": refreshed, **get_diary_index_payload(date_key, user_id=user_id)}


def diary_review_document(date_key: str, action: str, ai_markdown: str, correction: str) -> str:
    if action == "correct":
        return f"用户修正了 {date_key} 的AI记：{correction.strip()}"
    excerpt = re.sub(r"\s+", " ", (ai_markdown or "").strip())
    if len(excerpt) > 90:
        excerpt = f"{excerpt[:90]}..."
    return f"用户确认 {date_key} 的AI记准确：{excerpt}"


def snapshot_for_diary_review(date_key: str, user_id: str = DEFAULT_MEMORY_USER_ID) -> Dict:
    with MEMORY_LOCK:
        snapshot = MEMORY_STATE["latest_by_date"].get(memory_snapshot_key(user_id, date_key)) or {}
    return snapshot


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


def handle_diary_review(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    date_key = payload.get("date") or memory_date_from_payload("")
    action = (payload.get("action") or "").strip().lower()
    correction = (payload.get("correction") or "").strip()
    if action not in {"confirm", "correct"}:
        return {"ok": False, "error": "invalid action", **get_diary_index_payload(date_key, user_id=user_id)}
    if action == "correct" and not correction:
        return {"ok": False, "error": "missing correction", **get_diary_index_payload(date_key, user_id=user_id)}

    diary_payload = get_diary_payload(date_key, user_id=user_id)
    if not diary_payload.get("ai_review_available"):
        return {"ok": False, "error": "ai diary is not pending review", **get_diary_index_payload(date_key, user_id=user_id)}

    snapshot = snapshot_for_diary_review(date_key, user_id=user_id)
    emotion = emotion_for_memory_write(snapshot)
    modalities = snapshot.get("modalities") or {"text": True, "audio": False, "video": False}
    timestamp = snapshot.get("timestamp") or normalize_timestamp_to_china("")
    confirmation = "corrected" if action == "correct" else "confirmed"
    document = diary_review_document(date_key, action, diary_payload.get("ai_raw_markdown", ""), correction)
    confidence = 0.9 if action == "correct" else 0.85
    memory = long_memory.create_memory(
        document=document,
        date=date_key,
        timestamp=timestamp,
        user="user",
        user_id=user_id,
        type="summary",
        source="diary_user",
        has_emotion=bool(snapshot.get("emotion")),
        valence=emotion.get("valence", 0.0),
        arousal=emotion.get("arousal", 0.0),
        confidence=confidence,
        text=modalities.get("text", False),
        audio=modalities.get("audio", False),
        video=modalities.get("video", False),
        confirmation=confirmation,
    )
    with LONG_MEMORY_LOCK:
        memory_id = long_memory.add_memory(memory)
    mark_ai_diary_reviewed(date_key, confirmation, correction=correction, memory_id=memory_id, user_id=user_id)
    with MEMORY_LOCK:
        MEMORY_STATE["dirty_dates"].discard((user_id, date_key))
    return {
        "ok": True,
        "action": action,
        "memory": {"id": memory_id, "document": memory["document"], "metadata": memory["metadata"]},
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

    with MEMORY_LOCK:
        for user_id in user_ids:
            for key in list(MEMORY_STATE["latest_by_date"].keys()):
                if key.startswith(f"{user_id}:"):
                    MEMORY_STATE["latest_by_date"].pop(key, None)
            MEMORY_STATE["dirty_dates"] = {
                item for item in MEMORY_STATE["dirty_dates"] if not (isinstance(item, tuple) and item[0] == user_id)
            }

    return {
        "ok": True,
        "user_ids": user_ids,
        "memory": memory_results,
        "diary": diary_results,
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
