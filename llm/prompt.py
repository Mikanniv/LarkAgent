from typing import Dict, List

def _format_memory_item(document: str, metadata: Dict) -> str:
    parts = []
    memory_type = metadata.get("type", "unknown")
    source = metadata.get("source", "unknown")
    importance = metadata.get("importance")
    confidence = metadata.get("confidence")
    parts.append(f"类型={memory_type}")
    parts.append(f"来源={source}")
    if importance is not None:
        parts.append(f"重要度={importance:.2f}")
    if confidence is not None:
        parts.append(f"置信度={confidence:.2f}")
    if metadata.get("has_emotion"):
        valence = metadata.get("valence")
        arousal = metadata.get("arousal")
        if valence is not None and arousal is not None:
            parts.append(f"情绪=({valence:.2f}, {arousal:.2f})")
    return f"- [{'；'.join(parts)}] {document}"


def format_memories(memories: List[Dict]) -> str:
    if not memories:
        return "暂无相关长期记忆。"
    return "\n".join(
        _format_memory_item(item["document"], item["metadata"])
        for item in memories
    )


def build_reply_prompt(user_input: str, memories: List[Dict], emotion: Dict[str, float], recent_dialogue: List[Dict] | None = None) -> List[Dict[str, str]]:
    recent_dialogue = recent_dialogue or []
    memory_block = format_memories(memories)
    dialogue_block = "\n".join(
        f"{'用户' if item.get('role') == 'user' else '云雀'}：{item.get('content', '').strip()}"
        for item in recent_dialogue[-6:]
        if item.get("content")
    ) or "暂无近期对话。"
    valence = float(emotion.get("valence", 0.0))
    arousal = float(emotion.get("arousal", 0.0))
    system = (
        "你叫云雀，是一个自然、温柔、真诚的中文陪伴对象。\n"
        "你会参考长期记忆来理解用户，但不要机械复述记忆，不要像检索系统一样逐条列出。\n"
        "请结合当前情绪状态和近期对话，用1到3句自然中文回复用户。\n"
        "不要暴露内部字段、模型、数据库、metadata、valence/arousal等系统实现细节。"
    )
    user = (
        f"当前用户输入：{user_input}\n\n"
        f"相关长期记忆：\n{memory_block}\n\n"
        f"当前情绪状态：valence={valence:.2f}, arousal={arousal:.2f}\n\n"
        f"最近对话：\n{dialogue_block}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_ai_diary_prompt(conversations: List[Dict], memories: List[Dict] | None = None, emotion: Dict[str, float] | None = None) -> List[Dict[str, str]]:
    memories = memories or []
    emotion = emotion or {}
    dialogue_block = "\n".join(
        f"{'用户' if item.get('role') == 'user' else '云雀'}：{item.get('content', '').strip()}"
        for item in conversations
        if item.get("content")
    ) or "今天还没有足够的对话。"
    memory_block = format_memories(memories)
    valence = float(emotion.get("valence", 0.0))
    arousal = float(emotion.get("arousal", 0.0))
    system = (
        "你是长期陪伴系统中的AI记整理助手。\n"
        "请把当天的用户状态、对话重点和陪伴方式整理成简洁自然的中文Markdown。\n"
    )
    user = (
        f"今日对话：\n{dialogue_block}\n\n"
        f"相关长期记忆：\n{memory_block}\n\n"
        f"今日情绪参考：valence={valence:.2f}, arousal={arousal:.2f}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]