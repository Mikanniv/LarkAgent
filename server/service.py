from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict

from agent.replies import agent_payload, generate_agent_reply
from core.config import CHAT_CONTEXT_LIMIT, CHAT_DISPLAY_LIMIT, SELF_MM_MODEL_PATH
from core.utils import memory_date_from_payload, normalize_timestamp_to_china, now_china
from diary.store import delete_diary_data, delete_user_diary, get_diary_index_payload, save_user_diary
from emotion.mapping import FineGrainedEmotion
from agent.asr import transcribe_audio
from emotion.media import (
    build_audio_tensor_from_media,
    build_video_tensor_from_media,
    resolve_payload_media_path,
    resolve_text_input,
)
from emotion.models import SelfMMRunner
from memory import v2 as memory_v2
from memory.pipeline_v2 import list_ai_diary_batches, record_complete_interaction, review_ai_diary_item
from storage.chat_store import (
    add_chat_message,
    add_emotion_record,
    delete_ai_diary_v2_batches,
    delete_chat_messages,
    delete_emotion_records,
    delete_runtime_state_for_user,
    list_chat_messages,
    list_context_messages,
    list_emotion_records,
)


EMOTION_RUNNER = None
DEFAULT_MEMORY_USER_ID = "local_user"
MAX_ATTACHMENTS = 9
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS_TOTAL_BYTES = 25 * 1024 * 1024


def normalize_attachments(payload: Dict) -> list[Dict[str, Any]]:
    items = payload.get("attachments") or []
    if not isinstance(items, list):
        return []
    result = []
    total = 0
    for item in items[:MAX_ATTACHMENTS]:
        if not isinstance(item, dict):
            continue
        mime_type = str(item.get("type") or "").lower()
        data = str(item.get("data") or "")
        if not (mime_type.startswith("image/") or mime_type.startswith("audio/")) or not data.startswith(f"data:{mime_type};base64,"):
            continue
        encoded = data.split(",", 1)[-1]
        estimated_size = max(0, len(encoded.rstrip("=")) * 3 // 4)
        try:
            declared_size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            declared_size = 0
        size = max(declared_size, estimated_size)
        if size > MAX_ATTACHMENT_BYTES or total + size > MAX_ATTACHMENTS_TOTAL_BYTES:
            continue
        total += size
        result.append({"name": str(item.get("name") or "媒体文件"), "type": mime_type, "size": size, "data": data})
    return result


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
    attachments = normalize_attachments(payload)
    uploaded_audio = next((item for item in attachments if item["type"].startswith("audio/")), None)
    if uploaded_audio and not payload.get("audio_data"):
        payload["audio_data"] = uploaded_audio["data"]
    user_text, text_source = resolve_text_input(payload)
    audio_path, temporary_audio = resolve_payload_media_path(payload, "audio")
    asr_result: Dict[str, Any] = {}
    if audio_path is not None and not user_text:
        try:
            asr_result = transcribe_audio(audio_path)
        except Exception:
            if temporary_audio:
                audio_path.unlink(missing_ok=True)
            raise
        user_text = str(asr_result.get("text") or "").strip()
        text_source = "asr"
    if audio_path is not None and not user_text:
        raise ValueError("没有从录音中识别出可发送的文字。")
    history = list_context_messages(user_id, limit=CHAT_CONTEXT_LIMIT)
    if not history:
        history = (payload.get("history", []) or [])[-CHAT_CONTEXT_LIMIT:]
    proactive = bool(payload.get("proactive"))
    timestamp = normalize_timestamp_to_china(payload.get("timestamp", ""))
    runner = get_emotion_runner()
    audio_tensor, audio_info = build_audio_tensor_from_media(audio_path)
    video_tensor, _ = build_video_tensor_from_media(None)
    if bool(audio_info.get("available")):
        predicted = runner.predict(user_text or " ", audio_tensor, video_tensor)
        raw_scores = {
            "text": float(predicted.get("text", 0.0)),
            "audio": float(predicted.get("audio", 0.0)),
            "fusion": float(predicted.get("fusion", 0.0)),
        }
    else:
        predicted = runner.predict_text(user_text or " ")
        raw_scores = {
            "text": float(predicted.get("text", 0.0)),
            "audio": 0.0,
            "fusion": float(predicted.get("fusion", 0.0)),
        }
    if proactive:
        raw_scores["proactive_reason"] = (
            payload.get("proactive_reason") or payload.get("proactiveReason") or "主动回应"
        )
    elif user_text:
        add_emotion_record(user_id, raw_scores, audio_available=bool(audio_info.get("available")), created_at=timestamp)

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
            attachments=attachments,
        )
        if user_text:
            add_chat_message(
                user_id, "user", user_text, created_at=timestamp,
                attachments=[{"name": item["name"], "type": item["type"], "size": item["size"]} for item in attachments],
            )
        if agent_reply:
            add_chat_message(user_id, "assistant", agent_reply, created_at=timestamp)
        if user_text and agent_reply and not proactive:
            pipeline_result = record_complete_interaction(user_id, timestamp)

    response = {
        "model": {
            "name": runner.metadata().get("name", "SELF-MM"),
            "modalities": ["text", "audio"] if audio_info.get("available") else ["text"],
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
            "asr_text": asr_result.get("text", ""),
            "asr_model": asr_result.get("model", ""),
            "audio_available": bool(audio_info.get("available")),
            "audio": audio_info,
            "video_available": False,
        },
        "chat_history": list_chat_messages(user_id, limit=CHAT_DISPLAY_LIMIT),
        "timestamp": timestamp,
    }
    if temporary_audio and audio_path is not None:
        audio_path.unlink(missing_ok=True)
    return response


