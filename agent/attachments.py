from __future__ import annotations

import base64
import io
import os
import re
import zipfile
from typing import Any, Dict, List
from xml.etree import ElementTree as ET

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css", ".scss",
    ".java", ".c", ".cpp", ".h", ".hpp", ".go", ".rs", ".sql", ".sh",
}

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".yaml", ".yml",
    ".log",
} | CODE_EXTENSIONS

OFFICE_MIMES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
}


def infer_attachment_mime(name: str, declared_mime: str = "") -> str:
    mime = str(declared_mime or "").strip().lower()
    if mime and mime != "application/octet-stream":
        return mime
    ext = os.path.splitext(str(name or "").lower())[1]
    if ext in OFFICE_MIMES:
        return OFFICE_MIMES[ext]
    if ext in TEXT_EXTENSIONS:
        return "text/plain"
    return mime or "application/octet-stream"


def is_supported_attachment(name: str, mime_type: str) -> bool:
    mime = infer_attachment_mime(name, mime_type)
    if mime.startswith("image/") or mime.startswith("audio/") or mime.startswith("text/"):
        return True
    if mime in {
        "application/pdf",
        "application/json",
        "application/xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }:
        return True
    ext = os.path.splitext(str(name or "").lower())[1]
    return ext in TEXT_EXTENSIONS or ext in OFFICE_MIMES


def decode_data_url_bytes(data_url: str) -> bytes:
    if not data_url or "," not in data_url:
        return b""
    encoded = data_url.split(",", 1)[1]
    return base64.b64decode(encoded)


def _decode_text_bytes(raw: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_pdf_text(raw: bytes) -> str:
    try:
        import pypdf  # type: ignore
        reader = pypdf.PdfReader(io.BytesIO(raw))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        return "\n\n".join(p for p in pages if p)
    except ImportError:
        pass
    try:
        import fitz  # type: ignore
        doc = fitz.open(stream=raw, filetype="pdf")
        pages = [(page.get_text("text") or "").strip() for page in doc]
        return "\n\n".join(p for p in pages if p)
    except ImportError:
        return "[提示：后端尚未安装 pypdf 或 pymupdf，暂无法直接提取该 PDF 文本，可安装 `pip install pypdf` 后重试，或截图发送关键页]"
    except Exception as exc:
        return f"[PDF 解析失败: {exc}]"


def _extract_docx_text(raw: bytes) -> str:
    try:
        import docx  # type: ignore
        document = docx.Document(io.BytesIO(raw))
        parts = [p.text.strip() for p in document.paragraphs if p.text and p.text.strip()]
        for table in document.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    parts.append(row_text)
        return "\n".join(parts)
    except ImportError:
        pass
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        texts: List[str] = []
        for para in root.iter():
            if para.tag.endswith("}p"):
                line = "".join(node.text for node in para.iter() if node.tag.endswith("}t") and node.text)
                if line.strip():
                    texts.append(line.strip())
        return "\n".join(texts)
    except Exception as exc:
        return f"[DOCX 解析失败: {exc}]"


def _extract_pptx_text(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            slide_names = sorted(
                [n for n in zf.namelist() if re.match(r"^ppt/slides/slide\d+\.xml$", n)],
                key=lambda s: int(re.findall(r"\d+", s)[-1]),
            )
            slides_text: List[str] = []
            for idx, name in enumerate(slide_names, 1):
                root = ET.fromstring(zf.read(name))
                items = [node.text.strip() for node in root.iter() if node.tag.endswith("}t") and node.text and node.text.strip()]
                if items:
                    slides_text.append(f"[幻灯片 {idx}]\n" + "\n".join(items))
            return "\n\n".join(slides_text)
    except Exception as exc:
        return f"[PPTX 解析失败: {exc}]"


def _extract_xlsx_text(raw: bytes) -> str:
    try:
        import openpyxl  # type: ignore
        wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
        sheets: List[str] = []
        for sheet in wb.worksheets:
            rows_out: List[str] = []
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c).strip() if c is not None else "" for c in row]
                if any(cells):
                    rows_out.append(" | ".join(cells))
            if rows_out:
                sheets.append(f"[工作表: {sheet.title}]\n" + "\n".join(rows_out[:200]))
        return "\n\n".join(sheets)
    except ImportError:
        pass
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            shared: List[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                sroot = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in sroot.iter():
                    if si.tag.endswith("}si"):
                        val = "".join(n.text for n in si.iter() if n.tag.endswith("}t") and n.text)
                        shared.append(val)
            return "\n".join(s for s in shared if s.strip())
    except Exception as exc:
        return f"[XLSX 解析失败: {exc}]"


def infer_file_type(name: str, declared_mime: str = "") -> str:
    mime = infer_attachment_mime(name, declared_mime)
    ext = os.path.splitext(str(name or "").lower())[1]
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if ext == ".pdf" or mime == "application/pdf":
        return "pdf"
    if ext == ".pptx" or mime == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
        return "pptx"
    if ext == ".docx" or mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return "docx"
    if ext == ".xlsx" or mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        return "xlsx"
    if ext in {".csv", ".tsv"} or mime == "text/csv":
        return "csv"
    if ext in {".md", ".markdown"} or mime == "text/markdown":
        return "markdown"
    if ext in CODE_EXTENSIONS:
        return "code"
    if ext in {".json", ".jsonl", ".xml", ".yaml", ".yml"}:
        return "structured"
    return "text"


def _clean_segment_text(text: str) -> str:
    text = (text or "").replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln).strip()


def _extract_heading_from_lines(text: str, fallback: str) -> str:
    lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
    for ln in lines[:6]:
        if re.fullmatch(r"\d+", ln):
            continue
        cleaned = re.sub(r"^#+\s*", "", ln).strip()
        if len(cleaned) >= 2:
            return cleaned[:60]
    return fallback


def _extract_pdf_segments(raw: bytes, file_name: str) -> List[Dict[str, Any]]:
    stem = os.path.splitext(file_name)[0]
    try:
        import pypdf  # type: ignore
        reader = pypdf.PdfReader(io.BytesIO(raw))
        segs: List[Dict[str, Any]] = []
        for idx, page in enumerate(reader.pages, 1):
            txt = _clean_segment_text(page.extract_text() or "")
            if not txt:
                continue
            segs.append({
                "location": f"P.{idx}",
                "page_num": idx,
                "section_title": _extract_heading_from_lines(txt, f"{stem} 第{idx}页"),
                "content": txt,
            })
        return segs
    except ImportError:
        pass
    try:
        import fitz  # type: ignore
        doc = fitz.open(stream=raw, filetype="pdf")
        segs = []
        for idx, page in enumerate(doc, 1):
            txt = _clean_segment_text(page.get_text("text") or "")
            if not txt:
                continue
            segs.append({
                "location": f"P.{idx}",
                "page_num": idx,
                "section_title": _extract_heading_from_lines(txt, f"{stem} 第{idx}页"),
                "content": txt,
            })
        doc.close()
        return segs
    except ImportError:
        return [{
            "location": "P.1",
            "page_num": 1,
            "section_title": stem,
            "content": "[提示：后端尚未安装 pypdf 或 pymupdf，暂无法直接提取该 PDF 文本，可安装 `pip install pypdf` 后重试]",
        }]
    except Exception as exc:
        return [{"location": "P.1", "page_num": 1, "section_title": stem, "content": f"[PDF 解析失败: {exc}]"}]


def _extract_pptx_segments(raw: bytes, file_name: str) -> List[Dict[str, Any]]:
    stem = os.path.splitext(file_name)[0]
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            slide_names = sorted(
                [n for n in zf.namelist() if re.match(r"^ppt/slides/slide\d+\.xml$", n)],
                key=lambda s: int(re.findall(r"\d+", s)[-1]),
            )
            segs: List[Dict[str, Any]] = []
            for idx, name in enumerate(slide_names, 1):
                root = ET.fromstring(zf.read(name))
                items = [node.text.strip() for node in root.iter() if node.tag.endswith("}t") and node.text and node.text.strip()]
                txt = _clean_segment_text("\n".join(items))
                if txt:
                    segs.append({
                        "location": f"幻灯片 {idx}",
                        "page_num": idx,
                        "section_title": _extract_heading_from_lines(txt, f"{stem} 幻灯片 {idx}"),
                        "content": txt,
                    })
            return segs
    except Exception as exc:
        return [{"location": "幻灯片 1", "page_num": 1, "section_title": stem, "content": f"[PPTX 解析失败: {exc}]"}]


def _extract_docx_segments(raw: bytes, file_name: str) -> List[Dict[str, Any]]:
    stem = os.path.splitext(file_name)[0]
    paragraphs: List[tuple[bool, str]] = []
    try:
        import docx  # type: ignore
        document = docx.Document(io.BytesIO(raw))
        for p in document.paragraphs:
            txt = (p.text or "").strip()
            if not txt:
                continue
            style_name = (getattr(p.style, "name", "") or "").lower()
            is_heading = "heading" in style_name or "title" in style_name or bool(re.match(r"^(第[一二三四五六七八九十百\d]+[章节节]|[\d]+(?:\.[\d]+)*\s+\S)", txt))
            paragraphs.append((is_heading, txt))
        for table in document.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paragraphs.append((False, row_text))
    except ImportError:
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                root = ET.fromstring(zf.read("word/document.xml"))
            for para in root.iter():
                if para.tag.endswith("}p"):
                    style_val = ""
                    for node in para.iter():
                        if node.tag.endswith("}pStyle"):
                            style_val = next(iter(node.attrib.values()), "").lower()
                    line = "".join(node.text for node in para.iter() if node.tag.endswith("}t") and node.text).strip()
                    if line:
                        is_heading = "heading" in style_val or "title" in style_val or bool(re.match(r"^(第[一二三四五六七八九十百\d]+[章节]|[\d]+(?:\.[\d]+)*\s+\S)", line))
                        paragraphs.append((is_heading, line))
        except Exception as exc:
            return [{"location": "第 1 节", "page_num": 1, "section_title": stem, "content": f"[DOCX 解析失败: {exc}]"}]

    if not paragraphs:
        return []
    segs: List[Dict[str, Any]] = []
    cur_title = stem
    cur_lines: List[str] = []
    sec_idx = 1
    for is_heading, line in paragraphs:
        if is_heading and cur_lines:
            segs.append({
                "location": f"第 {sec_idx} 节",
                "page_num": sec_idx,
                "section_title": cur_title[:60],
                "content": "\n".join(cur_lines),
            })
            sec_idx += 1
            cur_title = line
            cur_lines = [line]
        else:
            if is_heading and not cur_lines:
                cur_title = line
            cur_lines.append(line)
    if cur_lines:
        segs.append({
            "location": f"第 {sec_idx} 节",
            "page_num": sec_idx,
            "section_title": cur_title[:60],
            "content": "\n".join(cur_lines),
        })
    return segs


def _extract_markdown_segments(text: str, file_name: str) -> List[Dict[str, Any]]:
    stem = os.path.splitext(file_name)[0]
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return []
    lines = cleaned.split("\n")
    segs: List[Dict[str, Any]] = []
    cur_title = stem
    cur_lines: List[str] = []
    sec_idx = 1
    for ln in lines:
        m = re.match(r"^(#{1,4})\s+(.+)$", ln.strip())
        if m:
            if cur_lines:
                body = "\n".join(cur_lines).strip()
                if body:
                    segs.append({
                        "location": f"§{sec_idx}",
                        "page_num": sec_idx,
                        "section_title": cur_title[:60],
                        "content": body,
                    })
                    sec_idx += 1
            cur_title = m.group(2).strip()
            cur_lines = [ln]
        else:
            cur_lines.append(ln)
    if cur_lines:
        body = "\n".join(cur_lines).strip()
        if body:
            segs.append({
                "location": f"§{sec_idx}",
                "page_num": sec_idx,
                "section_title": cur_title[:60],
                "content": body,
            })
    return segs


def _extract_tabular_segments(raw: bytes, file_name: str, file_type: str) -> List[Dict[str, Any]]:
    stem = os.path.splitext(file_name)[0]
    segs: List[Dict[str, Any]] = []
    if file_type == "csv":
        lines = [ln.strip() for ln in _decode_text_bytes(raw).replace("\r\n", "\n").split("\n") if ln.strip()]
        if not lines:
            return []
        header = lines[0]
        rows = lines[1:] if len(lines) > 1 else lines
        batch = 25
        for idx, start in enumerate(range(0, len(rows), batch), 1):
            chunk_rows = rows[start : start + batch]
            body = f"表头: {header}\n" + "\n".join(chunk_rows) if len(lines) > 1 else "\n".join(chunk_rows)
            segs.append({
                "location": f"行 {start + 1}-{start + len(chunk_rows)}",
                "page_num": idx,
                "section_title": f"{stem} (行 {start + 1}-{start + len(chunk_rows)})",
                "content": body,
            })
        return segs

    text = _extract_xlsx_text(raw)
    if not text:
        return []
    blocks = re.split(r"(?=\[工作表: )", text)
    idx = 1
    for blk in blocks:
        blk = blk.strip()
        if not blk:
            continue
        m = re.match(r"\[工作表:\s*([^\]]+)\]\n?(.*)", blk, re.S)
        sheet_name = m.group(1).strip() if m else f"Sheet{idx}"
        body = (m.group(2) if m else blk).strip()
        segs.append({
            "location": f"工作表 {sheet_name}",
            "page_num": idx,
            "section_title": f"{stem} · {sheet_name}",
            "content": body,
        })
        idx += 1
    return segs


def _extract_code_segments(text: str, file_name: str) -> List[Dict[str, Any]]:
    stem = os.path.splitext(file_name)[0]
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return []
    lines = cleaned.split("\n")
    segs: List[Dict[str, Any]] = []
    cur_title = stem
    cur_lines: List[str] = []
    sec_idx = 1
    def_re = re.compile(r"^(?:async\s+def|def|class|export\s+(?:default\s+)?(?:async\s+)?function|function|struct|interface|fn)\s+([A-Za-z_][A-Za-z0-9_]*)")
    for ln in lines:
        m = def_re.match(ln)
        if m and len("\n".join(cur_lines)) >= 120:
            segs.append({
                "location": f"代码段 {sec_idx}",
                "page_num": sec_idx,
                "section_title": cur_title[:60],
                "content": "\n".join(cur_lines).strip(),
            })
            sec_idx += 1
            cur_title = m.group(1)
            cur_lines = [ln]
        else:
            if m and not cur_lines:
                cur_title = m.group(1)
            cur_lines.append(ln)
    if cur_lines:
        segs.append({
            "location": f"代码段 {sec_idx}",
            "page_num": sec_idx,
            "section_title": cur_title[:60],
            "content": "\n".join(cur_lines).strip(),
        })
    return segs


def extract_structured_segments(item: Dict[str, Any], max_chars: int = 200000) -> tuple[str, str, List[Dict[str, Any]]]:
    """根据文件类型提取结构化分段，返回 (file_type, full_text, segments)。"""
    name = str(item.get("name") or "学习资料")
    mime = infer_attachment_mime(name, str(item.get("type") or ""))
    file_type = infer_file_type(name, mime)
    raw = decode_data_url_bytes(str(item.get("data") or ""))
    stem = os.path.splitext(name)[0]

    if file_type == "image":
        txt = f"[图片资料: {name}]"
        return file_type, txt, [{"location": "图片", "page_num": 1, "section_title": stem, "content": txt}]
    if file_type == "audio":
        txt = f"[音频资料: {name}]"
        return file_type, txt, [{"location": "音频", "page_num": 1, "section_title": stem, "content": txt}]
    if not raw:
        return file_type, "", []

    if file_type == "pdf":
        segments = _extract_pdf_segments(raw, name)
    elif file_type == "pptx":
        segments = _extract_pptx_segments(raw, name)
    elif file_type == "docx":
        segments = _extract_docx_segments(raw, name)
    elif file_type == "markdown":
        segments = _extract_markdown_segments(_decode_text_bytes(raw), name)
    elif file_type in {"xlsx", "csv"}:
        segments = _extract_tabular_segments(raw, name, file_type)
    elif file_type == "code":
        segments = _extract_code_segments(_decode_text_bytes(raw), name)
    else:
        txt = _clean_segment_text(_decode_text_bytes(raw))
        segments = [{"location": "全文", "page_num": 1, "section_title": _extract_heading_from_lines(txt, stem), "content": txt}] if txt else []

    full_text = "\n\n".join(s["content"] for s in segments if s.get("content")).strip()
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars]
    return file_type, full_text, segments


