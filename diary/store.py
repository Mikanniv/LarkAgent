from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from core.config import DIARY_DIR
from core.utils import memory_date_from_payload
from storage import r2_store


def ensure_diary_dir() -> None:
    DIARY_DIR.mkdir(parents=True, exist_ok=True)


def normalize_user_id(user_id: str | None = None) -> str:
    safe = re.sub(r"[^0-9A-Za-z_-]+", "_", str(user_id or "local_user")).strip("_")
    return (safe or "local_user")[:80]


def diary_user_dir(user_id: str | None = None) -> Path:
    path = DIARY_DIR / normalize_user_id(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def diary_path(date_key: str, user_id: str | None = None) -> Path:
    return diary_user_dir(user_id) / f"{date_key}-user.md"


def diary_object_key(date_key: str, user_id: str | None = None) -> str:
    return r2_store.object_key(normalize_user_id(user_id), f"{date_key}-user.md")


def read_user_diary(date_key: str, user_id: str | None = None) -> str:
    if r2_store.is_enabled():
        return r2_store.get_text(diary_object_key(date_key, user_id=user_id)) or ""
    path = diary_path(date_key, user_id=user_id)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_user_diary(date_key: str, content: str, user_id: str | None = None) -> None:
    normalized = (content or "").replace("\r\n", "\n").rstrip()
    value = f"{normalized}\n" if normalized else ""
    if r2_store.is_enabled():
        r2_store.put_text(
            diary_object_key(date_key, user_id=user_id),
            value,
            content_type="text/markdown; charset=utf-8",
        )
        return
    path = diary_path(date_key, user_id=user_id)
    path.write_text(value, encoding="utf-8")


def delete_user_diary_file(date_key: str, user_id: str | None = None) -> int:
    if r2_store.is_enabled():
        return r2_store.delete_keys([diary_object_key(date_key, user_id=user_id)])
    path = diary_path(date_key, user_id=user_id)
    if not path.exists():
        return 0
    path.unlink()
    return 1


def list_diary_dates(user_id: str | None = None) -> List[str]:
    dates = set()
    if r2_store.is_enabled():
        prefix = f"{r2_store.object_key(normalize_user_id(user_id))}/"
        keys = r2_store.list_keys(prefix)
        names = [Path(key).name for key in keys if key.endswith("-user.md")]
    else:
        names = [path.name for path in diary_user_dir(user_id).glob("*-user.md")]
    for name in names:
        maybe_date = name.removesuffix("-user.md")
        try:
            datetime.fromisoformat(maybe_date)
            dates.add(maybe_date)
        except ValueError:
            continue
    dates.add(memory_date_from_payload(""))
    return sorted(dates, reverse=True)


def get_diary_payload(date_key: str, user_id: str | None = None) -> Dict:
    return {
        "date": date_key,
        "user_id": normalize_user_id(user_id),
        "is_today": date_key == memory_date_from_payload(""),
        "user_markdown": read_user_diary(date_key, user_id=user_id),
    }


def get_diary_index_payload(selected_date: str = "", user_id: str | None = None) -> Dict:
    dates = list_diary_dates(user_id=user_id)
    date_key = selected_date if selected_date in dates else dates[0]
    return {
        "dates": dates,
        "selected_date": date_key,
        "selected": get_diary_payload(date_key, user_id=user_id),
    }


def save_user_diary(date_key: str, markdown: str, user_id: str | None = None) -> Dict:
    write_user_diary(date_key, markdown, user_id=user_id)
    return get_diary_index_payload(date_key, user_id=user_id)


def delete_user_diary(date_key: str, user_id: str | None = None) -> Dict:
    deleted = delete_user_diary_file(date_key, user_id=user_id)
    return {"ok": True, "deleted": deleted, **get_diary_index_payload(date_key, user_id=user_id)}


def delete_diary_data(user_id: str | None = None) -> Dict:
    safe_user_id = normalize_user_id(user_id)
    deleted_r2 = 0
    r2_error = ""
    if r2_store.is_enabled():
        try:
            deleted_r2 = r2_store.delete_prefix(f"{r2_store.object_key(safe_user_id)}/")
        except Exception as exc:
            r2_error = str(exc)
    deleted_local_files = 0
    user_dir = DIARY_DIR / safe_user_id
    if user_dir.exists():
        deleted_local_files = len([path for path in user_dir.rglob("*") if path.is_file()])
        shutil.rmtree(user_dir)
    return {
        "user_id": safe_user_id,
        "deleted_r2": deleted_r2,
        "deleted_local_files": deleted_local_files,
        "r2_error": r2_error,
    }
