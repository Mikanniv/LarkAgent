import re
from typing import Dict, List, Tuple

from agent.agent import call_chat_completion, chat_api_ready
from agent.attachments import build_multimodal_user_content
from agent.academic import format_academic_context
from core.config import API_AUDIO_INPUT, API_IMAGE_INPUT, MODEL
from emotion.mapping import FineGrainedEmotion


RECENT_DIALOGUE_MESSAGES = 8
REPLY_MAX_TOKENS = 1000


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
    attachments: List[Dict] | None = None,
    academic_profile: Dict | None = None,
) -> List[Dict]:
    recent_assistant_replies = [
        (item.get("content") or "").strip()
        for item in history[-RECENT_DIALOGUE_MESSAGES:]
        if item.get("role") == "assistant" and (item.get("content") or "").strip()
    ]
    system = (
        "你叫云雀，是一个自然、温柔、真诚的中文陪伴与成长搭档。"
        "直接回复用户，不要写分析过程，只输出自然中文。"
        "不要暴露模型、参数、传感器、valence/arousal 等系统实现细节。"
        "你可以参考长期记忆与学业背景理解用户偏好、当前困惑与长远目标，但不要机械复述记忆或强行说教。"
        "如果长期记忆和当前输入冲突，以当前输入为准。"
        "避免书面腔，要像真人学伴聊天。"
        "当用户需要可视化演示、互动小工具、图表、动画或可交互练习时，可输出一个完整自包含的 ```html-widget ... ``` 单文件代码块（内联 CSS 与 JS，不依赖外部本地文件），前端会自动渲染为可交互预览卡片。"
    )
    if proactive:
        system += (
            "这次是你主动发起回应，要自然、克制，不要显得像系统提醒。"
            "不要使用“今天有好好吃饭吗”“记得吃饭/喝水/早点睡”这类打卡式关心，除非用户刚刚明确提到饮食、喝水或睡眠。"
            "不要重复最近已经说过的句式。优先结合最近对话、长期记忆、学业阶段或当前情绪状态，轻轻承接一句。"
        )
    proactive_reason = raw_scores.get("proactive_reason")
    context_summary = f"用户的情感得分为{float(raw_scores.get('fusion', 0.0)):.3f}。"
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
    if academic_profile:
        messages.append({"role": "system", "content": f"用户学业与成长背景：\n{format_academic_context(academic_profile)}"})
    for item in history[-RECENT_DIALOGUE_MESSAGES:]:
        role = "assistant" if item.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": item.get("content", "")})
    proactive_user_prompt = (
        "用户暂时没有继续输入。请基于最近对话、长期记忆和当前状态，主动说一句不打扰的陪伴话。"
        "不要问吃饭、喝水、睡觉这类泛化生活打卡问题。"
    )
    final_text = user_text or proactive_user_prompt
    user_content = build_multimodal_user_content(
        final_text,
        attachments,
        allow_image=API_IMAGE_INPUT,
        allow_audio=API_AUDIO_INPUT,
    )
    messages.append({"role": "user", "content": user_content})
    return messages


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


def generate_agent_reply(
    user_text: str,
    emotion: FineGrainedEmotion,
    raw_scores: Dict[str, float],
    history: List[Dict],
    memories: List[Dict] | None = None,
    strategies: List[Dict] | None = None,
    proactive: bool = False,
    attachments: List[Dict] | None = None,
    academic_profile: Dict | None = None,
) -> Tuple[str, str, str]:
    content, error = call_chat_completion(
        build_agent_prompt(
            user_text,
            emotion,
            raw_scores,
            history,
            memories=memories,
            strategies=strategies,
            proactive=proactive,
            attachments=attachments,
            academic_profile=academic_profile,
        ),
        max_tokens=REPLY_MAX_TOKENS,
        temperature=0.7,
    )
    if content and not reply_looks_bad(content, history=history, proactive=proactive):
        return content, "api", ""
    detail = error or "模型返回了空内容或无效回复"
    raise RuntimeError(f"模型调用失败：{detail}")


def agent_payload(reply: str, source: str, error: str) -> Dict[str, object]:
    return {
        "reply": reply,
        "source": source,
        "model": MODEL,
        "api_ready": chat_api_ready(),
        "error": error,
    }
