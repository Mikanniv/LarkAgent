from datetime import datetime
from pathlib import Path
from typing import Dict, List

from core.config import DIARY_DIR, MEMORY_DIR
from core.utils import memory_date_from_payload


def ensure_diary_dir() -> None:
    DIARY_DIR.mkdir(parents=True, exist_ok=True)


def diary_paths(date_key: str) -> Dict[str, Path]:
    ensure_diary_dir()
    return {
        "user": DIARY_DIR / f"{date_key}-user.md",
        "ai": DIARY_DIR / f"{date_key}-ai.md",
    }


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


def get_diary_payload(date_key: str) -> Dict:
    paths = diary_paths(date_key)
    legacy_paths = legacy_diary_paths(date_key)
    user_text = read_markdown(paths["user"], read_markdown(legacy_paths["user"]))
    ai_text = read_markdown(
        paths["ai"],
        read_markdown(legacy_paths["ai"], "AI 记忆会根据当天对话和状态自动更新。"),
    )
    today = memory_date_from_payload("")
    return {
        "date": date_key,
        "is_today": date_key == today,
        "memory_dir": str(DIARY_DIR),
        "user_markdown": user_text,
        "ai_markdown": ai_text,
        "user_path": str(paths["user"]),
        "ai_path": str(paths["ai"]),
    }


def list_diary_dates() -> List[str]:
    ensure_diary_dir()
    dates = set()
    for base in (DIARY_DIR, MEMORY_DIR):
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


def get_diary_index_payload(selected_date: str = "") -> Dict:
    dates = list_diary_dates()
    date_key = selected_date if selected_date in dates else dates[0]
    return {
        "dates": dates,
        "selected_date": date_key,
        "selected": get_diary_payload(date_key),
    }


def save_user_diary(date_key: str, markdown: str) -> Dict:
    write_markdown(diary_paths(date_key)["user"], markdown)
    return get_diary_index_payload(date_key)

