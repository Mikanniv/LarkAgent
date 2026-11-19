from __future__ import annotations

import json
from typing import Any, Dict, List

from agent.agent import call_chat_completion, chat_api_ready


def format_academic_context(profile: Dict | None) -> str:
    """Format academic profile into a compact, natural context string for the chat agent."""
    if not profile or not isinstance(profile, dict):
        return "用户尚未设置学业或成长档案。"

    stage = str(profile.get("stage") or "high_school").strip()
    grade = str(profile.get("grade") or "").strip()
    sub_category = str(profile.get("sub_category") or "").strip()
    target_school = str(profile.get("target_school") or "").strip()
    target_goal = str(profile.get("target_goal") or "").strip()
    current_score_or_gpa = str(profile.get("current_score_or_gpa") or "").strip()
    rank_info = str(profile.get("rank_info") or "").strip()
    current_school = str(profile.get("current_school") or "").strip()
    province = str(profile.get("province") or "").strip()
    extra = profile.get("extra_profile") or {}

    parts: List[str] = []
    if stage == "high_school":
        parts.append(f"学业阶段：高中（{grade or '在读'}）")
        if province:
            parts.append(f"省份：{province}")
        if sub_category:
            parts.append(f"选科：{sub_category}")
        if current_score_or_gpa:
            parts.append(f"近期模考成绩：{current_score_or_gpa}")
        if rank_info:
            parts.append(f"位次：{rank_info}")
        if target_school:
            parts.append(f"目标院校：{target_school}")
        if target_goal:
            parts.append(f"目标追求：{target_goal}")
        weak_subjects = extra.get("weak_subjects")
        if weak_subjects:
            parts.append(f"主要薄弱点：{weak_subjects}")
    elif stage == "undergraduate":
        parts.append(f"学业阶段：本科（{grade or '在读'}）")
        if current_school:
            parts.append(f"就读院校：{current_school}")
        if sub_category:
            parts.append(f"专业：{sub_category}")
        if current_score_or_gpa:
            parts.append(f"当前绩点/GPA：{current_score_or_gpa}")
        if rank_info:
            parts.append(f"专业排名：{rank_info}")
        if target_school:
            parts.append(f"目标院校：{target_school}")
        if target_goal:
            parts.append(f"长远目标：{target_goal}")
        research = extra.get("research")
        if research:
            parts.append(f"科研情况：{research}")
        competitions = extra.get("competitions")
        if competitions:
            parts.append(f"学科竞赛：{competitions}")
        english = extra.get("english")
        if english:
            parts.append(f"外语成绩：{english}")
    else:
        parts.append(f"成长阶段：{stage}")
        if sub_category:
            parts.append(f"方向：{sub_category}")
        if target_goal:
            parts.append(f"目标：{target_goal}")
        if current_score_or_gpa:
            parts.append(f"现状：{current_score_or_gpa}")

    return "；".join(parts) if parts else "用户尚未设置学业或成长档案。"