def extract_document_text(item: Dict[str, Any], max_chars: int = 12000) -> str:
    name = str(item.get("name") or "附件")
    mime = infer_attachment_mime(name, str(item.get("type") or ""))
    data_url = str(item.get("data") or "")
    raw = decode_data_url_bytes(data_url)
    if not raw:
        return ""

    ext = os.path.splitext(name.lower())[1]
    text = ""
    if mime == "application/pdf" or ext == ".pdf":
        text = _extract_pdf_text(raw)
    elif ext == ".docx" or mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        text = _extract_docx_text(raw)
    elif ext == ".pptx" or mime == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
        text = _extract_pptx_text(raw)
    elif ext == ".xlsx" or mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        text = _extract_xlsx_text(raw)
    elif mime.startswith("text/") or mime in {"application/json", "application/xml"} or ext in TEXT_EXTENSIONS:
        text = _decode_text_bytes(raw)

    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n...(文件内容过长，已截取前 {max_chars} 字符)"
    return text


def build_multimodal_user_content(
    user_text: str,
    attachments: List[Dict[str, Any]] | None,
    allow_image: bool = True,
    allow_audio: bool = True,
) -> Any:
    text_blocks: List[str] = [user_text] if user_text else []
    media_parts: List[Dict[str, Any]] = []

    for item in attachments or []:
        name = str(item.get("name") or "媒体文件")
        mime_type = infer_attachment_mime(name, str(item.get("type") or ""))
        data_url = str(item.get("data") or "")
        if mime_type.startswith("image/") and allow_image and data_url.startswith("data:image/"):
            media_parts.append({"type": "image_url", "image_url": {"url": data_url}})
        elif mime_type.startswith("audio/") and allow_audio and data_url.startswith("data:audio/"):
            encoded = data_url.split(",", 1)[-1]
            subtype = mime_type.split("/", 1)[-1].split(";", 1)[0]
            media_parts.append({
                "type": "input_audio",
                "input_audio": {
                    "data": encoded,
                    "format": "wav" if subtype in {"wav", "x-wav", "wave"} else subtype,
                },
            })
        elif not mime_type.startswith("image/") and not mime_type.startswith("audio/"):
            doc_text = extract_document_text(item)
            if doc_text:
                text_blocks.append(f"【用户上传文件：{name}】\n```\n{doc_text}\n```")
            else:
                text_blocks.append(f"【用户上传了文件：{name}（{mime_type}），但未能提取文本内容】")

    combined_text = "\n\n".join(text_blocks).strip()
    if not media_parts:
        return combined_text
    return [{"type": "text", "text": combined_text or "请查看我发送的媒体文件。"}] + media_parts
