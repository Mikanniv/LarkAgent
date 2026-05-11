from __future__ import annotations

import argparse
import html
from pathlib import Path
import sys
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import MEMORY_DIR
from memory.db import collection
from memory.schema import apply_decay, create_memory, add_memory, delete_memory, list_memories, now_local, recall


TYPE_LABEL = {
    "event": "事件",
    "routine": "习惯",
    "preference": "偏好",
    "relationship": "关系",
    "summary": "总结",
}


def short_text(value: str, width: int = 34) -> str:
    value = " ".join((value or "").split())
    return value if len(value) <= width else value[: width - 1] + "…"


def flatten_recall_results(results: Dict[str, List[List[Any]]]) -> List[Dict[str, Any]]:
    ids = (results.get("ids") or [[]])[0]
    documents = (results.get("documents") or [[]])[0]
    metadatas = (results.get("metadatas") or [[]])[0]
    distances = (results.get("distances") or [[]])[0]
    scores = (results.get("scores") or [[]])[0]
    rows = []
    for index, document in enumerate(documents):
        rows.append(
            {
                "id": ids[index] if index < len(ids) else "",
                "document": document,
                "metadata": metadatas[index] if index < len(metadatas) else {},
                "distance": distances[index] if index < len(distances) else None,
                "score": scores[index] if index < len(scores) else None,
            }
        )
    return rows


def table_rows(items: List[Dict[str, Any]], show_score: bool = False) -> List[List[str]]:
    rows = []
    for item in items:
        metadata = item.get("metadata") or {}
        row = [
            short_text(item.get("id", ""), 8),
            TYPE_LABEL.get(metadata.get("type"), metadata.get("type", "-")),
            metadata.get("date", "-"),
            f"{float(metadata.get('importance', 0.0)):.2f}",
            f"{float(metadata.get('confidence', 0.0)):.2f}",
            metadata.get("source", "-"),
            short_text(item.get("document", "")),
        ]
        if show_score:
            score = item.get("score")
            distance = item.get("distance")
            row.insert(3, "-" if score is None else f"{float(score):.2f}")
            row.insert(4, "-" if distance is None else f"{float(distance):.2f}")
        rows.append(row)
    return rows


def print_table(items: List[Dict[str, Any]], show_score: bool = False) -> None:
    headers = ["id", "类型", "日期", "重要度", "置信度", "来源", "内容"]
    if show_score:
        headers = ["id", "类型", "日期", "召回分", "距离", "重要度", "置信度", "来源", "内容"]
    rows = table_rows(items, show_score=show_score)
    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(widths[index], len(cell)) for index, cell in enumerate(row)]

    def line(parts: List[str]) -> str:
        return " | ".join(parts[index].ljust(widths[index]) for index in range(len(parts)))

    print(line(headers))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(line(row))


def seed_demo_memories(user_id: str = "debug_user") -> List[str]:
    now = now_local()
    samples = [
        create_memory(
            document="用户明确表示，自己低落时希望云雀先安慰情绪，再慢慢给建议。",
            timestamp=now.isoformat(timespec="seconds"),
            user="user",
            user_id=user_id,
            type="preference",
            source="conversation",
            has_emotion=True,
            valence=-0.45,
            arousal=0.66,
            confidence=0.88,
            text=True,
            audio=False,
            video=False,
            confirmation="corrected",
        ),
        create_memory(
            document="用户最近在准备大创项目答辩，担心系统架构讲不清楚。",
            timestamp=now.isoformat(timespec="seconds"),
            user="user",
            user_id=user_id,
            type="event",
            source="diary_user",
            has_emotion=True,
            valence=-0.35,
            arousal=0.72,
            confidence=0.82,
            text=True,
            audio=False,
            video=False,
        ),
        create_memory(
            document="用户连续多天提到睡眠不足，通常在晚上更容易焦虑。",
            timestamp=now.isoformat(timespec="seconds"),
            user="ai",
            user_id=user_id,
            type="routine",
            source="inference",
            has_emotion=True,
            valence=-0.40,
            arousal=0.58,
            confidence=0.74,
            text=True,
            audio=True,
            video=False,
        ),
    ]
    ids = []
    for index, memory in enumerate(samples, start=1):
        ids.append(add_memory(memory, memory_id=f"{user_id}_demo_{index}"))
    return ids