def generate_academic_advice(profile: Dict, score_history: List[Dict] | None = None) -> str:
    """Generate professional, personalized academic and growth planning advice."""
    if not chat_api_ready():
        return "大模型 API 尚未配置，无法生成个性化学业建议。"

    stage = str(profile.get("stage") or "high_school").strip()
    context_desc = format_academic_context(profile)

    scores_desc_list: List[str] = []
    for item in (score_history or [])[:5]:
        title = item.get("title", "测验")
        date = item.get("exam_date", "")
        score = item.get("total_score", "")
        rank = item.get("rank_num", "")
        total = item.get("rank_total", "")
        rank_str = f"（排名 {rank}/{total}）" if rank else ""
        details = item.get("details", {})
        details_str = (
            f"，明细：{json.dumps(details, ensure_ascii=False)}" if details else ""
        )
        scores_desc_list.append(f"- {date} {title}：得分 {score}{rank_str}{details_str}")
    scores_text = "\n".join(scores_desc_list) if scores_desc_list else "暂无历史成绩记录"

    system_prompt = (
        "你叫云雀，不仅是用户温柔贴心的陪伴伙伴，也是一位兼具深度洞察与科学规划能力的学业成长导师。"
        "你需要根据用户的学业画像、目标院校/发展愿景以及近期成绩记录，为用户输出一份兼具【理性分析】与【温暖鼓励】的个性化成长规划建议。"
        "语气要像一位既懂升学/保研规则、又由衷关心用户成长的学长/学姐：专业、务实、不讲空话套话、不施加焦虑。"
        "输出格式建议包含："
        "1. 【现状定位与差距诊断】：客观评估当前实力与目标的距离，肯定优势，点出核心发力点。"
        "2. 【关键突破策略】：针对高中（选科赋分、考点提分、大题攻坚策略）或大学（保研排名推免算法、夏令营入营竞争力、科研论文加分、高规格学科竞赛、四六级门槛等）给出精准破局方案。"
        "3. 【阶段行动建议】：拆解为近 1~3 个月和本学期可立即落地执行的 2~3 个具体动作。"
        "4. 【云雀的陪伴寄语】：一句温暖真诚的打气，提醒劳逸结合，无论顺境逆境云雀都在身边。"
        "排版请使用清晰的 Markdown 格式。"
    )

    user_prompt = (
        f"用户学业档案信息：\n{context_desc}\n\n"
        f"历史成绩与考试流水：\n{scores_text}\n\n"
        "请结合以上信息，为用户量身定制一份具有指导意义的学业与成长规划建议："
    )

    content, error = call_chat_completion(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=1500,
        temperature=0.6,
    )

    if content:
        return content
    return f"生成学业建议失败：{error or '模型返回内容为空'}"


def is_requesting_plan(text: str) -> bool:
    """Detect if user asks the agent to generate an academic/growth plan."""
    t = text.strip().lower()
    keywords = [
        "生成规划", "学业规划", "成长规划", "制定规划", "规划一下",
        "给我规划", "生成建议", "学习规划", "保研规划", "高考规划",
        "升学规划", "考研规划", "我的规划", "制定方案", "定制规划",
    ]
    return any(k in t for k in keywords)


COMMON_SUBJECTS = [
    "高等数学", "线性代数", "概率论与数理统计", "概率论", "微积分", "离散数学",
    "大学物理", "普通物理", "数据结构", "计算机网络", "操作系统", "计算机组成原理",
    "四级", "六级", "雅思", "托福", "考研英语", "考研数学", "考研政治",
    "数学", "语文", "英语", "物理", "化学", "生物", "历史", "地理", "政治",
    "高数", "线代", "计网", "计组", "算法", "程序设计", "Python", "C++", "Java",
]


def detect_study_intent(text: str) -> Dict[str, str] | None:
    """
    Detect whether user wants to study or review a subject/topic.
    Returns dict with subject, title, prompt_seed or None.
    """
    t = text.strip()
    if len(t) < 2:
        return None

    # Check for direct matches like "我想复习数学", "我们来学高数", "帮我复习力学"
    action_keywords = ["复习", "学习", "辅导", "学一下", "学一学", "讲讲", "讲一下", "做题", "刷题", "备考", "练习"]
    has_action = any(act in t for act in action_keywords)

    found_subject = ""
    for subj in COMMON_SUBJECTS:
        if subj.lower() in t.lower():
            found_subject = subj
            break

    # If no predefined subject but clear pattern like "我想复习[XXX]" or "学习[XXX]"
    if not found_subject and has_action:
        import re
        match = re.search(r'(?:复习|学习|学一下|辅导|讲讲|备考)\s*([a-zA-Z0-9\u4e00-\u9fa5]{2,10})', t)
        if match:
            candidate = match.group(1).strip()
            banned = ["一下", "什么", "这个", "东西", "怎么", "如何", "知识", "内容"]
            if candidate not in banned:
                found_subject = candidate

    if found_subject:
        return {
            "subject": found_subject,
            "title": f"{found_subject}专项学习",
            "prompt_seed": f"请针对【{found_subject}】进行专业梳理、重点辅导和答疑解惑。",
        }

    return None

