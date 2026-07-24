import re
from typing import Dict, List, Tuple

from agent.kimi import call_kimi_chat, kimi_ready
from core.config import KIMI_MODEL
from emotion.mapping import FineGrainedEmotion


RECENT_DIALOGUE_MESSAGES = 8
REPLY_MAX_TOKENS = 1000


def choose_variant(options: List[str], seed_text: str) -> str:
    if not options:
        return ""
    index = sum(ord(ch) for ch in seed_text) % len(options)
    return options[index]


def is_greeting(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text.lower())
    return normalized in {"你好", "你好呀", "嗨", "哈喽", "hello", "hi", "在吗", "早上好", "晚上好"}


def is_identity_question(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text.lower())
    patterns = ["你是谁", "你是什么", "你是什么模型", "你是啥", "你叫什么", "你叫什么名字"]
    return any(pattern in normalized for pattern in patterns)


def format_memory_context(memories: List[Dict]) -> str:
    if not memories:
        return "暂无可用长期记忆。"
    lines = []
    for item in memories[:3]:
        metadata = item.get("metadata") or {}
        document = (item.get("document") or "").strip()
        if not document:
            continue
        layer = item.get("layer") or metadata.get("layer")
        topics = item.get("topics") or []
        parts = []
        if layer:
            parts.append(f"层级={layer}")
        elif metadata.get("type"):
            parts.append(f"类型={metadata.get('type')}")
        if topics:
            parts.append(f"主题={','.join(topics)}")
        if item.get("importance") is not None or metadata.get("importance") is not None:
            parts.append(f"重要度={float(item.get('importance', metadata.get('importance', 0.0))):.2f}")
        if item.get("confidence") is not None or metadata.get("confidence") is not None:
            parts.append(f"置信度={float(item.get('confidence', metadata.get('confidence', 0.0))):.2f}")
        if item.get("score") is not None:
            parts.append(f"召回分={float(item.get('score', 0.0)):.2f}")
        lines.append(f"- [{'；'.join(parts)}] {document}")
    return "\n".join(lines) if lines else "暂无可用长期记忆。"


def format_strategy_context(strategies: List[Dict]) -> str:
    if not strategies:
        return "暂无可用互动策略。"
    lines = []
    for item in strategies[:2]:
        scene = str(item.get("scene") or "当前情境").strip()
        description = str(item.get("document") or item.get("description") or "").strip()
        if description:
            lines.append(f"- 场景={scene}：{description}")
    return "\n".join(lines) if lines else "暂无可用互动策略。"


def build_agent_prompt(
    user_text: str,
    emotion: FineGrainedEmotion,
    raw_scores: Dict[str, float],
    history: List[Dict],
    memories: List[Dict] | None = None,
    strategies: List[Dict] | None = None,
    proactive: bool = False,
) -> List[Dict[str, str]]:
    recent_assistant_replies = [
        (item.get("content") or "").strip()
        for item in history[-RECENT_DIALOGUE_MESSAGES:]
        if item.get("role") == "assistant" and (item.get("content") or "").strip()
    ]
    system = (
        "你叫云雀，是一个自然、温柔、真诚的中文陪伴对象。"
        "直接回复用户，不要写分析过程，只输出自然中文。"
        "不要暴露模型、参数、传感器、valence/arousal 等系统实现细节。"
        "你可以参考长期记忆理解用户偏好和近期背景，但不要机械复述记忆。"
        "如果长期记忆和当前输入冲突，以当前输入为准。"
        "避免书面腔，要像真人聊天。"
    )
    if proactive:
        system += (
            "这次是你主动发起回应，要自然、克制，不要显得像系统提醒。"
            "不要使用“今天有好好吃饭吗”“记得吃饭/喝水/早点睡”这类打卡式关心，除非用户刚刚明确提到饮食、喝水或睡眠。"
            "不要重复最近已经说过的句式。优先结合最近对话、长期记忆或当前情绪状态，轻轻承接一句。"
        )
    proactive_reason = raw_scores.get("proactive_reason")
    context_summary = (
        f"文本情绪模型参考：text score={float(raw_scores.get('text', 0.0)):.3f}；"
        f"fusion score={float(raw_scores.get('fusion', 0.0)):.3f}。"
        "这些分数只用于调整回应语气，不代表确定的情绪标签。"
    )
    if proactive_reason:
        context_summary += f" 主动回应触发原因：{proactive_reason}。"
    if proactive and recent_assistant_replies:
        context_summary += f" 最近云雀已说过：{'；'.join(recent_assistant_replies[-2:])}。"
    memory_context = f"相关长期记忆：\n{format_memory_context(memories or [])}"
    strategy_context = f"可能适用的互动策略：\n{format_strategy_context(strategies or [])}"
    messages = [
        {"role": "system", "content": system},
        {"role": "system", "content": context_summary},
        {"role": "system", "content": memory_context},
        {"role": "system", "content": strategy_context},
    ]
    for item in history[-RECENT_DIALOGUE_MESSAGES:]:
        role = "assistant" if item.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": item.get("content", "")})
    proactive_user_prompt = (
        "用户暂时没有继续输入。请基于最近对话、长期记忆和当前状态，主动说一句不打扰的陪伴话。"
        "不要问吃饭、喝水、睡觉这类泛化生活打卡问题。"
    )
    messages.append({"role": "user", "content": user_text or proactive_user_prompt})
    return messages


