from typing import Dict, List

from agent.ollama import call_ollama_chat
from diary.store import diary_paths, get_diary_payload, write_markdown


def build_ai_diary_markdown(date_key: str, snapshot: Dict, user_markdown: str) -> str:
    emotion = snapshot["emotion"]
    scores = snapshot["scores"]
    recent_history = snapshot.get("history", [])[-8:]
    user_focus = []
    agent_support = []
    for item in recent_history:
        content = (item.get("content") or "").strip()
        if content:
            if item.get("role") == "user":
                user_focus.append(content)
            else:
                agent_support.append(content)
    user_focus_text = "；".join(user_focus[-3:]) if user_focus else "今天还没有足够的用户表达。"
    agent_support_text = "；".join(agent_support[-2:]) if agent_support else "今天的陪伴回应还在逐步形成。"
    user_excerpt = (user_markdown or "").strip() or "今天用户还没有在日记页写下内容。"
    return "\n".join(
        [
            f"# AI记 {date_key}",
            "",
            "## 今日概览",
            f"今天整体更接近“{emotion['label']}”的状态，愉悦度 {emotion['positivity']:.2f}，"
            f"唤醒度 {emotion['arousal']:.2f}，压力值 {emotion['stress']:.2f}。",
            "",
            "## 用户状态",
            f"- 当前主基调：{emotion['label']}",
            f"- 自我感受线索：{user_focus_text}",
            f"- 掌控感：{emotion['dominance']:.2f}",
            f"- 融合分数：{scores['fusion']:.2f}",
            "",
            "## 日记线索",
            user_excerpt,
            "",
            "## 陪伴观察",
            f"今天更有效的陪伴方式偏向：{agent_support_text}",
        ]
    )


def build_ai_diary_prompt(date_key: str, snapshot: Dict, user_markdown: str) -> List[Dict[str, str]]:
    emotion = snapshot["emotion"]
    scores = snapshot["scores"]
    history = snapshot.get("history", [])[-8:]
    history_text = "\n".join(
        [
            f"{'用户' if item.get('role') == 'user' else 'AI'}：{(item.get('content') or '').strip()}"
            for item in history
            if (item.get("content") or "").strip()
        ]
    ) or "今天还没有足够的对话。"
    diary_text = (user_markdown or "").strip() or "今天用户还没有手动写日记。"
    system = (
        "你是长期陪伴系统中的记忆整理助手。"
        "请把当天的用户日记、情绪状态和对话内容总结成一份中文 Markdown AI记。"
        "不要逐条抄写对话，不要流水账，不要写传感器或检测过程。"
        "输出包含以下二级标题：## 今日概览、## 用户状态、## 日记线索、## 陪伴观察。"
    )
    user = (
        f"日期：{date_key}\n"
        f"主状态：{emotion['label']}，愉悦度={emotion['positivity']:.2f}，唤醒度={emotion['arousal']:.2f}，"
        f"掌控感={emotion['dominance']:.2f}，压力值={emotion['stress']:.2f}，融合分数={scores['fusion']:.2f}\n\n"
        f"用户日记：\n{diary_text}\n\n"
        f"最近对话：\n{history_text}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def diary_looks_bad(text: str) -> bool:
    if not text:
        return True
    banned_fragments = ["作为AI", "客服", "官方渠道"]
    if any(fragment in text for fragment in banned_fragments):
        return True
    required_sections = ["## 今日概览", "## 用户状态", "## 日记线索", "## 陪伴观察"]
    return any(section not in text for section in required_sections)


def generate_ai_diary_markdown(date_key: str, snapshot: Dict, user_markdown: str) -> str:
    content, _ = call_ollama_chat(
        build_ai_diary_prompt(date_key, snapshot, user_markdown),
        max_tokens=500,
        temperature=0.5,
    )
    if content and not diary_looks_bad(content):
        return content
    return build_ai_diary_markdown(date_key, snapshot, user_markdown)


def refresh_ai_diary_from_snapshot(date_key: str, snapshot: Dict) -> bool:
    payload = get_diary_payload(date_key)
    ai_markdown = generate_ai_diary_markdown(date_key, snapshot, payload["user_markdown"])
    write_markdown(diary_paths(date_key)["ai"], ai_markdown)
    return True
