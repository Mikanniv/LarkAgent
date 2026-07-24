from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from datetime import datetime
from typing import Any, Dict, Iterable, List

from core.utils import CHINA_TZ, normalize_timestamp_to_china, now_china
from memory.db import client, embedding_function


LAYERS = ("observation", "reflection", "strategy")
TOPICS = ("event", "preference", "routine", "relationship")
COLLECTION_NAMES = {
    "observation": "yunque_v2_observations",
    "reflection": "yunque_v2_reflections",
    "strategy": "yunque_v2_strategies",
}
ID_PREFIXES = {
    "observation": "obs",
    "reflection": "ref",
    "strategy": "str",
}

_LOCK = threading.RLock()
collections = {
    layer: client.get_or_create_collection(
        name=name,
        embedding_function=embedding_function,
        metadata={"hnsw:space": "cosine"},
    )
    for layer, name in COLLECTION_NAMES.items()
}


def clamp(value: Any, lower: float = 0.0, upper: float = 10.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = lower
    return max(lower, min(upper, number))


def _json_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = []
    return [str(item) for item in parsed if str(item).strip()] if isinstance(parsed, list) else []


def normalize_topics(value: Any) -> List[str]:
    aliases = {
        "事件": "event",
        "偏好": "preference",
        "习惯": "routine",
        "关系": "relationship",
    }
    values = value if isinstance(value, list) else [value]
    normalized: List[str] = []
    for item in values:
        topic = aliases.get(str(item).strip(), str(item).strip().lower())
        if topic in TOPICS and topic not in normalized:
            normalized.append(topic)
    return normalized or ["event"]


def _safe_user_key(user_id: str) -> str:
    return hashlib.sha1(user_id.encode("utf-8")).hexdigest()[:16]


def _internal_id(user_id: str, display_id: str) -> str:
    return f"{_safe_user_key(user_id)}::{display_id}"


def _metadata_to_item(layer: str, memory_id: str, document: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    item = {
        "id": memory_id,
        "display_id": str(metadata.get("display_id") or memory_id.split("::")[-1]),
        "layer": layer,
        "document": document,
        "description": document,
        "topics": _json_list(metadata.get("topics_json")),
        "importance": float(metadata.get("importance", 0.0)),
        "confidence": float(metadata.get("confidence", 0.0)),
        "created_at": str(metadata.get("created_at") or ""),
        "status": str(metadata.get("status") or "active"),
        "review_status": str(metadata.get("review_status") or ""),
        "seen": bool(metadata.get("seen", False)),
        "diary_batch_id": str(metadata.get("diary_batch_id") or ""),
        "linked_memory_ids": _json_list(metadata.get("linked_ids_json")),
        "scene": str(metadata.get("scene") or ""),
        "metadata": dict(metadata),
    }
    return item


def _all_for_user(layer: str, user_id: str) -> List[Dict[str, Any]]:
    collection = collections[layer]
    if collection.count() == 0:
        return []
    result = collection.get(
        where={"user_id": user_id},
        include=["documents", "metadatas"],
    )
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    items = [
        _metadata_to_item(
            layer,
            str(memory_id),
            str(documents[index] if index < len(documents) else ""),
            dict((metadatas[index] if index < len(metadatas) else {}) or {}),
        )
        for index, memory_id in enumerate(ids)
    ]
    items.sort(key=lambda item: (item["created_at"], item["display_id"]), reverse=True)
    return items


def _next_display_id(layer: str, user_id: str) -> str:
    prefix = ID_PREFIXES[layer]
    maximum = 0
    for item in _all_for_user(layer, user_id):
        match = re.fullmatch(rf"{prefix}_(\d+)", item["display_id"])
        if match:
            maximum = max(maximum, int(match.group(1)))
    return f"{prefix}_{maximum + 1:05d}"


def create_memory(
    *,
    layer: str,
    user_id: str,
    description: str,
    topics: Iterable[str] | str | None = None,
    importance: float = 5.0,
    confidence: float = 5.0,
    review_status: str = "",
    linked_memory_ids: Iterable[str] | None = None,
    scene: str = "",
    created_at: str = "",
) -> Dict[str, Any]:
    if layer not in LAYERS:
        raise ValueError(f"unsupported v2 memory layer: {layer}")
    document = (description or "").strip()
    if not document:
        raise ValueError("memory description cannot be empty")
    with _LOCK:
        display_id = _next_display_id(layer, user_id)
        memory_id = _internal_id(user_id, display_id)
        normalized_topics = normalize_topics(topics or ["event"]) if layer != "strategy" else []
        timestamp = normalize_timestamp_to_china(created_at)
        metadata = {
            "display_id": display_id,
            "user_id": user_id,
            "layer": layer,
            "topics_json": json.dumps(normalized_topics, ensure_ascii=False),
            "importance": clamp(importance),
            "confidence": clamp(confidence),
            "created_at": timestamp,
            "status": "active",
            "review_status": review_status,
            "seen": False,
            "diary_batch_id": "",
            "linked_ids_json": json.dumps(list(linked_memory_ids or []), ensure_ascii=False),
            "reflected_topics_json": "[]",
            "used_for_strategy": False,
            "scene": (scene or "").strip(),
        }
        collections[layer].upsert(
            ids=[memory_id],
            documents=[document],
            metadatas=[metadata],
        )
        return _metadata_to_item(layer, memory_id, document, metadata)


def get_memory(layer: str, user_id: str, memory_id: str) -> Dict[str, Any] | None:
    if layer not in LAYERS:
        return None
    internal_id = memory_id if "::" in memory_id else _internal_id(user_id, memory_id)
    result = collections[layer].get(ids=[internal_id], include=["documents", "metadatas"])
    if not result.get("ids"):
        return None
    metadata = dict((result.get("metadatas") or [{}])[0] or {})
    if metadata.get("user_id") != user_id:
        return None
    return _metadata_to_item(
        layer,
        str(result["ids"][0]),
        str((result.get("documents") or [""])[0]),
        metadata,
    )


def update_memory(
    layer: str,
    user_id: str,
    memory_id: str,
    *,
    document: str | None = None,
    metadata_updates: Dict[str, Any] | None = None,
) -> Dict[str, Any] | None:
    item = get_memory(layer, user_id, memory_id)
    if not item:
        return None
    metadata = dict(item["metadata"])
    for key, value in (metadata_updates or {}).items():
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)
        metadata[key] = value
    final_document = (document if document is not None else item["document"]).strip()
    collections[layer].update(
        ids=[item["id"]],
        documents=[final_document],
        metadatas=[metadata],
    )
    return _metadata_to_item(layer, item["id"], final_document, metadata)


def list_memories(
    user_id: str,
    *,
    layer: str | None = None,
    include_deleted: bool = False,
) -> List[Dict[str, Any]]:
    selected_layers = [layer] if layer in LAYERS else list(LAYERS)
    items: List[Dict[str, Any]] = []
    with _LOCK:
        for selected in selected_layers:
            items.extend(_all_for_user(selected, user_id))
    if not include_deleted:
        items = [item for item in items if item["status"] == "active"]
    items.sort(key=lambda item: (item["created_at"], item["display_id"]), reverse=True)
    return items


def list_pending_observations(user_id: str, *, unbatched_only: bool = False) -> List[Dict[str, Any]]:
    items = [
        item
        for item in list_memories(user_id, layer="observation")
        if item["review_status"] == "pending"
    ]
    if unbatched_only:
        items = [item for item in items if not item["diary_batch_id"]]
    return sorted(items, key=lambda item: (item["created_at"], item["display_id"]))


def mark_seen(layer: str, user_id: str, memory_id: str) -> Dict[str, Any] | None:
    return update_memory(layer, user_id, memory_id, metadata_updates={"seen": True})


def unread_counts(user_id: str) -> Dict[str, int]:
    counts = {
        layer: sum(1 for item in list_memories(user_id, layer=layer) if not item["seen"])
        for layer in LAYERS
    }
    counts["total"] = sum(counts.values())
    return counts


def _parse_created_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = now_china()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CHINA_TZ)
    return parsed