def valence_is_negative(valence: float) -> bool:
    return valence <= -0.2


def reply_looks_bad(text: str, history: List[Dict] | None = None, proactive: bool = False) -> bool:
    if not text:
        return True
    banned_fragments = [
        "首先，用户",
        "关键点：",
        "分析过程",
        "思考过程",
        "推理过程",
        "作为AI",
        "作为助手",
        "用户当前",
        "最终回复：",
        "回复：",
    ]
    if any(fragment in text for fragment in banned_fragments):
        return True
    if proactive:
        recent_user_text = " ".join(
            (item.get("content") or "")
            for item in (history or [])[-RECENT_DIALOGUE_MESSAGES:]
            if item.get("role") == "user"
        )
        generic_care_cues = ["好好吃饭", "吃饭了吗", "记得吃饭", "多喝水", "早点睡", "早睡"]
        related_context_cues = ["吃饭", "没吃", "饿", "胃", "喝水", "口渴", "睡", "失眠", "困"]
        if any(cue in text for cue in generic_care_cues) and not any(cue in recent_user_text for cue in related_context_cues):
            return True
    return False


def scripted_agent_reply(user_text: str, emotion: FineGrainedEmotion, proactive: bool = False) -> str:
    seed = f"{user_text}|{emotion.label}|{emotion.valence:.2f}|{emotion.arousal:.2f}|{proactive}"
    if proactive:
        return ""
    if is_greeting(user_text):
        return choose_variant(
            [
                "你好呀，我在。今天想从哪件事开始聊？",
                "你好，我在这儿。你现在最想说的是什么？",
                "你好呀，见到你了。要不要先跟我说说你这会儿的状态？",
            ],
            seed,
        )
    if is_identity_question(user_text):
        return choose_variant(
            [
                "你可以把我当成云雀，一个陪你说话、陪你整理心情的伙伴。",
                "我是云雀，会陪你聊聊现在的感受，也会帮你慢慢把思绪理顺。",
                "我是云雀，主要做的事就是陪你说话，在你需要的时候接住你的情绪。",
            ],
            seed,
        )
    return ""


def fallback_agent_reply(user_text: str, emotion: FineGrainedEmotion, proactive: bool = False) -> str:
    seed = f"{user_text}|{emotion.label}|{emotion.valence:.2f}|{emotion.arousal:.2f}|{proactive}"
    if proactive:
        return choose_variant(
            [
                "我在这儿陪你待一会儿。你不用马上回应，先慢慢呼一口气。",
                "我过来看看你。现在如果有一点想说的，我会认真听。",
            ],
            seed,
        )

    if emotion.label in {"紧张", "愤怒"} or (valence_is_negative(emotion.valence) and emotion.arousal >= 0.55):
        return choose_variant(
            [
                "我听出来你现在有点绷着。先别急着解决全部，我们可以先把最让你难受的那一点说出来。",
                "这会儿确实不轻松。我在，你可以慢慢说，不用一下子讲完整。",
            ],
            seed,
        )
    if emotion.label in {"低落"}:
        return choose_variant(
            [
                "你现在的感受值得被认真对待。先不用急着振作，我陪你把最卡住的地方说清楚。",
                "我在认真听。你可以先说最真实的一句，不用给自己下结论。",
            ],
            seed,
        )
    return choose_variant(
        [
            "我在。你可以先说一小句，不用一开始就讲得很完整。",
            "我们慢慢聊。你可以从现在最想说的那个点开始。",
        ],
        seed,
    )


def generate_agent_reply(
    user_text: str,
    emotion: FineGrainedEmotion,
    raw_scores: Dict[str, float],
    history: List[Dict],
    memories: List[Dict] | None = None,
    strategies: List[Dict] | None = None,
    proactive: bool = False,
) -> Tuple[str, str, str]:
    scripted = scripted_agent_reply(user_text, emotion, proactive=proactive)
    if scripted:
        return scripted, "scripted", ""
    content, error = call_kimi_chat(
        build_agent_prompt(
            user_text,
            emotion,
            raw_scores,
            history,
            memories=memories,
            strategies=strategies,
            proactive=proactive,
        ),
        max_tokens=REPLY_MAX_TOKENS,
        temperature=0.7,
    )
    if content and not reply_looks_bad(content, history=history, proactive=proactive):
        return content, "kimi", ""
    return fallback_agent_reply(user_text, emotion, proactive=proactive), "fallback", error or "bad_or_empty_response"


def agent_payload(reply: str, source: str, error: str) -> Dict[str, object]:
    return {
        "reply": reply,
        "source": source,
        "model": KIMI_MODEL,
        "api_ready": kimi_ready(),
        "error": error,
    }