def handle_asr_segment(payload: Dict) -> Dict:
    """Transcribe one independently decodable recording segment without chatting."""
    audio_path, temporary_audio = resolve_payload_media_path(payload, "audio")
    if audio_path is None:
        raise ValueError("missing audio segment")
    try:
        result = transcribe_audio(audio_path)
        return {
            "ok": True,
            "segment_id": str(payload.get("segment_id") or ""),
            "sequence": int(payload.get("sequence") or 0),
            "text": str(result.get("text") or ""),
            "model": str(result.get("model") or ""),
            "final": bool(payload.get("final")),
        }
    finally:
        if temporary_audio:
            audio_path.unlink(missing_ok=True)


def handle_audio_input(payload: Dict) -> Dict:
    result = handle_asr_segment(payload)
    return {"ok": True, "transcript": result["text"], "asr_model": result["model"]}


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


def handle_emotion_trend_query(params: Dict[str, list[str]]) -> Dict:
    user_id = (params.get("_auth_user_id") or params.get("user_id") or [DEFAULT_MEMORY_USER_ID])[0]
    mode = str((params.get("range") or ["one_day"])[0]).strip().lower()
    if mode not in {"one_day", "daily", "weekly", "monthly"}:
        mode = "one_day"
    anchor = str((params.get("anchor") or [""])[0]).strip()
    current = now_china()
    timezone = current.tzinfo
    try:
        if mode == "one_day":
            selected = datetime.strptime(anchor or current.strftime("%Y-%m-%d"), "%Y-%m-%d")
            start, end = selected.replace(tzinfo=timezone), selected.replace(tzinfo=timezone) + timedelta(days=1)
        elif mode == "daily":
            selected = datetime.strptime(anchor or current.strftime("%Y-%m"), "%Y-%m")
            start = selected.replace(tzinfo=timezone)
            end = start.replace(year=start.year + (start.month == 12), month=1 if start.month == 12 else start.month + 1)
        else:
            year = int(anchor or current.year)
            start, end = datetime(year, 1, 1, tzinfo=timezone), datetime(year + 1, 1, 1, tzinfo=timezone)
    except (TypeError, ValueError):
        raise ValueError("无效的趋势时间选择。")
    raw_records = list_emotion_records(user_id, start.isoformat(timespec="seconds"), limit=5000, end_at=end.isoformat(timespec="seconds"))
    if mode == "one_day":
        records = [{**item, "period_label": datetime.fromisoformat(item["created_at"]).strftime("%H:%M:%S")} for item in raw_records]
    else:
        grouped: Dict[str, list[Dict]] = {}
        for item in raw_records:
            created = datetime.fromisoformat(item["created_at"])
            if mode == "daily":
                period_start, key, label = created.replace(hour=0, minute=0, second=0, microsecond=0), created.strftime("%Y-%m-%d"), created.strftime("%m/%d")
            elif mode == "weekly":
                period_start = (created - timedelta(days=created.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
                key, label = period_start.strftime("%G-W%V"), f"第{period_start.strftime('%V')}周"
            else:
                period_start = created.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                key, label = period_start.strftime("%Y-%m"), period_start.strftime("%m月")
            grouped.setdefault(key, []).append({**item, "_start": period_start, "_label": label})
        records = []
        for key, items in grouped.items():
            audio_items = [item for item in items if item["audio_available"]]
            records.append({
                "id": key, "text": sum(item["text"] for item in items) / len(items),
                "audio": sum(item["audio"] for item in audio_items) / len(audio_items) if audio_items else 0.0,
                "fusion": sum(item["fusion"] for item in items) / len(items), "audio_available": bool(audio_items),
                "sample_count": len(items), "created_at": items[0]["_start"].isoformat(timespec="seconds"), "period_label": items[0]["_label"],
            })
        records.sort(key=lambda item: item["created_at"])
    memories = []
    for layer in ("observation", "reflection"):
        for item in memory_v2.list_memories(user_id, layer=layer):
            try:
                created = datetime.fromisoformat(str(item.get("created_at") or "").replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone)
            except ValueError:
                continue
            if start <= created < end:
                memories.append({"id": item["display_id"], "layer": item["layer"], "description": item["description"], "topics": item["topics"], "importance": item["importance"], "confidence": item["confidence"], "created_at": item["created_at"]})
    strategies = [{"id": item["display_id"], "scene": item["scene"], "description": item["description"], "importance": item["importance"], "confidence": item["confidence"], "created_at": item["created_at"]} for item in memory_v2.list_memories(user_id, layer="strategy")[:5]]
    values = [item["fusion"] for item in records]
    summary = {"average": sum(values) / len(values) if values else 0.0, "minimum": min(values) if values else 0.0, "maximum": max(values) if values else 0.0, "change": values[-1] - values[0] if len(values) > 1 else 0.0, "audio_count": sum(1 for item in raw_records if item["audio_available"]), "raw_count": len(raw_records)}
    return {"ok": True, "user_id": user_id, "range": mode, "anchor": anchor, "start_at": start.isoformat(timespec="seconds"), "end_at": end.isoformat(timespec="seconds"), "records": records, "memories": memories, "strategies": strategies, "summary": summary}


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
        "emotion_records_deleted": delete_emotion_records(user_id),
        "memory_v2_deleted": memory_v2.clear_user(user_id),
        "ai_diary_v2_deleted": delete_ai_diary_v2_batches(user_id),
        "runtime_v2_deleted": delete_runtime_state_for_user(user_id),
    }