def _retrievable(item: Dict[str, Any]) -> bool:
    if item["status"] != "active":
        return False
    if item["layer"] == "observation":
        return item["review_status"] in {"confirmed", "revised"}
    return True


def _query_layer(layer: str, user_id: str, query: str, limit: int) -> List[Dict[str, Any]]:
    collection = collections[layer]
    if collection.count() == 0:
        return []
    result = collection.query(
        query_texts=[query],
        n_results=min(max(limit * 4, 8), collection.count()),
        where={"user_id": user_id},
        include=["documents", "metadatas", "distances"],
    )
    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    now = now_china()
    items: List[Dict[str, Any]] = []
    for index, memory_id in enumerate(ids):
        metadata = dict((metadatas[index] if index < len(metadatas) else {}) or {})
        item = _metadata_to_item(
            layer,
            str(memory_id),
            str(documents[index] if index < len(documents) else ""),
            metadata,
        )
        if not _retrievable(item):
            continue
        similarity = max(0.0, min(1.0, 1.0 - float(distances[index] if index < len(distances) else 1.0)))
        age_days = max(0.0, (now - _parse_created_at(item["created_at"]).astimezone(now.tzinfo)).total_seconds() / 86400.0)
        recency = math.exp(-age_days / 30.0)
        item["semantic_similarity"] = similarity
        item["recency"] = recency
        item["score"] = (
            0.55 * similarity
            + 0.15 * recency
            + 0.15 * (item["importance"] / 10.0)
            + 0.15 * (item["confidence"] / 10.0)
        )
        items.append(item)
    items.sort(key=lambda item: item["score"], reverse=True)
    return items[:limit]


