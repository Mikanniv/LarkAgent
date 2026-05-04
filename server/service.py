import threading
import time
from typing import Dict

from agent.replies import agent_payload, generate_agent_reply
from core.config import AI_DIARY_UPDATE_INTERVAL, SELF_MM_MODEL_PATH
from core.utils import memory_date_from_payload
from diary.generator import refresh_ai_diary_from_snapshot
from diary.store import get_diary_index_payload, get_diary_payload, save_user_diary
from emotion.mapping import derive_architecture_emotion, make_emotion_bars
from emotion.media import (
    build_audio_tensor_from_media,
    build_video_tensor_from_media,
    resolve_payload_media_path,
    resolve_text_input,
    summarize_video_tensor,
)
from emotion.models import SelfMMRunner


EMOTION_RUNNER = None
MEMORY_LOCK = threading.Lock()
MEMORY_STATE = {
    "dirty_dates": set(),
    "latest_by_date": {},
}
EMOTION_STATE = {
    "recent_va": [],
    "smoothed": None,
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


def mark_memory_snapshot(date_key: str, snapshot: Dict) -> None:
    with MEMORY_LOCK:
        MEMORY_STATE["latest_by_date"][date_key] = snapshot
        MEMORY_STATE["dirty_dates"].add(date_key)


def refresh_ai_diary(date_key: str) -> bool:
    with MEMORY_LOCK:
        snapshot = MEMORY_STATE["latest_by_date"].get(date_key)
        if snapshot is None:
            return False
    refreshed = refresh_ai_diary_from_snapshot(date_key, snapshot)
    with MEMORY_LOCK:
        MEMORY_STATE["dirty_dates"].discard(date_key)
    return refreshed


def ai_diary_worker() -> None:
    while True:
        time.sleep(max(20, AI_DIARY_UPDATE_INTERVAL))
        with MEMORY_LOCK:
            dirty_dates = list(MEMORY_STATE["dirty_dates"])
        for date_key in dirty_dates:
            try:
                refresh_ai_diary(date_key)
            except Exception:
                continue


def analyze_and_reply(payload: Dict, should_reply: bool = True) -> Dict:
    user_text, text_source = resolve_text_input(payload)
    history = payload.get("history", []) or []
    proactive = bool(payload.get("proactive"))
    date_key = memory_date_from_payload(payload.get("timestamp", ""))
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
            agent_reply, agent_source, agent_error = generate_agent_reply(
                user_text,
                emotion,
                raw_scores,
                history,
                proactive=proactive,
            )
        predicted_history = history + ([{"role": "user", "content": user_text}] if user_text else [])
        if should_reply and agent_reply:
            predicted_history.append({"role": "assistant", "content": agent_reply})
        mark_memory_snapshot(
            date_key,
            {
                "emotion": emotion.__dict__,
                "scores": raw_scores,
                "history": predicted_history,
                "audio": audio_meta,
                "video": video_summary,
                "modalities": modalities,
                "timestamp": payload.get("timestamp"),
            },
        )

        return {
            "model": runner.metadata(),
            "scores": raw_scores,
            "emotion": emotion.__dict__,
            "emotion_state": emotion_state,
            "emotion_bars": make_emotion_bars(emotion),
            "agent": agent_payload(agent_reply, agent_source, agent_error),
            "memory": get_diary_payload(date_key),
            "modal_inputs": {
                "text_available": modalities["text"],
                "text_source": text_source,
                "audio_available": modalities["audio"],
                "video_available": modalities["video"],
                "audio": audio_meta,
                "video": video_meta,
            },
            "media_features": {
                "video": video_summary,
            },
            "timestamp": payload.get("timestamp"),
        }
    finally:
        for path in temp_paths:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass


def handle_diary_user(payload: Dict) -> Dict:
    date_key = payload.get("date") or memory_date_from_payload("")
    response = save_user_diary(date_key, payload.get("markdown", ""))
    if date_key == memory_date_from_payload(""):
        with MEMORY_LOCK:
            MEMORY_STATE["dirty_dates"].add(date_key)
    return response


def handle_diary_refresh(payload: Dict) -> Dict:
    date_key = payload.get("date") or memory_date_from_payload("")
    refreshed = refresh_ai_diary(date_key)
    return {"ok": refreshed, **get_diary_index_payload(date_key)}
