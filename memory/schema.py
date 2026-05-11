import math
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Literal

from core.utils import CHINA_TZ, normalize_timestamp_to_china, now_china
from memory.db import collection


MemoryType = Literal["event", "routine", "preference", "relationship", "summary"]
MemorySource = Literal["conversation", "diary_user", "inference"]
MemoryUser = Literal["user", "ai"]
ConfirmationState = Literal["none", "confirmed", "corrected"]

TYPE_BASE = {
    "preference": 0.75,
    "relationship": 0.70,
    "routine": 0.65,
    "event": 0.60,
    "summary": 0.55,
}

SOURCE_BONUS = {
    "diary_user": 0.05,
    "conversation": 0.03,
    "inference": -0.05,
}

CONFIRMATION_BONUS = {
    "none": 0.00,
    "confirmed": 0.05,
    "corrected": 0.08,
}


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def normalize_weights(alpha: float, beta: float, gamma: float) -> tuple[float, float, float]:
    values = [max(0.0, float(item)) for item in (alpha, beta, gamma)]
    total = sum(values)
    if total <= 0:
        return 0.55, 0.30, 0.15
    return values[0] / total, values[1] / total, values[2] / total


def now_local() -> datetime:
    return now_china()


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def calculate_initial_importance(
    memory_type: str,
    source: str,
    confidence: float,
    confirmation: ConfirmationState = "none",
) -> float:
    base = TYPE_BASE.get(memory_type, 0.55)
    source_bonus = SOURCE_BONUS.get(source, 0.0)
    confidence_bonus = 0.18 * (clamp(confidence) - 0.5)
    confirmation_bonus = CONFIRMATION_BONUS.get(confirmation, 0.0)
    return clamp(base + source_bonus + confidence_bonus + confirmation_bonus)


def decay_importance(importance_0: float, elapsed_days: float) -> float:
    importance_0 = clamp(importance_0)
    elapsed_days = max(0.0, float(elapsed_days))
    return clamp(importance_0 * math.exp(elapsed_days * (importance_0 - 1.0)))


def recency_from_timestamp(timestamp: str | None, now: datetime | None = None, half_life_days: float = 14.0) -> float:
    created_at = parse_timestamp(timestamp)
    if created_at is None:
        return 0.0
    now = now or now_local()
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=CHINA_TZ)
    elapsed_days = max(0.0, (now - created_at.astimezone(now.tzinfo)).total_seconds() / 86400.0)
    return clamp(math.exp(-elapsed_days / max(half_life_days, 0.001)))


def elapsed_days_from_timestamp(timestamp: str | None, now: datetime | None = None) -> float:
    created_at = parse_timestamp(timestamp)
    if created_at is None:
        return 0.0
    now = now or now_local()
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=CHINA_TZ)
    return max(0.0, (now - created_at.astimezone(now.tzinfo)).total_seconds() / 86400.0)


def create_memory(
    document: str,
    date: str | None = None,
    timestamp: str | None = None,
    user: MemoryUser = "user",
    type: MemoryType = "event",
    source: MemorySource = "conversation",
    has_emotion: bool = False,
    valence: float | None = None,
    arousal: float | None = None,
    confidence: float = 0.7,
    importance: float | None = None,
    user_id: str | None = None,
    text: bool | None = None,
    audio: bool | None = None,
    video: bool | None = None,
    text_available: bool | None = None,
    audio_available: bool | None = None,
    video_available: bool | None = None,
    confirmation: ConfirmationState = "none",
) -> Dict[str, Any]:
    document = (document or "").strip()
    if not document:
        raise ValueError("memory document cannot be empty")

    current = now_local()
    timestamp = normalize_timestamp_to_china(timestamp or current.isoformat(timespec="seconds"))
    date = date or timestamp[:10]
    confidence = clamp(confidence)
    importance = calculate_initial_importance(type, source, confidence, confirmation) if importance is None else clamp(importance)

    metadata = {
        "date": date,
        "timestamp": timestamp,
        "user": user,
        "type": type,
        "source": source,
        "has_emotion": bool(has_emotion),
        "confidence": confidence,
        "importance": importance,
        "importance_0": importance,
    }
    if user_id is not None:
        metadata["user_id"] = user_id
    if has_emotion:
        metadata["valence"] = max(-1.0, min(1.0, float(valence or 0.0)))
        metadata["arousal"] = clamp(arousal or 0.0)

    text = text if text is not None else text_available
    audio = audio if audio is not None else audio_available
    video = video if video is not None else video_available
    if text is not None:
        metadata["text"] = bool(text)
        metadata["text_available"] = bool(text)
    if audio is not None:
        metadata["audio"] = bool(audio)
        metadata["audio_available"] = bool(audio)
    if video is not None:
        metadata["video"] = bool(video)
        metadata["video_available"] = bool(video)

    return {
        "document": document,
        "metadata": metadata,
    }


def add_memory(memory: Dict[str, Any], memory_id: str | None = None) -> str:
    memory_id = memory_id or str(uuid.uuid4())
    collection.upsert(
        documents=[memory["document"]],
        metadatas=[memory["metadata"]],
        ids=[memory_id],
    )
    return memory_id


def _metadata_where(user_id: str | None = None, memory_type: str | Iterable[str] | None = None) -> Dict[str, Any] | None:
    clauses: List[Dict[str, Any]] = []
    if user_id:
        clauses.append({"user_id": user_id})
    if memory_type:
        if isinstance(memory_type, str):
            clauses.append({"type": memory_type})
        else:
            clauses.append({"type": {"$in": list(memory_type)}})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def normalize_distance(distance: float | None) -> float:
    if distance is None:
        return 1.0
    return clamp(distance)