def recall_for_chat(user_id: str, query: str, *, memory_k: int = 3, strategy_k: int = 2) -> Dict[str, List[Dict[str, Any]]]:
    if not (query or "").strip():
        return {"memories": [], "strategies": []}
    mixed = _query_layer("observation", user_id, query, memory_k)
    mixed.extend(_query_layer("reflection", user_id, query, memory_k))
    mixed.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    return {
        "memories": mixed[:memory_k],
        "strategies": _query_layer("strategy", user_id, query, strategy_k),
    }


def clear_user(user_id: str) -> Dict[str, int]:
    deleted: Dict[str, int] = {}
    with _LOCK:
        for layer in LAYERS:
            items = _all_for_user(layer, user_id)
            ids = [item["id"] for item in items]
            if ids:
                collections[layer].delete(ids=ids)
            deleted[layer] = len(ids)
    return deleted


def clear_all() -> Dict[str, int]:
    deleted: Dict[str, int] = {}
    with _LOCK:
        for layer in LAYERS:
            count = collections[layer].count()
            if count:
                collections[layer].delete(where={"layer": layer})
            deleted[layer] = count
    return deleted


def assign_diary_batch(user_id: str, observation_ids: Iterable[str], batch_id: str) -> List[Dict[str, Any]]:
    assigned: List[Dict[str, Any]] = []
    with _LOCK:
        for memory_id in observation_ids:
            item = update_memory(
                "observation",
                user_id,
                memory_id,
                metadata_updates={"diary_batch_id": batch_id},
            )
            if item:
                assigned.append(item)
    return assigned


def review_observation(
    user_id: str,
    memory_id: str,
    action: str,
    *,
    revised_content: str = "",
) -> Dict[str, Any] | None:
    action = (action or "").strip().lower()
    item = get_memory("observation", user_id, memory_id)
    if not item or item["review_status"] != "pending":
        return None
    if action == "confirm":
        return update_memory(
            "observation",
            user_id,
            memory_id,
            metadata_updates={
                "review_status": "confirmed",
                "confidence": max(9.0, item["confidence"]),
            },
        )
    if action == "revise":
        document = (revised_content or "").strip()
        if not document:
            raise ValueError("revised_content cannot be empty")
        return update_memory(
            "observation",
            user_id,
            memory_id,
            document=document,
            metadata_updates={
                "review_status": "revised",
                "confidence": 10.0,
                "importance": max(8.0, item["importance"]),
            },
        )
    if action == "delete":
        return update_memory(
            "observation",
            user_id,
            memory_id,
            metadata_updates={
                "review_status": "deleted",
                "status": "deleted",
                "confidence": 0.0,
            },
        )
    raise ValueError("unsupported review action")


def reviewed_observations_for_topic(user_id: str, topic: str) -> List[Dict[str, Any]]:
    if topic not in TOPICS:
        return []
    items = [
        item
        for item in list_memories(user_id, layer="observation")
        if item["review_status"] in {"confirmed", "revised"}
        and topic in item["topics"]
        and topic not in _json_list(item["metadata"].get("reflected_topics_json"))
    ]
    return sorted(items, key=lambda item: (item["created_at"], item["display_id"]))


def mark_observations_reflected(user_id: str, observation_ids: Iterable[str], topic: str) -> None:
    with _LOCK:
        for memory_id in observation_ids:
            item = get_memory("observation", user_id, memory_id)
            if not item:
                continue
            reflected_topics = _json_list(item["metadata"].get("reflected_topics_json"))
            if topic not in reflected_topics:
                reflected_topics.append(topic)
            update_memory(
                "observation",
                user_id,
                memory_id,
                metadata_updates={"reflected_topics_json": reflected_topics},
            )


def unused_reflections(user_id: str) -> List[Dict[str, Any]]:
    return sorted(
        [
            item
            for item in list_memories(user_id, layer="reflection")
            if not bool(item["metadata"].get("used_for_strategy", False))
        ],
        key=lambda item: (item["created_at"], item["display_id"]),
    )


def mark_reflections_used(user_id: str, reflection_ids: Iterable[str]) -> None:
    with _LOCK:
        for memory_id in reflection_ids:
            update_memory(
                "reflection",
                user_id,
                memory_id,
                metadata_updates={"used_for_strategy": True},
            )


def hierarchy_payload(user_id: str) -> Dict[str, Any]:
    layers = {
        layer: [
            {
                "id": item["display_id"],
                "layer": item["layer"],
                "description": item["description"],
                "topics": item["topics"],
                "scene": item["scene"],
                "importance": item["importance"],
                "confidence": item["confidence"],
                "created_at": item["created_at"],
                "review_status": item["review_status"],
                "linked_memory_ids": item["linked_memory_ids"],
                "is_new": not item["seen"],
            }
            for item in list_memories(user_id, layer=layer)
        ]
        for layer in LAYERS
    }
    return {
        "user_id": user_id,
        "layers": layers,
        "unread": unread_counts(user_id),
    }
