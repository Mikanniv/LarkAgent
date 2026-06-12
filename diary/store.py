import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from core.config import DIARY_DIR, MEMORY_DIR
from core.utils import memory_date_from_payload, normalize_timestamp_to_china
from storage import r2_store


AI_DIARY_PLACEHOLDER = "云雀正在努力总结中..."


def ensure_diary_dir() -> None:
    DIARY_DIR.mkdir(parents=True, exist_ok=True)


def normalize_user_id(user_id: str | None = None) -> str:
    safe = re.sub(r"[^0-9A-Za-z_-]+", "_", str(user_id or "local_user")).strip("_")
    return (safe or "local_user")[:80]


def diary_user_dir(user_id: str | None = None) -> Path:
    path = DIARY_DIR / normalize_user_id(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def diary_paths(date_key: str, user_id: str | None = None) -> Dict[str, Path]:
    base = diary_user_dir(user_id)
    return {
        "user": base / f"{date_key}-user.md",
        "ai": base / f"{date_key}-ai.md",
        "ai_meta": base / f"{date_key}-ai.json",
    }


def diary_object_key(date_key: str, kind: str, user_id: str | None = None) -> str:
    return r2_store.object_key(normalize_user_id(user_id), f"{date_key}-{kind}")


def legacy_diary_paths(date_key: str) -> Dict[str, Path]:
    return {
        "user": MEMORY_DIR / f"{date_key}-user.md",
        "ai": MEMORY_DIR / f"{date_key}-ai.md",
    }


def read_markdown(path: Path, fallback: str = "") -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return fallback


def write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = (content or "").replace("\r\n", "\n").rstrip()
    path.write_text(f"{normalized}\n" if normalized else "", encoding="utf-8")


def read_diary_markdown(date_key: str, kind: str, user_id: str | None = None, fallback: str = "") -> str:
    if r2_store.is_enabled():
        content = r2_store.get_text(diary_object_key(date_key, f"{kind}.md", user_id=user_id))
        return content if content is not None else fallback
    return read_markdown(diary_paths(date_key, user_id=user_id)[kind], fallback)


def write_diary_markdown(date_key: str, kind: str, content: str, user_id: str | None = None) -> None:
    normalized = (content or "").replace("\r\n", "\n").rstrip()
    if r2_store.is_enabled():
        r2_store.put_text(
            diary_object_key(date_key, f"{kind}.md", user_id=user_id),
            f"{normalized}\n" if normalized else "",
            content_type="text/markdown; charset=utf-8",
        )
        return
    write_markdown(diary_paths(date_key, user_id=user_id)[kind], normalized)


def delete_diary_markdown(date_key: str, kind: str, user_id: str | None = None) -> int:
    if r2_store.is_enabled():
        return r2_store.delete_keys([diary_object_key(date_key, f"{kind}.md", user_id=user_id)])
    deleted = 0
    path = diary_paths(date_key, user_id=user_id)[kind]
    if path.exists():
        path.unlink()
        deleted += 1
    if kind == "user" and normalize_user_id(user_id) == "local_user":
        legacy_path = legacy_diary_paths(date_key)["user"]
        if legacy_path.exists():
            legacy_path.unlink()
            deleted += 1
    return deleted


def default_ai_diary_meta() -> Dict:
    return {"status": "not_ready"}


def read_ai_diary_meta(date_key: str, user_id: str | None = None) -> Dict:
    if r2_store.is_enabled():
        content = r2_store.get_text(diary_object_key(date_key, "ai.json", user_id=user_id))
        if not content:
            return default_ai_diary_meta()
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return default_ai_diary_meta()
        return data if isinstance(data, dict) else default_ai_diary_meta()
    path = diary_paths(date_key, user_id=user_id)["ai_meta"]
    if not path.exists():
        return default_ai_diary_meta()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_ai_diary_meta()
    return data if isinstance(data, dict) else default_ai_diary_meta()


def write_ai_diary_meta(date_key: str, metadata: Dict, user_id: str | None = None) -> None:
    if r2_store.is_enabled():
        r2_store.put_text(
            diary_object_key(date_key, "ai.json", user_id=user_id),
            json.dumps(metadata, ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
        )
        return
    path = diary_paths(date_key, user_id=user_id)["ai_meta"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_ai_diary_pending(
    date_key: str,
    user_id: str | None = None,
    structured: Dict | None = None,
    memory_links: Dict | None = None,
) -> None:
    metadata = {
        "status": "pending",
        "generated_at": normalize_timestamp_to_china(""),
        "version": "v1.1",
        "memory_links": memory_links or {
            "preferences": [],
            "events": [],
            "routines": [],
            "relationships": [],
            "summary": [],
        },
    }
    if structured:
        metadata["structured"] = structured
    write_ai_diary_meta(
        date_key,
        metadata,
        user_id=user_id,
    )


def mark_ai_diary_reviewed(
    date_key: str,
    status: str,
    correction: str = "",
    memory_id: str = "",
    memory_links: Dict | None = None,
    review_items: List[Dict] | None = None,
    user_id: str | None = None,
) -> Dict:
    metadata = {
        **read_ai_diary_meta(date_key, user_id=user_id),
        "status": status if status in {"confirmed", "corrected"} else "confirmed",
        "reviewed_at": normalize_timestamp_to_china(""),
    }
    if correction.strip():
        metadata["correction"] = correction.strip()
    if memory_id:
        metadata["memory_id"] = memory_id
    if memory_links is not None:
        metadata["memory_links"] = memory_links
    if review_items is not None:
        metadata["review_items"] = review_items
    structured = metadata.get("structured")
    if isinstance(structured, dict):
        review = structured.setdefault("review", {})
        review["status"] = metadata["status"]
        review["review_text"] = correction.strip()
        review["review_timestamp"] = metadata["reviewed_at"]
        if memory_links is not None:
            review["memory_links"] = memory_links
        if review_items is not None:
            review["items"] = review_items
    write_ai_diary_meta(date_key, metadata, user_id=user_id)
    return metadata


def get_diary_payload(date_key: str, user_id: str | None = None) -> Dict:
    paths = diary_paths(date_key, user_id=user_id)
    legacy_paths = legacy_diary_paths(date_key) if normalize_user_id(user_id) == "local_user" else {}
    legacy_user_text = "" if r2_store.is_enabled() else read_markdown(legacy_paths["user"]) if legacy_paths else ""
    legacy_ai_text = "" if r2_store.is_enabled() else read_markdown(legacy_paths["ai"]) if legacy_paths else ""
    user_text = read_diary_markdown(date_key, "user", user_id=user_id, fallback=legacy_user_text)
    raw_ai_text = read_diary_markdown(date_key, "ai", user_id=user_id, fallback=legacy_ai_text)
    ai_meta = read_ai_diary_meta(date_key, user_id=user_id)
    ai_status = ai_meta.get("status", "not_ready")
    today = memory_date_from_payload("")
    if date_key >= today and ai_status == "pending":
        ai_status = "not_ready"
    visible_ai_statuses = {"pending", "confirmed", "corrected"}
    ai_text = raw_ai_text if ai_status in visible_ai_statuses and raw_ai_text.strip() else AI_DIARY_PLACEHOLDER
    return {
        "date": date_key,
        "user_id": normalize_user_id(user_id),
        "is_today": date_key == today,
        "memory_dir": str(diary_user_dir(user_id)),
        "user_markdown": user_text,
        "ai_markdown": ai_text,
        "ai_raw_markdown": raw_ai_text if ai_status == "pending" else "",
        "ai_status": ai_status,
        "ai_structured": ai_meta.get("structured") if ai_status in visible_ai_statuses else None,
        "memory_links": ai_meta.get("memory_links", {}),
        "review_items": ai_meta.get("review_items", []),
        "ai_review_available": ai_status == "pending" and bool(raw_ai_text.strip()),
        "ai_placeholder": AI_DIARY_PLACEHOLDER,
        "user_path": str(paths["user"]),
        "ai_path": str(paths["ai"]),
    }


def list_diary_dates(user_id: str | None = None) -> List[str]:
    ensure_diary_dir()
    dates = set()
    if r2_store.is_enabled():
        prefix = r2_store.object_key(normalize_user_id(user_id))
        for key in r2_store.list_keys(f"{prefix}/"):
            stem = Path(key).stem
            if stem.endswith("-user") or stem.endswith("-ai"):
                maybe_date = stem.rsplit("-", 1)[0]
                try:
                    datetime.fromisoformat(maybe_date)
                    dates.add(maybe_date)
                except ValueError:
                    continue
        dates.add(memory_date_from_payload(""))
        return sorted(dates, reverse=True)

    bases = [diary_user_dir(user_id)]
    if normalize_user_id(user_id) == "local_user":
        bases.extend([MEMORY_DIR, DIARY_DIR])
    for base in bases:
        if not base.exists():
            continue
        for path in base.glob("*.md"):
            stem = path.stem
            if stem.endswith("-user") or stem.endswith("-ai"):
                maybe_date = stem.rsplit("-", 1)[0]
                try:
                    datetime.fromisoformat(maybe_date)
                    dates.add(maybe_date)
                except ValueError:
                    continue
    dates.add(memory_date_from_payload(""))
    return sorted(dates, reverse=True)


def latest_pending_ai_diary_date(dates: List[str], user_id: str | None = None) -> str:
    for date_key in sorted(dates, reverse=True):
        metadata = read_ai_diary_meta(date_key, user_id=user_id)
        if metadata.get("status") == "pending" and read_markdown(diary_paths(date_key, user_id=user_id)["ai"]).strip():
            return date_key
    return ""


def get_diary_index_payload(selected_date: str = "", user_id: str | None = None) -> Dict:
    dates = list_diary_dates(user_id=user_id)
    date_key = selected_date if selected_date in dates else latest_pending_ai_diary_date(dates, user_id=user_id) or dates[0]
    return {
        "dates": dates,
        "selected_date": date_key,
        "selected": get_diary_payload(date_key, user_id=user_id),
    }


def save_user_diary(date_key: str, markdown: str, user_id: str | None = None) -> Dict:
    write_diary_markdown(date_key, "user", markdown, user_id=user_id)
    return get_diary_index_payload(date_key, user_id=user_id)


def delete_user_diary(date_key: str, user_id: str | None = None) -> Dict:
    deleted = delete_diary_markdown(date_key, "user", user_id=user_id)
    return {"ok": True, "deleted": deleted, **get_diary_index_payload(date_key, user_id=user_id)}


def delete_diary_data(user_id: str | None = None) -> Dict:
    safe_user_id = normalize_user_id(user_id)
    deleted_r2 = 0
    if r2_store.is_enabled():
        deleted_r2 = r2_store.delete_prefix(f"{r2_store.object_key(safe_user_id)}/")

    deleted_local_files = 0
    user_dir = DIARY_DIR / safe_user_id
    if user_dir.exists():
        deleted_local_files = len([path for path in user_dir.rglob("*") if path.is_file()])
        shutil.rmtree(user_dir)

    if safe_user_id == "local_user":
        for path in list(MEMORY_DIR.glob("*-user.md")) + list(MEMORY_DIR.glob("*-ai.md")):
            if path.is_file():
                path.unlink()
                deleted_local_files += 1

    return {
        "user_id": safe_user_id,
        "deleted_r2": deleted_r2,
        "deleted_local_files": deleted_local_files,
    }