def _score_memory(
    metadata: Dict[str, Any],
    distance: float | None,
    alpha: float,
    beta: float,
    gamma: float,
    now: datetime | None = None,
) -> Dict[str, float]:
    normalized_distance = normalize_distance(distance)
    semantic_similarity = 1.0 - normalized_distance
    elapsed_days = elapsed_days_from_timestamp(metadata.get("timestamp"), now=now)
    importance = decay_importance(float(metadata.get("importance_0", metadata.get("importance", 0.0))), elapsed_days)
    recency = recency_from_timestamp(metadata.get("timestamp"), now=now)
    score = alpha * semantic_similarity + beta * importance + gamma * recency
    return {
        "score": clamp(score),
        "semantic_similarity": clamp(semantic_similarity),
        "importance": importance,
        "recency": recency,
    }


def recall(
    query: str,
    k: int = 3,
    user_id: str | None = None,
    memory_type: str | Iterable[str] | None = None,
    candidate_pool: int | None = None,
    alpha: float = 0.55,
    beta: float = 0.30,
    gamma: float = 0.15,
) -> Dict[str, List[List[Any]]]:
    alpha, beta, gamma = normalize_weights(alpha, beta, gamma)

    if collection.count() == 0:
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]], "scores": [[]]}

    candidate_pool = max(k, candidate_pool or k * 6)
    results = collection.query(
        query_texts=[query],
        n_results=min(candidate_pool, collection.count()),
        where=_metadata_where(user_id=user_id, memory_type=memory_type),
        include=["documents", "metadatas", "distances"],
    )
    ids = (results.get("ids") or [[]])[0]
    documents = (results.get("documents") or [[]])[0]
    metadatas = (results.get("metadatas") or [[]])[0]
    distances = (results.get("distances") or [[]])[0]
    now = now_local()

    ranked = []
    for index, document in enumerate(documents):
        metadata = dict(metadatas[index] or {}) if index < len(metadatas) else {}
        distance = distances[index] if index < len(distances) else None
        score_fields = _score_memory(metadata, distance, alpha, beta, gamma, now=now)
        metadata["importance"] = score_fields["importance"]
        ranked.append(
            {
                "id": ids[index] if index < len(ids) else "",
                "document": document,
                "metadata": metadata,
                "distance": distance,
                **score_fields,
            }
        )

    ranked.sort(key=lambda item: item["score"], reverse=True)
    selected = ranked[:k]
    return {
        "ids": [[item["id"] for item in selected]],
        "documents": [[item["document"] for item in selected]],
        "metadatas": [[item["metadata"] for item in selected]],
        "distances": [[item["distance"] for item in selected]],
        "scores": [[item["score"] for item in selected]],
        "semantic_similarities": [[item["semantic_similarity"] for item in selected]],
        "recencies": [[item["recency"] for item in selected]],
    }


def list_memories(
    limit: int = 50,
    offset: int = 0,
    user_id: str | None = None,
    memory_type: str | Iterable[str] | None = None,
) -> List[Dict[str, Any]]:
    results = collection.get(
        limit=limit,
        offset=offset,
        where=_metadata_where(user_id=user_id, memory_type=memory_type),
        include=["documents", "metadatas"],
    )
    ids = results.get("ids") or []
    documents = results.get("documents") or []
    metadatas = results.get("metadatas") or []
    items = []
    now = now_local()
    for index, memory_id in enumerate(ids):
        metadata = dict(metadatas[index] or {}) if index < len(metadatas) else {}
        elapsed_days = elapsed_days_from_timestamp(metadata.get("timestamp"), now=now)
        metadata["importance"] = decay_importance(float(metadata.get("importance_0", metadata.get("importance", 0.0))), elapsed_days)
        items.append(
            {
                "id": memory_id,
                "document": documents[index] if index < len(documents) else "",
                "metadata": metadata,
            }
        )
    items.sort(key=lambda item: item["metadata"].get("timestamp", ""), reverse=True)
    return items


def update_memory(memory_id: str, document: str | None = None, metadata_updates: Dict[str, Any] | None = None) -> None:
    current = collection.get(ids=[memory_id], include=["documents", "metadatas"])
    if not current.get("ids"):
        raise KeyError(f"memory not found: {memory_id}")
    old_document = (current.get("documents") or [""])[0]
    old_metadata = dict((current.get("metadatas") or [{}])[0] or {})
    old_metadata.update(metadata_updates or {})
    collection.update(
        ids=[memory_id],
        documents=[document if document is not None else old_document],
        metadatas=[old_metadata],
    )


def delete_memory(memory_id: str) -> None:
    collection.delete(ids=[memory_id])


def apply_decay(threshold: float = 0.05, dry_run: bool = True) -> List[Dict[str, Any]]:
    actions = []
    for item in list_memories(limit=max(collection.count(), 1)):
        memory_id = item["id"]
        metadata = item["metadata"]
        decayed = float(metadata.get("importance", 0.0))
        actions.append({"id": memory_id, "importance": decayed, "deleted": decayed < threshold})
        if dry_run:
            continue
        if decayed < threshold:
            delete_memory(memory_id)
        else:
            update_memory(memory_id, metadata_updates={"importance": decayed})
    return actions


def decay(importance: float, delta_time: float) -> float:
    """Backward-compatible alias used by earlier prototype code."""
    return decay_importance(importance, delta_time)
