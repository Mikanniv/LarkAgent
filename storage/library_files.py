from __future__ import annotations

import base64
import hashlib
import io
import re
import subprocess
from pathlib import Path

from core.config import UPLOADS_DIR

_SAFE_EXT_RE = re.compile(r"^\.[a-z0-9]{1,10}$")


def safe_user_dir(user_id: str) -> str:
    uid = (user_id or "default").strip()
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()[:24]


def _sanitize_ext(file_name: str, file_type: str = "") -> str:
    ext = Path(file_name or "").suffix.lower().strip()
    if _SAFE_EXT_RE.match(ext):
        return ext
    fallback = {
        "pdf": ".pdf",
        "pptx": ".pptx",
        "docx": ".docx",
        "markdown": ".md",
        "image": ".png",
        "audio": ".mp3",
    }.get((file_type or "").lower(), ".bin")
    return fallback


def _decode_data_url(data_url: str) -> bytes | None:
    raw = str(data_url or "").strip()
    if not raw:
        return None
    if "," in raw and raw.startswith("data:"):
        _, b64 = raw.split(",", 1)
    else:
        b64 = raw
    try:
        return base64.b64decode(b64, validate=False)
    except Exception:
        return None


def _generate_thumbnail(raw_path: Path, thumb_path: Path, file_type: str) -> bool:
    ft = (file_type or "").lower()
    ext = raw_path.suffix.lower()
    try:
        if ft == "image" or ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
            from PIL import Image

            with Image.open(raw_path) as img:
                img = img.convert("RGB")
                img.thumbnail((420, 420))
                img.save(thumb_path, format="PNG", optimize=True)
            return thumb_path.is_file()
        if ft == "pdf" or ext == ".pdf":
            proc = subprocess.run(
                ["sips", "-s", "format", "png", "-Z", "420", str(raw_path), "--out", str(thumb_path)],
                capture_output=True,
                timeout=10,
                check=False,
            )
            return proc.returncode == 0 and thumb_path.is_file() and thumb_path.stat().st_size > 0
        if ext in {".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx"}:
            proc = subprocess.run(
                ["qlmanage", "-t", "-s", "420", "-o", str(thumb_path.parent), str(raw_path)],
                capture_output=True,
                timeout=12,
                check=False,
            )
            generated = thumb_path.parent / f"{raw_path.name}.png"
            if proc.returncode == 0 and generated.is_file() and generated.stat().st_size > 0:
                generated.replace(thumb_path)
                return True
    except Exception:
        return False
    return False


def save_raw_and_thumbnail(
    user_id: str,
    file_id: str,
    file_name: str,
    file_type: str,
    data_url: str,
) -> tuple[str, str]:
    raw_bytes = _decode_data_url(data_url)
    if not raw_bytes:
        return "", ""
    user_folder = safe_user_dir(user_id)
    ext = _sanitize_ext(file_name, file_type)
    target_dir = UPLOADS_DIR / user_folder
    target_dir.mkdir(parents=True, exist_ok=True)

    raw_rel = f"{user_folder}/{file_id}{ext}"
    raw_path = UPLOADS_DIR / raw_rel
    raw_path.write_bytes(raw_bytes)

    thumb_rel = f"{user_folder}/{file_id}.thumb.png"
    thumb_path = UPLOADS_DIR / thumb_rel
    if not _generate_thumbnail(raw_path, thumb_path, file_type):
        thumb_rel = ""
        if thumb_path.exists():
            try:
                thumb_path.unlink()
            except OSError:
                pass
    return raw_rel, thumb_rel


def resolve_upload_path(rel_path: str) -> Path | None:
    rel = str(rel_path or "").strip().lstrip("/")
    if not rel:
        return None
    try:
        base = UPLOADS_DIR.resolve()
        candidate = (base / rel).resolve()
        if not candidate.is_relative_to(base):
            return None
        return candidate if candidate.is_file() else None
    except Exception:
        return None


def delete_upload_files(*rel_paths: str) -> None:
    for rel in rel_paths:
        path = resolve_upload_path(rel)
        if path:
            try:
                path.unlink()
            except OSError:
                pass


def ensure_office_preview_dir(raw_path: Path) -> Path | None:
    """使用 macOS QuickLook (qlmanage -p) 将 .ppt/.pptx/.doc/.docx/.xls/.xlsx 渲染为完整可视化 HTML 预览目录并缓存。"""
    if not raw_path or not raw_path.is_file():
        return None
    preview_dir = raw_path.parent / f"{raw_path.name}.qlpreview"
    html_file = preview_dir / "Preview.html"
    if html_file.is_file():
        return preview_dir
    try:
        proc = subprocess.run(
            ["qlmanage", "-p", "-o", str(raw_path.parent), str(raw_path)],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if proc.returncode == 0 and html_file.is_file():
            return preview_dir
    except Exception:
        return None
    return None
