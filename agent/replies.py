import json
import re
from typing import Dict, List, Tuple

from agent.kimi import call_kimi_chat, kimi_ready
from core.config import KIMI_MODEL
from emotion.mapping import FineGrainedEmotion


RECENT_DIALOGUE_MESSAGES = 8
REPLY_MAX_TOKENS = 1000
MEMORY_DECISION_MAX_TOKENS = 500


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
        parts = [
            f"类型={metadata.get('type', 'unknown')}",
            f"来源={metadata.get('source', 'unknown')}",
        ]
        if metadata.get("importance") is not None:
            parts.append(f"重要度={float(metadata.get('importance', 0.0)):.2f}")
        if metadata.get("confidence") is not None:
            parts.append(f"置信度={float(metadata.get('confidence', 0.0)):.2f}")
        if item.get("score") is not None:
            parts.append(f"召回分={float(item.get('score', 0.0)):.2f}")
        lines.append(f"- [{'；'.join(parts)}] {document}")
    return "\n".join(lines) if lines else "暂无可用长期记忆。"


def build_agent_prompt(
    user_text: str,
    emotion: FineGrainedEmotion,
    raw_scores: Dict[str, float],
    history: List[Dict],
    memories: List[Dict] | None = None,
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
    recent_va = raw_scores.get("recent_va")
    proactive_reason = raw_scores.get("proactive_reason")
    context_summary = (
        f"状态参考：偏 {emotion.label}；valence {emotion.valence:.2f}；"
        f"arousal {emotion.arousal:.2f}。"
    )
    if proactive_reason:
        context_summary += f" 主动回应触发原因：{proactive_reason}。"
    if recent_va:
        context_summary += f" 最近3次VA：{recent_va}。"
    if proactive and recent_assistant_replies:
        context_summary += f" 最近云雀已说过：{'；'.join(recent_assistant_replies[-2:])}。"
    memory_context = f"相关长期记忆：\n{format_memory_context(memories or [])}"
    messages = [
        {"role": "system", "content": system},
        {"role": "system", "content": context_summary},
        {"role": "system", "content": memory_context},
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


def extract_json_object(text: str) -> Dict:
    if not text:
        return {}
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        cleaned = match.group(0)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def clamp_float(value: object, default: float = 0.7, lower: float = 0.0, upper: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(lower, min(upper, number))


def is_low_value_emotion_memory(text: str) -> bool:
    normalized = (text or "").strip()
    compact = re.sub(r"\s+", "", normalized)
    if not compact:
        return True

    emotion_cues = ["焦虑", "压力", "难过", "难受", "生气", "崩溃", "委屈", "低落", "烦", "不舒服"]
    if not any(cue in normalized for cue in emotion_cues):
        return False

    explicit_memory_cues = ["记住", "以后", "下次", "希望你以后", "你以后"]
    context_cues = [
        "因为",
        "由于",
        "答辩",
        "考试",
        "项目",
        "大创",
        "论文",
        "作业",
        "面试",
        "实习",
        "工作",
        "失眠",
        "睡不着",
        "朋友",
        "家人",
        "爸",
        "妈",
        "老师",
        "同学",
        "伴侣",
        "对象",
        "室友",
    ]
    persistence_cues = ["最近", "这几天", "连续", "总是", "经常", "一直", "反复", "每天", "长期", "每次", "越来越"]
    if any(cue in normalized for cue in explicit_memory_cues + context_cues + persistence_cues):
        return False

    return True


def valence_is_negative(valence: float) -> bool:
    return valence <= -0.2


def compact_memory_phrase(text: str, limit: int = 90) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    text = re.sub(r"^(我|本人)", "用户", text)
    text = re.sub(r"^(今天|刚刚|现在)", r"用户\1", text)
    return text[:limit]


def fallback_memory_decision(user_text: str, emotion: FineGrainedEmotion) -> Dict:
    normalized = (user_text or "").strip()
    compact = re.sub(r"\s+", "", normalized)
    if len(compact) < 8:
        return {"should_write": False, "reason": "输入过短"}

    preference_cues = ["希望你", "以后你", "你以后", "我喜欢", "我不喜欢", "别一上来", "不要立刻", "先安慰", "先听我"]
    relationship_cues = ["朋友", "家人", "爸", "妈", "老师", "同学", "伴侣", "对象", "室友"]
    event_cues = ["答辩", "考试", "项目", "大创", "失眠", "睡不着", "论文", "作业", "面试", "实习", "工作"]
    emotion_cues = ["焦虑", "压力", "难过", "难受", "生气", "崩溃", "委屈", "低落", "不舒服"]

    if any(cue in normalized for cue in preference_cues):
        return {
            "should_write": True,
            "type": "preference",
            "source": "conversation",
            "document": f"用户对云雀的陪伴方式有明确偏好：{compact_memory_phrase(normalized)}",
            "confidence": 0.82,
            "reason": "用户明确表达了回复偏好",
        }
    if any(cue in normalized for cue in relationship_cues):
        return {
            "should_write": True,
            "type": "relationship",
            "source": "conversation",
            "document": f"用户的关系上下文中有值得后续参考的线索：{compact_memory_phrase(normalized)}",
            "confidence": 0.72,
            "reason": "用户提到关系上下文",
        }
    if any(cue in normalized for cue in event_cues) or (
        emotion.arousal >= 0.65
        and valence_is_negative(emotion.valence)
        and any(cue in normalized for cue in emotion_cues)
        and not is_low_value_emotion_memory(normalized)
    ):
        return {
            "should_write": True,
            "type": "event",
            "source": "conversation",
            "document": f"用户近期有值得后续跟进的状态或事件：{compact_memory_phrase(normalized)}",
            "confidence": 0.68,
            "reason": "输入包含可用于后续陪伴的事件或情绪线索",
        }
    if any(cue in normalized for cue in emotion_cues):
        return {"should_write": False, "reason": "仅为一次性情绪表达，不写入长期记忆"}
    return {"should_write": False, "reason": "未发现稳定偏好或重要事件"}


def decide_memory_update(
    user_text: str,
    assistant_reply: str,
    emotion: FineGrainedEmotion,
    raw_scores: Dict[str, float],
    memories: List[Dict],
    history: List[Dict],
    use_llm: bool = True,
) -> Tuple[Dict, str]:
    if not user_text.strip():
        return {"should_write": False, "reason": "无用户文本输入"}, "none"

    if not use_llm or not kimi_ready():
        return fallback_memory_decision(user_text, emotion), "heuristic"

    memory_block = format_memory_context(memories)
    recent_dialogue = "\n".join(
        f"{'用户' if item.get('role') == 'user' else '云雀'}：{item.get('content', '').strip()}"
        for item in history[-RECENT_DIALOGUE_MESSAGES:]
        if item.get("content")
    ) or "暂无近期对话。"
    system = (
        "你是云雀长期记忆库的写入决策器。"
        "你只判断当前轮次是否值得写入长期记忆，并只输出JSON。"
        "稳定偏好、重要关系、重复模式、用户对陪伴方式的明确反馈应写入。"
        "如果当前轮次包含对理解用户很有帮助的具体事实、阶段性进展、重要约定、关系变化或后续需要跟进的事情，也可以写入。"
        "普通闲聊、一次性寒暄、只有情绪但没有原因或背景的表达、低置信度推测不要写入。"
        "例如“我今天有点焦虑，想让你陪我聊聊”只代表当前状态，除非出现具体原因、反复模式或明确要求记住，否则不要写入。"
        "写入的document必须是自然的第三人称长期记忆句，不要照抄用户原话，"
        "不要写“用户说/用户提到/用户修改了AI记”这类记录动作。"
    )
    user = (
        f"当前用户输入：{user_text}\n\n"
        f"云雀回复：{assistant_reply}\n\n"
        f"近期对话：\n{recent_dialogue}\n\n"
        f"已召回长期记忆：\n{memory_block}\n\n"
        f"当前情绪参考：label={emotion.label}, valence={emotion.valence:.2f}, arousal={emotion.arousal:.2f}\n"
        f"模型原始分数：{raw_scores}\n\n"
        "输出JSON格式："
        "{\"should_write\": true/false, \"type\": \"event|routine|preference|relationship|summary\", "
        "\"source\": \"conversation|inference\", \"document\": \"一条不超过80字、像长期记忆而不是聊天原话的自然语言记忆\", "
        "\"confidence\": 0到1, \"reason\": \"简短原因\"}"
    )
    content, error = call_kimi_chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=MEMORY_DECISION_MAX_TOKENS,
        temperature=0.1,
    )
    decision = extract_json_object(content)
    if not decision:
        fallback = fallback_memory_decision(user_text, emotion)
        fallback["llm_error"] = error or "invalid_json"
        return fallback, "heuristic"
    decision["should_write"] = bool(decision.get("should_write"))
    if decision.get("type") not in {"event", "routine", "preference", "relationship", "summary"}:
        decision["type"] = "event"
    if decision.get("source") not in {"conversation", "inference"}:
        decision["source"] = "conversation"
    decision["confidence"] = clamp_float(decision.get("confidence"), default=0.7)
    decision["document"] = str(decision.get("document") or "").strip()[:140]
    if decision["should_write"] and not decision["document"]:
        decision["should_write"] = False
        decision["reason"] = "缺少可写入内容"
    if decision["should_write"] and decision["type"] == "event" and is_low_value_emotion_memory(
        f"{user_text}\n{decision['document']}"
    ):
        decision["should_write"] = False
        decision["reason"] = "仅为一次性情绪表达，不写入长期记忆"
    return decision, "kimi"


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
    proactive: bool = False,
) -> Tuple[str, str, str]:
    scripted = scripted_agent_reply(user_text, emotion, proactive=proactive)
    if scripted:
        return scripted, "scripted", ""
    content, error = call_kimi_chat(
        build_agent_prompt(user_text, emotion, raw_scores, history, memories=memories, proactive=proactive),
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
