from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict

from agent.replies import agent_payload, build_agent_prompt, generate_agent_reply
from agent.attachments import (
    build_multimodal_user_content,
    extract_document_text,
    extract_structured_segments,
    infer_attachment_mime,
    infer_file_type,
    is_supported_attachment,
)
from agent.rag import (
    DEFAULT_RELEVANCE_THRESHOLD,
    build_file_chunks,
    chunk_text,
    recommend_next_chunks,
    retrieve_chunks_with_scores,
    retrieve_relevant_chunks,
    verify_citations,
)
from agent.academic import (
    detect_study_intent,
    format_academic_context,
    generate_academic_advice,
    is_requesting_plan,
)
from agent.agent import call_chat_completion, call_chat_completion_with_tools, chat_api_ready, stream_chat_completion
from core.config import (
    API_AUDIO_INPUT,
    API_IMAGE_INPUT,
    CHAT_CONTEXT_LIMIT,
    CHAT_DISPLAY_LIMIT,
    ENABLE_MULTIMODAL,
    SELF_MM_MODEL_PATH,
)
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
    add_academic_score,
    add_chat_message,
    add_emotion_record,
    add_study_message,
    create_study_session,
    create_user_profile,
    delete_academic_data_for_user,
    delete_ai_diary_v2_batches,
    delete_chat_messages,
    delete_emotion_records,
    delete_library_file,
    delete_runtime_state_for_user,
    delete_study_and_profile_data_for_user,
    delete_study_file,
    delete_user_profile,
    get_academic_profile,
    get_active_profile,
    get_library_file_chunks,
    get_session_linked_chunks,
    get_study_file_chunks,
    get_study_session,
    list_academic_scores,
    list_chat_messages,
    list_context_messages,
    list_emotion_records,
    list_library_files,
    list_session_linked_files,
    list_study_files,
    save_library_file,
    set_session_file_link,
    set_session_linked_files,
    list_study_messages,
    list_study_sessions,
    list_user_profiles,
    mark_profile_chatted,
    profile_has_user_chatted,
    save_study_file,
    set_active_profile,
    update_academic_advice,
    update_user_profile,
    upsert_academic_profile,
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
        name = str(item.get("name") or "媒体文件")
        mime_type = infer_attachment_mime(name, str(item.get("type") or ""))
        data = str(item.get("data") or "")
        if not is_supported_attachment(name, mime_type) or ";base64," not in data or not data.startswith("data:"):
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
        result.append({"name": name, "type": mime_type, "size": size, "data": data})
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

    if ENABLE_MULTIMODAL:
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
        model_info = {
            "name": runner.metadata().get("name", "SELF-MM"),
            "modalities": ["text", "audio"] if audio_info.get("available") else ["text"],
        }
    else:
        audio_info = {"available": False}
        raw_scores = {
            "text": 0.0,
            "audio": 0.0,
            "fusion": 0.0,
        }
        model_info = {
            "name": "TextOnly",
            "modalities": ["text"],
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
    study_intent = None
    ask_study_confirmation = False

    active_profile = get_active_profile(user_id) or get_academic_profile(user_id) or {}
    profile_id = str(payload.get("profile_id") or active_profile.get("id") or "").strip()

    if should_reply:
        if user_text and is_requesting_plan(user_text):
            scores = list_academic_scores(user_id, limit=10)
            agent_reply = generate_academic_advice(active_profile, scores)
            agent_source = "academic_planner"
            agent_error = ""
            if profile_id:
                mark_profile_chatted(user_id, profile_id)
        else:
            study_candidate = detect_study_intent(user_text) if user_text else None
            if study_candidate:
                study_intent = study_candidate
                ask_study_confirmation = True
                subj = study_candidate.get("subject", "自选学科")
                agent_reply = f"好呀！检测到你想开始学习【{subj}】啦。是否要立即为你开启专属学习会话并前往「开始学习！」自习室呢？"
                agent_source = "study_dispatcher"
                agent_error = ""
                if profile_id:
                    mark_profile_chatted(user_id, profile_id)
            else:
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
                    academic_profile=active_profile,
                )
                if profile_id and user_text:
                    mark_profile_chatted(user_id, profile_id)

        if user_text:
            add_chat_message(
                user_id, "user", user_text, created_at=timestamp,
                attachments=[{"name": item["name"], "type": item["type"], "size": item["size"]} for item in attachments],
                profile_id=profile_id,
            )
        if agent_reply:
            add_chat_message(user_id, "assistant", agent_reply, created_at=timestamp, profile_id=profile_id)
        if user_text and agent_reply and not proactive:
            pipeline_result = record_complete_interaction(user_id, timestamp)

    response = {
        "model": model_info,
        "scores": raw_scores,
        "agent": agent_payload(agent_reply, agent_source, agent_error),
        "study_intent": study_intent,
        "ask_study_confirmation": ask_study_confirmation,
        "active_profile": active_profile,
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
        "chat_history": list_chat_messages(user_id, limit=CHAT_DISPLAY_LIMIT, profile_id=profile_id),
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
    profile_id = (params.get("profile_id") or [""])[0]
    if not profile_id:
        active = get_active_profile(user_id)
        if active:
            profile_id = str(active.get("id") or "")
    try:
        limit = int((params.get("limit") or [CHAT_DISPLAY_LIMIT])[0])
    except (TypeError, ValueError):
        limit = CHAT_DISPLAY_LIMIT
    limit = max(1, min(limit, 50))
    return {
        "ok": True,
        "user_id": user_id,
        "profile_id": profile_id,
        "limit": limit,
        "items": list_chat_messages(user_id, limit=limit, profile_id=profile_id),
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
    delete_academic_data_for_user(user_id)
    study_deleted = delete_study_and_profile_data_for_user(user_id)
    return {
        "ok": True,
        "user_id": user_id,
        "diary": delete_diary_data(user_id),
        "chat_deleted": delete_chat_messages(user_id),
        "emotion_records_deleted": delete_emotion_records(user_id),
        "memory_v2_deleted": memory_v2.clear_user(user_id),
        "ai_diary_v2_deleted": delete_ai_diary_v2_batches(user_id),
        "runtime_v2_deleted": delete_runtime_state_for_user(user_id),
        "study_and_profile_deleted": study_deleted,
    }


def handle_academic_profile_query(query: Dict) -> Dict:
    user_id = (query.get("_auth_user_id") or [DEFAULT_MEMORY_USER_ID])[0]
    profile = get_academic_profile(user_id)
    if not profile:
        profile = {
            "user_id": user_id,
            "stage": "high_school",
            "grade": "",
            "sub_category": "",
            "province": "",
            "current_school": "",
            "target_school": "",
            "target_goal": "",
            "current_score_or_gpa": "",
            "rank_info": "",
            "extra_profile": {},
            "latest_advice": "",
            "advice_updated_at": "",
            "updated_at": "",
        }
    return {"ok": True, "profile": profile}


def handle_academic_profile_save(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    profile = upsert_academic_profile(user_id, payload)
    return {"ok": True, "profile": profile}


def handle_academic_scores_query(query: Dict) -> Dict:
    user_id = (query.get("_auth_user_id") or [DEFAULT_MEMORY_USER_ID])[0]
    scores = list_academic_scores(user_id, limit=50)
    return {"ok": True, "scores": scores}


def handle_academic_score_save(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    score_record = add_academic_score(user_id, payload)
    return {"ok": True, "record": score_record}


def handle_academic_advice_generate(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    profile = get_academic_profile(user_id) or upsert_academic_profile(user_id, payload)
    scores = list_academic_scores(user_id, limit=10)
    advice = generate_academic_advice(profile, scores)
    update_academic_advice(user_id, advice)
    updated_profile = get_academic_profile(user_id)
    return {"ok": True, "advice": advice, "profile": updated_profile}


# --- 多画像 (Profile) 管理 ---

def handle_profiles_query(query: Dict) -> Dict:
    user_id = (query.get("_auth_user_id") or [DEFAULT_MEMORY_USER_ID])[0]
    profiles = list_user_profiles(user_id)
    active = get_active_profile(user_id)
    return {"ok": True, "profiles": profiles, "active_profile": active}


def handle_profile_create(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    profile = create_user_profile(user_id, payload)
    profiles = list_user_profiles(user_id)
    return {"ok": True, "profile": profile, "profiles": profiles, "active_profile": profile}


def handle_profile_switch(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    profile_id = str(payload.get("profile_id") or "").strip()
    if not profile_id:
        raise ValueError("缺少 profile_id 参数。")
    active = set_active_profile(user_id, profile_id)
    profiles = list_user_profiles(user_id)
    return {"ok": True, "active_profile": active, "profiles": profiles}


def handle_profile_update(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    profile_id = str(payload.get("profile_id") or "").strip()
    if not profile_id:
        active = get_active_profile(user_id)
        profile_id = active.get("id", "") if active else ""
    if not profile_id:
        raise ValueError("缺少 profile_id 参数。")
    active = update_user_profile(user_id, profile_id, payload)
    profiles = list_user_profiles(user_id)
    return {"ok": True, "active_profile": active, "profiles": profiles}


def handle_profile_delete(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    profile_id = str(payload.get("profile_id") or "").strip()
    if not profile_id:
        raise ValueError("缺少 profile_id 参数。")
    delete_user_profile(user_id, profile_id)
    profiles = list_user_profiles(user_id)
    active = get_active_profile(user_id)
    return {"ok": True, "profiles": profiles, "active_profile": active}


def handle_profile_greeting(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    active = get_active_profile(user_id)
    if not active:
        return {"ok": False, "error": "暂无活跃画像"}

    profile_id = active.get("id", "")
    force = bool(payload.get("force"))
    has_chatted = profile_has_user_chatted(user_id, profile_id)

    # 如果该画像已经跟用户有过聊天且不是强制触发，则直接返回已经聊过
    if has_chatted and not force:
        return {"ok": True, "already_chatted": True, "active_profile": active}

    stage = str(active.get("stage") or "high_school")
    stage_map = {"high_school": "高中", "undergraduate": "大学本科", "growth": "自主进修与成长"}
    stage_text = stage_map.get(stage, "学业成长")
    name = active.get("profile_name", "默认画像")
    grade = active.get("grade", "")
    target = active.get("target_goal") or active.get("target_school") or ""

    greeting = (
        f"你好呀！我注意到你当前使用的是画像【{name}】（学业阶段：{stage_text}"
        f"{f' · {grade}' if grade else ''}{f' · 目标：{target}' if target else ''}）。\n"
        f"我们还没有为这个画像制定过专属的成长与学业规划。现在需要为你量身生成一份详细的成长规划路线吗？"
    )

    history = list_chat_messages(user_id, limit=CHAT_DISPLAY_LIMIT, profile_id=profile_id)
    if not any(m.get("content") == greeting for m in history):
        timestamp = normalize_timestamp_to_china("")
        add_chat_message(user_id, "assistant", greeting, created_at=timestamp, profile_id=profile_id)
        history = list_chat_messages(user_id, limit=CHAT_DISPLAY_LIMIT, profile_id=profile_id)

    return {
        "ok": True,
        "greeting": greeting,
        "already_chatted": False,
        "ask_plan_confirmation": True,
        "active_profile": active,
        "chat_history": history,
    }


# --- 学习会话 (Study Sessions) ---

def handle_study_sessions_query(query: Dict) -> Dict:
    user_id = (query.get("_auth_user_id") or [DEFAULT_MEMORY_USER_ID])[0]
    profile_id = (query.get("profile_id") or [""])[0]
    sessions = list_study_sessions(user_id, profile_id=profile_id)
    return {"ok": True, "sessions": sessions}


def handle_study_session_create(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    profile_id = str(payload.get("profile_id") or "").strip()
    if not profile_id:
        active = get_active_profile(user_id)
        if active:
            profile_id = active.get("id", "")
    title = str(payload.get("title") or "自主学习专项").strip()
    subject = str(payload.get("subject") or "通用学科").strip()
    prompt_seed = str(payload.get("prompt_seed") or f"请辅导我深入学习【{subject}】的【{title}】。").strip()

    session = create_study_session(user_id, profile_id, title, subject=subject, prompt_seed=prompt_seed)

    greeting = (
        f"你好！我是你的专属【{subject}】辅导搭档云雀。今天我们要一起攻克【{title}】。\n"
        f"你可以随时把不懂的概念、卡住的题目或者想梳理的章节发给我，我们一步一步拆解！你现在想从哪里开始？"
    )
    init_msg = add_study_message(session["id"], user_id, "assistant", greeting)

    return {
        "ok": True,
        "session": session,
        "initial_message": init_msg,
    }


def handle_study_messages_query(query: Dict) -> Dict:
    user_id = current_user_id({"user_id": (query.get("_auth_user_id") or [""])[0]})
    session_id = (query.get("session_id") or [""])[0]
    if not session_id:
        return {"ok": False, "error": "缺少 session_id 参数"}
    if not get_study_session(user_id, session_id):
        return {"ok": False, "error": "学习会话不存在或无权访问"}
    messages = list_study_messages(session_id)
    return {"ok": True, "messages": messages}


def _save_attachments_to_study_library(
    user_id: str,
    attachments: list[Dict[str, Any]],
    session_id: str = "",
) -> list[Dict[str, Any]]:
    saved = []
    for item in attachments or []:
        name = str(item.get("name") or "学习资料")
        mime_type = infer_attachment_mime(name, str(item.get("type") or ""))
        size = int(item.get("size") or 0)
        file_type, extracted, segments = extract_structured_segments(item, max_chars=240000)
        if file_type == "image":
            category = "image"
        elif file_type == "audio":
            category = "audio"
        else:
            category = "document"
        chunks, file_topics = build_file_chunks(name, file_type, segments)
        record = save_library_file(
            user_id=user_id,
            file_name=name,
            mime_type=mime_type,
            file_size=size,
            file_category=category,
            file_type=file_type,
            extracted_text=extracted,
            chunks=chunks,
            topics=file_topics,
            session_id=session_id,
        )
        saved.append(record)
    return saved


def handle_study_library_query(query: Dict) -> Dict:
    user_id = current_user_id({"user_id": (query.get("_auth_user_id") or [""])[0]})
    session_id = (query.get("session_id") or [""])[0]
    if session_id and not get_study_session(user_id, session_id):
        return {"ok": False, "error": "学习会话不存在或无权访问"}
    files = list_library_files(user_id, session_id=session_id)
    linked_count = sum(1 for f in files if f.get("linked")) if session_id else 0
    return {"ok": True, "files": files, "linked_count": linked_count}


def handle_study_library_upload(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    session_id = str(payload.get("session_id") or "").strip()
    if session_id:
        session = get_study_session(user_id, session_id)
        if not session:
            raise ValueError("学习会话不存在。")
    attachments = normalize_attachments(payload)
    if not attachments:
        raise ValueError("未检测到有效的上传文件（支持 PDF、PPTX、Word、Excel/CSV、Markdown、文本、代码、图片与音频）。")
    saved = _save_attachments_to_study_library(user_id, attachments, session_id=session_id)
    files = list_library_files(user_id, session_id=session_id)
    linked_count = sum(1 for f in files if f.get("linked")) if session_id else 0
    return {
        "ok": True,
        "uploaded": saved,
        "files": files,
        "linked_files": [f for f in files if f.get("linked")] if session_id else [],
        "linked_count": linked_count,
    }


def handle_study_library_delete(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    session_id = str(payload.get("session_id") or "").strip()
    file_id = str(payload.get("file_id") or "").strip()
    if not file_id:
        raise ValueError("缺少 file_id 参数。")
    deleted = delete_library_file(user_id, file_id)
    files = list_library_files(user_id, session_id=session_id)
    linked_count = sum(1 for f in files if f.get("linked")) if session_id else 0
    return {"ok": deleted, "files": files, "linked_count": linked_count}


def handle_study_library_chunks_query(query: Dict) -> Dict:
    user_id = current_user_id({"user_id": (query.get("_auth_user_id") or [""])[0]})
    file_id = (query.get("file_id") or [""])[0]
    if not file_id:
        return {"ok": False, "error": "缺少 file_id 参数"}
    chunks = get_library_file_chunks(user_id, file_id)
    return {"ok": True, "chunks": chunks}


def handle_study_session_links_update(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise ValueError("缺少 session_id 参数。")
    session = get_study_session(user_id, session_id)
    if not session:
        raise ValueError("学习会话不存在。")

    if "file_ids" in payload and isinstance(payload.get("file_ids"), list):
        set_session_linked_files(user_id, session_id, [str(x) for x in payload["file_ids"]])
    else:
        file_id = str(payload.get("file_id") or "").strip()
        if not file_id:
            raise ValueError("缺少 file_id 或 file_ids 参数。")
        linked = bool(payload.get("linked", True))
        ok = set_session_file_link(user_id, session_id, file_id, linked)
        if not ok:
            raise ValueError("指定学习资料不存在。")

    files = list_library_files(user_id, session_id=session_id)
    linked_files = [f for f in files if f.get("linked")]
    return {
        "ok": True,
        "files": files,
        "linked_files": linked_files,
        "linked_count": len(linked_files),
    }


def handle_study_files_query(query: Dict) -> Dict:
    user_id = current_user_id({"user_id": (query.get("_auth_user_id") or [""])[0]})
    session_id = (query.get("session_id") or [""])[0]
    if not session_id:
        return {"ok": False, "error": "缺少 session_id 参数"}
    if not get_study_session(user_id, session_id):
        return {"ok": False, "error": "学习会话不存在或无权访问"}
    files = list_library_files(user_id, session_id=session_id)
    linked_files = [f for f in files if f.get("linked")]
    return {"ok": True, "files": linked_files, "library_files": files, "linked_count": len(linked_files)}


def handle_study_file_upload(payload: Dict) -> Dict:
    return handle_study_library_upload(payload)


def handle_study_file_delete(payload: Dict) -> Dict:
    user_id = current_user_id(payload)
    session_id = str(payload.get("session_id") or "").strip()
    file_id = str(payload.get("file_id") or "").strip()
    if not session_id or not file_id:
        raise ValueError("缺少 session_id 或 file_id 参数。")
    ok = set_session_file_link(user_id, session_id, file_id, False)
    files = list_library_files(user_id, session_id=session_id)
    linked_files = [f for f in files if f.get("linked")]
    return {"ok": ok, "files": linked_files, "library_files": files, "linked_count": len(linked_files)}


def _format_grounded_context_blocks(sources: list[Dict[str, Any]]) -> str:
    blocks = []
    for src in sources:
        topics_str = "、".join(src.get("topics") or []) or "未标注"
        header = (
            f"[{src['cite_id']}] 来源：{src['doc_name']} · {src['location']}"
            + (f"（{src['section_title']}）" if src.get("section_title") else "")
            + f" | 主题词：{topics_str} | 相关度：{src.get('score', 0.0):.3f}"
        )
        blocks.append(f"{header}\n{src['content']}")
    return "\n\n---\n\n".join(blocks)


def _build_abstention_reply(retrieval: Dict[str, Any]) -> str:
    sources = retrieval.get("results") or []
    max_score = float(retrieval.get("max_score") or 0.0)
    threshold = float(retrieval.get("threshold") or DEFAULT_RELEVANCE_THRESHOLD)
    closest_hint = ""
    if sources:
        top0 = sources[0]
        topics_str = "、".join(top0.get("topics") or [])
        topic_part = f"（主题词：{topics_str}）" if topics_str else ""
        closest_hint = (
            f"\n\n当前关联资料中最接近但相关度不足的切片：`{top0['doc_name']} · {top0['location']}`"
            f"{topic_part}（相关度 `{max_score:.3f}` < 阈值 `{threshold:.3f}`）。"
            "\n你可以在下方查看最相关的候选切片，或点击切片直接深入学习。"
        )
    return (
        "抱歉，**我不知道 / 根据当前自习室关联的学习资料无法可靠回答该问题**。\n\n"
        "原因：当前自习室已关联的学习资料中未检索到足够高相关度的直接依据，为避免编造信息，已拒绝生成。"
        + closest_hint
    )


def _prepare_study_context(payload: Dict) -> Dict[str, Any]:
    user_id = current_user_id(payload)
    session_id = str(payload.get("session_id") or "").strip()
    attachments = normalize_attachments(payload)
    content = str(payload.get("content") or "").strip()
    pinned_chunk_id = str(payload.get("pinned_chunk_id") or "").strip()
    if not session_id or (not content and not attachments):
        raise ValueError("缺少 session_id 或消息内容。")

    session = get_study_session(user_id, session_id)
    if not session:
        raise ValueError("学习会话不存在。")

    if not content and attachments:
        content = "请帮我解析上传的文件或图片内容，并结合当前学习主题辅导我。"

    if attachments:
        _save_attachments_to_study_library(user_id, attachments, session_id=session_id)

    attachment_names = [item["name"] for item in attachments]
    stored_user_content = content
    if attachment_names:
        stored_user_content = f"{content}\n\n" + " ".join(f"[附件: {n}]" for n in attachment_names)

    user_msg = add_study_message(session_id, user_id, "user", stored_user_content)
    history = list_study_messages(session_id)
    active_profile = get_active_profile(user_id) or {}

    subject = session.get("subject") or "自选学科"
    title = session.get("title") or "自主学习"
    prompt_seed = session.get("prompt_seed") or ""
    stage_desc = format_academic_context(active_profile)

    library_files = list_library_files(user_id, session_id=session_id)
    linked_files = [f for f in library_files if f.get("linked")]
    linked_chunks = get_session_linked_chunks(user_id, session_id)

    has_media_attachment = any(
        infer_file_type(str(a.get("name") or ""), str(a.get("type") or "")) in {"image", "audio"}
        for a in attachments
    )

    grounded_mode = bool(linked_chunks) and not has_media_attachment
    retrieval: Dict[str, Any] = {
        "abstained": False,
        "max_score": 0.0,
        "threshold": DEFAULT_RELEVANCE_THRESHOLD,
        "pinned_target": False,
        "results": [],
    }
    if grounded_mode:
        retrieval = retrieve_chunks_with_scores(
            content,
            linked_chunks,
            top_k=5,
            threshold=DEFAULT_RELEVANCE_THRESHOLD,
            pinned_chunk_id=pinned_chunk_id,
        )

    if grounded_mode and retrieval.get("abstained"):
        return {
            "user_id": user_id,
            "session_id": session_id,
            "session": session,
            "user_msg": user_msg,
            "library_files": library_files,
            "linked_files": linked_files,
            "linked_chunks": linked_chunks,
            "grounded_mode": True,
            "retrieval": retrieval,
            "abstained_early": True,
            "llm_messages": [],
        }

    if grounded_mode:
        sources = retrieval.get("results") or []
        context_blocks = _format_grounded_context_blocks(sources)
        pinned_hint = (
            "说明：学生正在针对指定学习切片 [S1] 进行深入学习，请以 [S1] 为核心进行清晰、启发式的讲解，必要时结合 [S2] 等关联切片补充。\n"
            if retrieval.get("pinned_target")
            else ""
        )
        system_prompt = (
            f"你叫云雀，是学生的严谨学科学习助教与导师。\n"
            f"当前自习室主题：【{subject}】 - {title}。\n"
            f"学生档案背景：{stage_desc}\n"
            f"会话初始要求：{prompt_seed}\n"
            f"{pinned_hint}"
            "你必须严格遵守以下溯源回答规则：\n"
            "1. 你只能依据下方提供的已关联学习资料切片 [S1]...[Sk] 中的事实回答问题，严禁补充资料中未提及的外部知识或臆测内容。\n"
            "2. 回答中的每一条关键结论、定义或步骤末尾，必须显式标注对应的来源编号，例如 [S1] 或 [S1][S2]。\n"
            "3. 如果参考切片仅包含相关名词，但没有直接包含问题的核心答案细节，你必须诚实回答：“根据当前自习室关联的学习资料，我不知道 / 无法可靠回答该问题（缺少……）”，绝不编造。\n"
            "4. 在严格基于资料的前提下，保持清晰、有条理、温暖耐心的讲解风格，支持规范 Markdown 与 LaTeX 公式。\n"
            "5. 当需要直观展示资料中的过程、结构或公式演练时，可按需输出完整自包含的 ```html-widget ... ``` 代码块。\n\n"
            f"【当前自习室已关联资料检索切片（仅限本自习室关联资料）】\n\n{context_blocks}"
        )
    else:
        system_prompt = (
            f"你叫云雀，现在是用户的专属学科学习导师。\n"
            f"当前自习室主题：【{subject}】 - {title}。\n"
            f"学生档案背景：{stage_desc}\n"
            f"会话初始要求：{prompt_seed}\n"
            "教学辅导原则：\n"
            "1. 耐心、专业、启发式辅导，用清晰步骤帮助学生理解核心概念。\n"
            "2. 遇到难题，先拆解知识点、梳理已知条件和常见陷阱，再进行分步推导。\n"
            "3. 支持公式推导（使用规范 Markdown / LaTeX 格式），鼓励学生积极提问与演算。\n"
            "4. 当讲解抽象概念、函数图像、算法步骤或需要交互式练习卡时，可以主动输出完整自包含的 ```html-widget ... ``` 单文件代码块。\n"
            "5. 语气温暖自信，像一位随时陪伴身边的学科私教。"
        )

    llm_messages: list[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for msg in history[-8:-1]:
        role = "assistant" if msg["role"] == "assistant" else "user"
        llm_messages.append({"role": role, "content": msg["content"]})

    current_user_content = build_multimodal_user_content(
        content,
        attachments,
        allow_image=API_IMAGE_INPUT,
        allow_audio=API_AUDIO_INPUT,
    )
    if grounded_mode and isinstance(current_user_content, str):
        current_user_content = f"{current_user_content}\n\n请严格依据上述已关联资料切片作答，并在关键结论处标注 [Si] 来源编号。"
    llm_messages.append({"role": "user", "content": current_user_content})

    return {
        "user_id": user_id,
        "session_id": session_id,
        "session": session,
        "user_msg": user_msg,
        "library_files": library_files,
        "linked_files": linked_files,
        "linked_chunks": linked_chunks,
        "grounded_mode": grounded_mode,
        "retrieval": retrieval,
        "abstained_early": False,
        "llm_messages": llm_messages,
    }


def _finalize_study_rag_meta(
    reply_content: str,
    ctx: Dict[str, Any],
) -> tuple[str, Dict[str, Any]]:
    if not ctx.get("grounded_mode"):
        return reply_content, {}

    retrieval = ctx.get("retrieval") or {}
    sources = retrieval.get("results") or []
    max_score = float(retrieval.get("max_score") or 0.0)
    threshold = float(retrieval.get("threshold") or DEFAULT_RELEVANCE_THRESHOLD)

    if ctx.get("abstained_early"):
        return reply_content, {
            "grounded": True,
            "abstained": True,
            "max_score": max_score,
            "threshold": threshold,
            "used_citations": [],
            "citation_warning": None,
            "sources": sources[:3],
            "recommendations": [],
        }

    valid_ids = {s["cite_id"] for s in sources if s.get("cite_id")}
    verified = verify_citations(reply_content, valid_ids)
    cleaned_answer = verified["answer"] or reply_content
    abstained = bool(verified["model_abstained"])

    recommendations: list[Dict[str, Any]] = []
    if not abstained and sources:
        cited_set = set(verified["valid_citations"])
        seed_ids = [s["chunk_id"] for s in sources if s.get("cite_id") in cited_set and s.get("chunk_id")]
        if not seed_ids:
            seed_ids = [s["chunk_id"] for s in sources[:2] if s.get("chunk_id")]
        recommendations = recommend_next_chunks(seed_ids, ctx.get("linked_chunks") or [], top_k=3)

    rag_meta = {
        "grounded": True,
        "abstained": abstained,
        "max_score": max_score,
        "threshold": threshold,
        "used_citations": verified["valid_citations"],
        "invalid_citations_removed": verified["invalid_citations_removed"],
        "citation_warning": verified["citation_warning"],
        "sources": sources,
        "recommendations": recommendations,
    }
    return cleaned_answer, rag_meta


def handle_study_chat(payload: Dict) -> Dict:
    ctx = _prepare_study_context(payload)
    user_id = ctx["user_id"]
    session_id = ctx["session_id"]

    if ctx.get("abstained_early"):
        raw_reply = _build_abstention_reply(ctx["retrieval"])
    else:
        temp = 0.25 if ctx.get("grounded_mode") else 0.6
        raw_reply, error = call_chat_completion(ctx["llm_messages"], max_tokens=3500, temperature=temp)
        if not raw_reply:
            raw_reply = f"抱歉，我刚刚在推导时遇到了一点网络波动：{error or '无内容'}。请再发一次试下~"

    final_reply, rag_meta = _finalize_study_rag_meta(raw_reply, ctx)
    assistant_msg = add_study_message(session_id, user_id, "assistant", final_reply, meta=rag_meta)

    return {
        "ok": True,
        "reply": final_reply,
        "rag_meta": rag_meta,
        "user_message": ctx["user_msg"],
        "assistant_message": assistant_msg,
        "session": ctx["session"],
        "files": ctx["linked_files"],
        "library_files": ctx["library_files"],
        "linked_count": len(ctx["linked_files"]),
    }


def stream_study_chat(payload: Dict):
    ctx = _prepare_study_context(payload)
    user_id = ctx["user_id"]
    session_id = ctx["session_id"]

    yield {
        "type": "meta",
        "session": ctx["session"],
        "files": ctx["linked_files"],
        "library_files": ctx["library_files"],
        "linked_count": len(ctx["linked_files"]),
        "user_message": ctx["user_msg"],
        "grounded": bool(ctx.get("grounded_mode")),
    }

    if ctx.get("abstained_early"):
        abstention_text = _build_abstention_reply(ctx["retrieval"])
        yield {"type": "delta", "delta": abstention_text}
        final_reply, rag_meta = _finalize_study_rag_meta(abstention_text, ctx)
        assistant_msg = add_study_message(session_id, user_id, "assistant", final_reply, meta=rag_meta)
        yield {
            "type": "done",
            "ok": True,
            "reply": final_reply,
            "rag_meta": rag_meta,
            "user_message": ctx["user_msg"],
            "assistant_message": assistant_msg,
            "session": ctx["session"],
            "files": ctx["linked_files"],
            "library_files": ctx["library_files"],
            "linked_count": len(ctx["linked_files"]),
        }
        return

    chunks_buf: list[str] = []
    temp = 0.25 if ctx.get("grounded_mode") else 0.6
    try:
        for delta in stream_chat_completion(ctx["llm_messages"], max_tokens=3500, temperature=temp):
            chunks_buf.append(delta)
            yield {"type": "delta", "delta": delta}
    except Exception as exc:
        if not chunks_buf:
            fallback, err = call_chat_completion(ctx["llm_messages"], max_tokens=3500, temperature=temp)
            text = fallback or f"抱歉，我刚刚在推导时遇到了一点网络波动：{err or exc}。请再发一次试下~"
            chunks_buf.append(text)
            yield {"type": "delta", "delta": text}

    raw_reply = "".join(chunks_buf).strip()
    if not raw_reply:
        raw_reply = "抱歉，我刚刚没有收到模型返回的内容，请重试一下~"
        yield {"type": "delta", "delta": raw_reply}

    final_reply, rag_meta = _finalize_study_rag_meta(raw_reply, ctx)
    assistant_msg = add_study_message(session_id, user_id, "assistant", final_reply, meta=rag_meta)
    yield {
        "type": "done",
        "ok": True,
        "reply": final_reply,
        "rag_meta": rag_meta,
        "user_message": ctx["user_msg"],
        "assistant_message": assistant_msg,
        "session": ctx["session"],
        "files": ctx["linked_files"],
        "library_files": ctx["library_files"],
        "linked_count": len(ctx["linked_files"]),
    }


MAIN_CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "propose_study_session",
            "description": "当用户明确表达想复习、刷题、学某个科目或进入专注学习时调用此工具，向用户发起进入「开始学习！」自习室的确认卡片。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "学科名称，如 数学、操作系统、英语、物理"},
                    "title": {"type": "string", "description": "本次自习室主题，如 线性代数特征值专项"},
                    "prompt_seed": {"type": "string", "description": "给自习室导师的初始辅导提示"},
                },
                "required": ["subject", "title"],
            },
        },
    }
]


def stream_main_chat(payload: Dict):
    """主聊天 SSE 流式接口（含情绪识别、长期记忆、原生 Tool Calling 学习意图感知）。"""
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
        if temporary_audio:
            audio_path.unlink(missing_ok=True)
        raise ValueError("音频未识别到有效语音内容。")

    proactive = bool(payload.get("proactive"))
    if not proactive and not user_text and not attachments:
        raise ValueError("请输入内容或上传文件后再发送。")
    if not user_text and attachments:
        user_text = "请结合我上传的文件或媒体内容回应我。"

    history = list_chat_messages(user_id, limit=CHAT_CONTEXT_LIMIT, profile_id=str(payload.get("profile_id") or ""))
    timestamp = normalize_timestamp_to_china(payload.get("timestamp", ""))

    if ENABLE_MULTIMODAL:
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
    else:
        audio_info = {"available": False}
        raw_scores = {"text": 0.0, "audio": 0.0, "fusion": 0.0}

    if temporary_audio and audio_path is not None:
        audio_path.unlink(missing_ok=True)

    if proactive:
        raw_scores["proactive_reason"] = payload.get("proactive_reason") or payload.get("proactiveReason") or "主动回应"
    elif user_text:
        add_emotion_record(user_id, raw_scores, audio_available=bool(audio_info.get("available")), created_at=timestamp)

    emotion = FineGrainedEmotion(label="", valence=0.0, arousal=0.0, confidence=0.0)
    active_profile = get_active_profile(user_id) or get_academic_profile(user_id) or {}
    profile_id = str(payload.get("profile_id") or active_profile.get("id") or "").strip()

    study_intent = None
    ask_study_confirmation = False
    recalled = {"memories": [], "strategies": []}

    yield {
        "type": "meta",
        "scores": raw_scores,
        "modal_inputs": {
            "text_available": bool(user_text),
            "text_source": text_source,
            "audio_available": bool(audio_info.get("available")),
        },
    }

    chunks: list[str] = []
    if user_text and is_requesting_plan(user_text):
        scores = list_academic_scores(user_id, limit=10)
        plan_text = generate_academic_advice(active_profile, scores)
        chunks.append(plan_text)
        yield {"type": "delta", "delta": plan_text}
    else:
        study_candidate = detect_study_intent(user_text) if (user_text and not proactive) else None
        if not study_candidate and user_text and not proactive and chat_api_ready():
            # 使用原生 Tool Calling 进行学习意图识别
            probe_messages = [
                {"role": "system", "content": "如果用户表达了想学习、复习或刷题的意愿，请调用 propose_study_session；否则直接简短忽略。"},
                {"role": "user", "content": user_text},
            ]
            _, tcalls, _ = call_chat_completion_with_tools(probe_messages, MAIN_CHAT_TOOLS, max_tokens=200, temperature=0.1)
            for tc in tcalls:
                fn = tc.get("function") or {}
                if fn.get("name") == "propose_study_session":
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except Exception:
                        args = {}
                    subj = str(args.get("subject") or "自选学科").strip()
                    study_candidate = {
                        "subject": subj,
                        "title": str(args.get("title") or f"{subj}专项自习").strip(),
                        "prompt_seed": str(args.get("prompt_seed") or f"请辅导我学习{subj}。").strip(),
                    }
                    break

        if study_candidate:
            study_intent = study_candidate
            ask_study_confirmation = True
            subj = study_candidate.get("subject", "自选学科")
            msg = f"好呀！检测到你想开始学习【{subj}】啦。是否要立即为你开启专属学习会话并前往「开始学习！」自习室呢？"
            chunks.append(msg)
            yield {"type": "delta", "delta": msg}
        else:
            memory_query = user_text or raw_scores.get("proactive_reason") or "当前陪伴情境"
            recalled = memory_v2.recall_for_chat(user_id, memory_query, memory_k=3, strategy_k=2)
            messages = build_agent_prompt(
                user_text,
                emotion,
                raw_scores,
                history,
                memories=recalled["memories"],
                strategies=recalled["strategies"],
                proactive=proactive,
                attachments=attachments,
                academic_profile=active_profile,
            )
            try:
                for delta in stream_chat_completion(messages, max_tokens=2000, temperature=0.8):
                    chunks.append(delta)
                    yield {"type": "delta", "delta": delta}
            except Exception:
                pass
            if not chunks:
                fallback_reply, _, _ = generate_agent_reply(
                    user_text,
                    emotion,
                    raw_scores,
                    history,
                    memories=recalled["memories"],
                    strategies=recalled["strategies"],
                    proactive=proactive,
                    attachments=attachments,
                    academic_profile=active_profile,
                )
                chunks.append(fallback_reply)
                yield {"type": "delta", "delta": fallback_reply}

    agent_reply = "".join(chunks).strip()
    if profile_id and user_text:
        mark_profile_chatted(user_id, profile_id)
    if user_text:
        add_chat_message(
            user_id, "user", user_text, created_at=timestamp,
            attachments=[{"name": item["name"], "type": item["type"], "size": item["size"]} for item in attachments],
            profile_id=profile_id,
        )
    if agent_reply:
        add_chat_message(user_id, "assistant", agent_reply, created_at=timestamp, profile_id=profile_id)
    if user_text and agent_reply and not proactive:
        record_complete_interaction(user_id, timestamp)

    yield {
        "type": "done",
        "ok": True,
        "reply": agent_reply,
        "scores": raw_scores,
        "study_intent": study_intent,
        "ask_study_confirmation": ask_study_confirmation,
        "chat_history": list_chat_messages(user_id, limit=CHAT_DISPLAY_LIMIT, profile_id=profile_id),
    }