def render_html(items: List[Dict[str, Any]], output: Path, title: str) -> None:
    cards = []
    for item in items:
        metadata = item.get("metadata") or {}
        score = item.get("score")
        score_html = "" if score is None else f"<span>召回分 {float(score):.2f}</span>"
        emotion_html = ""
        if metadata.get("has_emotion"):
            emotion_html = (
                f"<span>V {float(metadata.get('valence', 0.0)):.2f}</span>"
                f"<span>A {float(metadata.get('arousal', 0.0)):.2f}</span>"
            )
        cards.append(
            f"""
            <article class="card">
              <div class="meta">
                <span>{html.escape(TYPE_LABEL.get(metadata.get("type"), metadata.get("type", "-")))}</span>
                <span>{html.escape(metadata.get("date", "-"))}</span>
                <span>重要度 {float(metadata.get("importance", 0.0)):.2f}</span>
                <span>置信度 {float(metadata.get("confidence", 0.0)):.2f}</span>
                {score_html}
                {emotion_html}
              </div>
              <p>{html.escape(item.get("document", ""))}</p>
              <footer>{html.escape(item.get("id", ""))} · {html.escape(metadata.get("source", "-"))}</footer>
            </article>
            """
        )

    content = "\n".join(cards) or "<p class='empty'>暂无记忆。</p>"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f3ee; color: #23211f; }}
    main {{ max-width: 1080px; margin: 0 auto; padding: 32px 20px 48px; }}
    h1 {{ margin: 0 0 8px; font-size: 30px; }}
    .sub {{ margin: 0 0 24px; color: #706a62; }}
    .grid {{ display: grid; gap: 12px; }}
    .card {{ background: #fffdf8; border: 1px solid #ded7cd; border-radius: 8px; padding: 16px 18px; box-shadow: 0 1px 2px rgba(30, 24, 18, .05); }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }}
    .meta span {{ background: #ece6dc; border-radius: 999px; padding: 3px 8px; font-size: 12px; color: #5f554a; }}
    p {{ margin: 0; line-height: 1.72; font-size: 16px; }}
    footer {{ margin-top: 12px; color: #8c8378; font-size: 12px; }}
    .empty {{ color: #706a62; }}
  </style>
</head>
<body>
  <main>
    <h1>{html.escape(title)}</h1>
    <p class="sub">collection: memory · count: {collection.count()}</p>
    <section class="grid">{content}</section>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="查看和调试云雀长期记忆库。")
    parser.add_argument("--query", help="按查询语句召回记忆。")
    parser.add_argument("--k", type=int, default=10, help="显示或召回数量。")
    parser.add_argument("--user-id", help="只查看指定用户的记忆。")
    parser.add_argument("--type", dest="memory_type", help="只查看指定类型的记忆。")
    parser.add_argument("--html", nargs="?", const=str(MEMORY_DIR / "memory_view.html"), help="导出HTML可视化文件。")
    parser.add_argument("--seed-demo", action="store_true", help="写入3条debug_user示例记忆。")
    parser.add_argument("--delete-id", help="删除指定id的记忆。")
    parser.add_argument("--apply-decay", action="store_true", help="执行重要度衰减并删除低于阈值的记忆。")
    parser.add_argument("--threshold", type=float, default=0.05, help="遗忘阈值，配合--apply-decay使用。")
    args = parser.parse_args()

    if args.seed_demo:
        ids = seed_demo_memories(user_id=args.user_id or "debug_user")
        print("已写入示例记忆：")
        for memory_id in ids:
            print(f"- {memory_id}")

    if args.delete_id:
        delete_memory(args.delete_id)
        print(f"已删除记忆：{args.delete_id}")

    if args.apply_decay:
        actions = apply_decay(threshold=args.threshold, dry_run=False)
        deleted = [item for item in actions if item["deleted"]]
        print(f"已执行衰减：处理{len(actions)}条，删除{len(deleted)}条。")

    if args.query:
        items = flatten_recall_results(
            recall(args.query, k=args.k, user_id=args.user_id, memory_type=args.memory_type)
        )
        title = f"记忆召回：{args.query}"
        show_score = True
    else:
        items = list_memories(limit=args.k, user_id=args.user_id, memory_type=args.memory_type)
        title = "长期记忆库"
        show_score = False

    print(f"ChromaDB collection: memory, count={collection.count()}")
    print_table(items, show_score=show_score)

    if args.html:
        output = Path(args.html)
        render_html(items, output, title)
        print(f"\nHTML已导出：{output}")


if __name__ == "__main__":
    main()
