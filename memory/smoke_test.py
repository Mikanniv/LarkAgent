from datetime import datetime
from pathlib import Path
from pprint import pprint
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from memory.db import collection
    from memory.schema import add_memory, create_memory, recall
except ModuleNotFoundError as exc:
    if exc.name == "chromadb":
        print("缺少依赖：chromadb。请先在当前环境安装 `chromadb` 后再运行该测试脚本。")
        raise SystemExit(1)
    raise


def build_sample_memory():
    now = datetime.now().astimezone()
    return create_memory(
        document="用户提到最近在准备答辩，连续几天睡得少，担心自己表现不好，希望我先安慰情绪，不要立刻给建议。",
        date=now.date().isoformat(),
        timestamp=now.isoformat(timespec="seconds"),
        user="user",
        user_id="demo_user",
        type="preference",
        source="conversation",
        has_emotion=True,
        valence=-0.52,
        arousal=0.73,
        confidence=0.86,
        importance=0.91,
        text_available=True,
        audio_available=False,
        video_available=False,
    )


def print_recall_results(results):
    documents = (results.get("documents") or [[]])[0]
    metadatas = (results.get("metadatas") or [[]])[0]
    distances = (results.get("distances") or [[]])[0]
    print(f"召回 {len(documents)} 条记忆：")
    for index, document in enumerate(documents):
        print(f"\n[{index + 1}] {document}")
        if index < len(metadatas):
            pprint(metadatas[index])
        if index < len(distances):
            print(f"distance={distances[index]}")


def main():
    memory = build_sample_memory()
    print("准备写入示例记忆：")
    pprint(memory)
    add_memory(memory)

    query = "我最近答辩压力很大，希望你先安慰我"
    print(f"\n使用查询语句召回：{query}\n")
    results = recall(query, k=3)
    print_recall_results(results)

    print(f"\n当前collection条目数：{collection.count()}")


if __name__ == "__main__":
    main()
