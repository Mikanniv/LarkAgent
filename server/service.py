from __future__ import annotations

from typing import Any, Dict

from agent.replies import agent_payload, generate_agent_reply
from core.config import CHAT_CONTEXT_LIMIT, CHAT_DISPLAY_LIMIT, SELF_MM_MODEL_PATH
from core.utils import memory_date_from_payload, normalize_timestamp_to_china
from diary.store import delete_diary_data, delete_user_diary, get_diary_index_payload, save_user_diary
from emotion.mapping import FineGrainedEmotion
from emotion.media import resolve_text_input
from emotion.models import SelfMMRunner
from memory import v2 as memory_v2
from memory.pipeline_v2 import list_ai_diary_batches, record_complete_interaction, review_ai_diary_item
from storage.chat_store import (
    add_chat_message,
    delete_ai_diary_v2_batches,
    delete_chat_messages,
    delete_runtime_state_for_user,
    list_chat_messages,
    list_context_messages,
)


EMOTION_RUNNER = None
DEFAULT_MEMORY_USER_ID = "local_user"


def current_user_id(payload: Dict | None = None) -> str:
    payload = payload or {}
    user_id = payload.get("user_id") or payload.get("userId") or DEFAULT_MEMORY_USER_ID
    return str(user_id).strip() or DEFAULT_MEMORY_USER_ID


def get_emotion_runner() -> SelfMMRunner:
    global EMOTION_RUNNER
    if EMOTION_RUNNER is None:
        EMOTION_RUNNER = SelfMMRunner(SELF_MM_MODEL_PATH)
    return EMOTION_RUNNER


def analyze_and_reply(payload: Dict, should_reply: bool = True) -> Dict:
    user_id = current_user_id(payload)
    user_text, text_source = resolve_text_input(payload)
    history = list_context_messages(user_id, limit=CHAT_CONTEXT_LIMIT)
    if not history:
        history = (payload.get("history", []) or [])[-CHAT_CONTEXT_LIMIT:]
    proactive = bool(payload.get("proactive"))
    timestamp = normalize_timestamp_to_china(payload.get("timestamp", ""))
    runner = get_emotion_runner()
    raw_scores = runner.predict_text(user_text or " ")
    raw_scores = {
        "text": float(raw_scores.get("text", 0.0)),
        "fusion": float(raw_scores.get("fusion", 0.0)),
    }
    if proactive:
        raw_scores["proactive_reason"] = (
            payload.get("proactive_reason") or payload.get("proactiveReason") or "主动回应"
        )

    # v2.0 only exposes SELF-MM text/fusion scores. Legacy VA labels are not persisted.
    emotion = FineGrainedEmotion(label="", valence=0.0, arousal=0.0, confidence=0.0)
    agent_reply = ""
    agent_source = "none"
    agent_error = ""
    recalled = {"memories": [], "strategies": []}
    pipeline_result: Dict[str, Any] = {}

    if should_reply:
        memory_query = user_text or raw_scores.get("proactive_reason") or "当前陪伴情境"
        recalled = memory_v2.recall_for_chat(user_id, memory_query, memory_k=3, strategy_k=2)
        agent_reply, agent_source, agent_error = generate_agent_reply(
            user_text,
            emotion,
            raw_scores,
            history,
            memories=recalled["memories"],
            strategies=recalled["strategies"],
            proactive=proactive,
        )
        if user_text:
            add_chat_message(user_id, "user", user_text, created_at=timestamp)
        if agent_reply:
            add_chat_message(user_id, "assistant", agent_reply, created_at=timestamp)
        if user_text and agent_reply and not proactive:
            pipeline_result = record_complete_interaction(user_id, timestamp)

    return {
        "model": {
            "name": runner.metadata().get("name", "SELF-MM"),
            "modalities": ["text"],
        },
        "scores": raw_scores,
        "agent": agent_payload(agent_reply, agent_source, agent_error),
        "long_memory": {
            "user_id": user_id,
            "recalled": recalled,
            "pipeline": pipeline_result,
            "unread": memory_v2.unread_counts(user_id),
        },
        "modal_inputs": {
            "text_available": bool(user_text),
            "text_source": text_source,
            "audio_available": False,
            "video_available": False,
        },
        "chat_history": list_chat_messages(user_id, limit=CHAT_DISPLAY_LIMIT),
        "timestamp": timestamp,
    }


def handle_diary_user(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    date_key = payload.get("date") or memory_date_from_payload("")
    markdown = (payload.get("markdown") or "").strip()
    if not markdown:
        return {"ok": False, "error": "empty diary", **get_diary_index_payload(date_key, user_id=user_id)}
    return save_user_diary(date_key, markdown, user_id=user_id)


def handle_diary_user_delete(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    date_key = payload.get("date") or memory_date_from_payload("")
    return delete_user_diary(date_key, user_id=user_id)


def handle_chat_history(params: Dict[str, list[str]]) -> Dict:
    user_id = (
        params.get("_auth_user_id")
        or params.get("user_id")
        or params.get("userId")
        or [DEFAULT_MEMORY_USER_ID]
    )[0]
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


def handle_memory_v2_query(params: Dict[str, list[str]]) -> Dict:
    user_id = (
        params.get("_auth_user_id")
        or params.get("user_id")
        or params.get("userId")
        or [DEFAULT_MEMORY_USER_ID]
    )[0]
    return memory_v2.hierarchy_payload(user_id)


def handle_memory_v2_read(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    layer = str(payload.get("layer") or "").strip().lower()
    memory_id = str(payload.get("id") or "").strip()
    if layer not in memory_v2.LAYERS or not memory_id:
        return {"ok": False, "error": "invalid layer or id", **memory_v2.hierarchy_payload(user_id)}
    item = memory_v2.mark_seen(layer, user_id, memory_id)
    if not item:
        return {"ok": False, "error": "memory not found", **memory_v2.hierarchy_payload(user_id)}
    return {"ok": True, "item": item, **memory_v2.hierarchy_payload(user_id)}


def handle_ai_diary_v2_query(params: Dict[str, list[str]]) -> Dict:
    user_id = (
        params.get("_auth_user_id")
        or params.get("user_id")
        or params.get("userId")
        or [DEFAULT_MEMORY_USER_ID]
    )[0]
    date_key = (params.get("date") or [""])[0].strip()
    return list_ai_diary_batches(user_id, date_key=date_key)


def handle_ai_diary_v2_review(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    batch_id = str(payload.get("batch_id") or "").strip()
    observation_id = str(payload.get("observation_id") or payload.get("id") or "").strip()
    action = str(payload.get("action") or "").strip().lower()
    revised_content = str(
        payload.get("revised_content") or payload.get("correction") or ""
    ).strip()
    if action not in {"confirm", "revise", "delete"}:
        return {"ok": False, "error": "invalid action"}
    if not batch_id or not observation_id:
        return {"ok": False, "error": "missing batch_id or observation_id"}
    if action == "revise" and not revised_content:
        return {"ok": False, "error": "missing revised_content"}
    try:
        return review_ai_diary_item(
            user_id,
            batch_id,
            observation_id,
            action,
            revised_content=revised_content,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def handle_user_clear(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    return {
        "ok": True,
        "user_id": user_id,
        "diary": delete_diary_data(user_id),
        "chat_deleted": delete_chat_messages(user_id),
        "memory_v2_deleted": memory_v2.clear_user(user_id),
        "ai_diary_v2_deleted": delete_ai_diary_v2_batches(user_id),
        "runtime_v2_deleted": delete_runtime_state_for_user(user_id),
    }
