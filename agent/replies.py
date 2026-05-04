import re
from typing import Dict, List, Tuple

from agent.ollama import call_ollama_chat, ollama_ready
from core.config import OLLAMA_MODEL
from emotion.mapping import FineGrainedEmotion


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


def build_agent_prompt(
    user_text: str,
    emotion: FineGrainedEmotion,
    raw_scores: Dict[str, float],
    history: List[Dict],
    proactive: bool = False,
) -> List[Dict[str, str]]:
    system = (
        "/no_think\n"
        "你叫云雀，是一个自然、温柔、真诚的中文陪伴对象。"
        "直接回复用户，不要写分析过程。只输出 1 到 3 句自然中文。"
        "不要暴露模型、参数、传感器、valence/arousal 等系统实现细节。"
        "如果用户表达难过、焦虑、委屈，先接住情绪，再给一个很轻的陪伴式建议。"
        "避免书面腔，要像真人聊天。"
    )
    if proactive:
        system += "这次是你主动发起回应，要自然、克制，不要显得像系统提醒。"
    recent_va = raw_scores.get("recent_va")
    proactive_reason = raw_scores.get("proactive_reason")
    context_summary = (
        f"状态参考：偏 {emotion.label}；愉悦 {emotion.positivity:.2f}；"
        f"唤醒 {emotion.arousal:.2f}；压力 {emotion.stress:.2f}。"
    )
    if proactive_reason:
        context_summary += f" 主动回应触发原因：{proactive_reason}。"
    if recent_va:
        context_summary += f" 最近3次VA：{recent_va}。"
    messages = [{"role": "system", "content": system}, {"role": "system", "content": context_summary}]
    for item in history[-4:]:
        role = "assistant" if item.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": item.get("content", "")})
    messages.append({"role": "user", "content": user_text or "请主动发起一句简短关心。"})
    return messages


def reply_looks_bad(text: str) -> bool:
    if not text:
        return True
    banned_fragments = [
        "作为AI",
        "作为助手",
        "AI assistant",
        "assistant",
        "联系客服",
        "官方渠道",
        "感谢您的理解",
        "如果您有任何问题",
        "首先，用户",
        "关键点：",
        "结构：",
    ]
    return any(fragment in text for fragment in banned_fragments)


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
        if emotion.label in {"紧张", "愤怒"} or emotion.stress >= 0.55:
            return choose_variant(
                [
                    "我先来陪你待一会儿。你现在看起来有点绷着，不用急着回答我，先慢慢呼一口气也可以。",
                    "我注意到你这会儿像是在硬撑着往前走。我们可以先把节奏放慢一点。",
                    "先不用马上组织语言，我在这儿。要不要先试着放松一下肩膀？",
                ],
                seed,
            )
        return choose_variant(
            [
                "我在这儿。你如果有想说的，随时直接跟我说就行。",
                "先陪你待一下。你可以继续忙手头的事，想聊的时候我在。",
                "我过来看看你。现在要不要先说一句此刻最真实的感受？",
            ],
            seed,
        )

    if emotion.label in {"紧张", "愤怒"} or emotion.stress >= 0.55:
        return choose_variant(
            [
                "我能感觉到你现在有些绷着，这种状态并不轻松。先别急着把所有问题一次解决，我们可以一起把眼前最小的一件事拆出来。",
                "听起来你像是被很多事情同时拉扯着。我们先不求一下子想明白全部，只抓住最迫近的一件事。",
                "你现在像是在高压里继续往前顶，这很消耗人。先给自己留一个很小的缓冲，再决定下一步。",
            ],
            seed,
        )
    if emotion.label in {"低落"}:
        return choose_variant(
            [
                "你现在的感受值得被认真对待，不需要急着把自己拉回正常。可以先说说此刻最卡住你的那件事。",
                "这种时候先别要求自己立刻振作也没关系。我们先把最不舒服的那一点单独拎出来看看。",
                "我在认真听你说。现在不用急着给自己下结论，先讲出最真实的困扰就已经很重要了。",
            ],
            seed,
        )
    return choose_variant(
        [
            "此刻看起来你还在整理自己的感受，这很正常。你可以挑一个最想先说的点，我们慢慢往下聊。",
            "现在不用急着把答案找全。先从你最想展开的那一部分说起，我们一起把线头理出来。",
            "我在。你可以先说一小句，不用一开始就讲得很完整。",
        ],
        seed,
    )


def generate_agent_reply(
    user_text: str,
    emotion: FineGrainedEmotion,
    raw_scores: Dict[str, float],
    history: List[Dict],
    proactive: bool = False,
) -> Tuple[str, str, str]:
    scripted = scripted_agent_reply(user_text, emotion, proactive=proactive)
    if scripted:
        return scripted, "scripted", ""
    content, error = call_ollama_chat(
        build_agent_prompt(user_text, emotion, raw_scores, history, proactive=proactive),
        max_tokens=220,
        temperature=0.7,
    )
    if content and not reply_looks_bad(content):
        return content, "ollama", ""
    if error == "ollama_missing":
        return fallback_agent_reply(user_text, emotion, proactive=proactive), "fallback", error
    return fallback_agent_reply(user_text, emotion, proactive=proactive), "fallback", error or "bad_or_empty_response"


def agent_payload(reply: str, source: str, error: str) -> Dict[str, object]:
    return {
        "reply": reply,
        "source": source,
        "model": OLLAMA_MODEL,
        "api_ready": ollama_ready(),
        "error": error,
    }
