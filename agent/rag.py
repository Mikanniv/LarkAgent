from __future__ import annotations

import math
import os
import re
from collections import Counter
from typing import Any, Dict, List, Set, Tuple

try:
    import jieba  # type: ignore
    import jieba.analyse  # type: ignore

    _HAS_JIEBA = True
except Exception:
    jieba = None
    _HAS_JIEBA = False

try:
    import numpy as np  # type: ignore
    from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
    from sklearn.metrics.pairwise import cosine_similarity  # type: ignore

    _HAS_SKLEARN = True
except Exception:
    np = None
    TfidfVectorizer = None
    cosine_similarity = None
    _HAS_SKLEARN = False

DEFAULT_RELEVANCE_THRESHOLD = 0.22

STOPWORDS: Set[str] = {
    "的", "了", "和", "是", "在", "有", "与", "及", "或", "对", "为", "以", "由", "从", "到",
    "把", "被", "将", "让", "给", "中", "上", "下", "内", "外", "时", "后", "前", "之", "其",
    "这", "那", "这个", "那个", "这些", "那些", "一个", "一种", "一些", "可以", "能够", "需要",
    "必须", "应该", "可能", "通过", "采用", "使用", "进行", "完成", "实现", "具有", "包括",
    "包含", "主要", "常见", "基本", "相关", "不同", "相同", "如果", "因为", "所以", "但是",
    "而且", "或者", "以及", "例如", "比如", "其中", "同时", "如下", "以上", "以下", "说明",
    "内容", "部分", "方面", "方式", "方法", "过程", "情况", "问题", "结果", "作用", "特点",
    "什么", "怎么", "如何", "为什么", "哪些", "哪里", "多少", "是否", "请问", "帮我", "一下",
    "讲解", "解释", "介绍", "详细", "结合", "根据", "资料", "文档", "课件", "教材", "切片",
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "have", "has",
    "not", "but", "can", "will", "into", "about", "what", "how", "why", "when", "where", "which",
    "http", "https", "www", "com", "org", "pdf", "pptx", "docx",
}


def chunk_text(text: str, chunk_size: int = 650, overlap: int = 120) -> List[str]:
    """按段落与语义边界切分长文档，返回非空切片列表。"""
    cleaned = re.sub(r"\r\n?", "\n", (text or "")).strip()
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", cleaned) if p.strip()]
    chunks: List[str] = []
    current = ""

    for para in paragraphs:
        if len(para) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            sentences = [s.strip() for s in re.split(r"(?<=[。！？.!?\n])\s*", para) if s.strip()]
            buf = ""
            for sent in sentences:
                if len(sent) > chunk_size:
                    if buf:
                        chunks.append(buf)
                        buf = ""
                    step = max(1, chunk_size - overlap)
                    for start in range(0, len(sent), step):
                        piece = sent[start : start + chunk_size].strip()
                        if piece:
                            chunks.append(piece)
                elif len(buf) + len(sent) + 1 <= chunk_size:
                    buf = f"{buf} {sent}".strip() if buf else sent
                else:
                    if buf:
                        chunks.append(buf)
                    buf = sent
            if buf:
                chunks.append(buf)
            continue

        if len(current) + len(para) + 2 <= chunk_size:
            current = f"{current}\n\n{para}".strip() if current else para
        else:
            if current:
                chunks.append(current)
                tail = current[-overlap:].strip() if overlap > 0 and len(current) > overlap else ""
                current = f"{tail}\n\n{para}".strip() if tail and len(tail) + len(para) + 2 <= chunk_size else para
            else:
                current = para

    if current:
        chunks.append(current)
    return chunks


def tokenize_for_rag(text: str) -> List[str]:
    """中英混合分词：优先使用 jieba 词级分词，同时保留英文术语与中文 2-gram 兜底。"""
    s = (text or "").strip()
    if not s:
        return []
    tokens: List[str] = []
    if _HAS_JIEBA and jieba is not None:
        for tok in jieba.lcut(s):
            t = tok.strip().lower()
            if not t or t in STOPWORDS:
                continue
            if re.fullmatch(r"[\W_]+", t):
                continue
            if len(t) == 1 and not re.match(r"[\u4e00-\u9fff]", t):
                continue
            if re.fullmatch(r"\d+", t):
                continue
            tokens.append(t)
    else:
        low = s.lower()
        for t in re.findall(r"[a-z0-9_#+.-]{2,}", low):
            if t not in STOPWORDS and not t.isdigit():
                tokens.append(t)
        for zh_seg in re.findall(r"[\u4e00-\u9fff]+", low):
            n = len(zh_seg)
            if n == 1 and zh_seg not in STOPWORDS:
                tokens.append(zh_seg)
            else:
                for i in range(n - 1):
                    bg = zh_seg[i : i + 2]
                    if bg not in STOPWORDS:
                        tokens.append(bg)
    return tokens


def extract_chunk_topics(text: str, section_title: str = "", top_k: int = 5) -> List[str]:
    """为单个切片提取高辨识度主题词元数据（3-5 个核心关键词）。"""
    combined = f"{section_title}\n{section_title}\n{text or ''}".strip()
    if not combined:
        return []

    topics: List[str] = []
    seen_lower: Set[str] = set()

    def _add(term: str) -> None:
        t = re.sub(r"^[\W_]+|[\W_]+$", "", (term or "").strip())
        if not t or len(t) < 2 or len(t) > 24:
            return
        low = t.lower()
        if low in STOPWORDS or low in seen_lower or re.fullmatch(r"\d+(?:\.\d+)*", low):
            return
        seen_lower.add(low)
        topics.append(t)

    # 1. 优先提取显眼的英文缩写 / 技术术语（如 PCB, LRU, TCP, SQL, Transformer）
    tech_terms = re.findall(r"\b(?:[A-Z]{2,}[A-Za-z0-9_-]*|[A-Za-z]+[0-9]+[A-Za-z0-9_-]*)\b", combined)
    for term, _ in Counter(tech_terms).most_common(4):
        _add(term)
        if len(topics) >= top_k:
            return topics[:top_k]

    # 2. 使用 jieba TF-IDF 关键词提取
    if _HAS_JIEBA and jieba is not None:
        try:
            tags = jieba.analyse.extract_tags(
                combined,
                topK=top_k * 3,
                allowPOS=("n", "nz", "vn", "eng", "nr", "ns", "nt", "l"),
            )
            for tag in tags:
                _add(tag)
                if len(topics) >= top_k:
                    return topics[:top_k]
            # 若词性过滤后不足，放宽词性补充
            if len(topics) < top_k:
                for tag in jieba.analyse.extract_tags(combined, topK=top_k * 2):
                    _add(tag)
                    if len(topics) >= top_k:
                        return topics[:top_k]
        except Exception:
            pass

    # 3. 词频兜底
    toks = [t for t in tokenize_for_rag(combined) if len(t) >= 2]
    for tok, _ in Counter(toks).most_common(top_k * 2):
        _add(tok)
        if len(topics) >= top_k:
            break

    return topics[:top_k]


def build_file_chunks(
    file_name: str,
    file_type: str,
    segments: List[Dict[str, Any]],
    chunk_size: int = 750,
    overlap: int = 120,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """根据文件类型分段构建带主题词元数据的切片列表，同时汇总文件级主题词。"""
    stem = os.path.splitext(file_name or "资料")[0]
    chunks: List[Dict[str, Any]] = []
    topic_counter: Counter[str] = Counter()

    # 不同文件类型微调切片粒度
    effective_size = chunk_size
    if file_type in {"pdf", "pptx"}:
        effective_size = 950  # 课件页尽量保持整页完整
    elif file_type == "code":
        effective_size = 900
    elif file_type in {"xlsx", "csv"}:
        effective_size = 1100

    chunk_index = 0
    for seg in segments or []:
        raw_content = str(seg.get("content") or "").strip()
        if not raw_content:
            continue
        base_loc = str(seg.get("location") or f"片段 {chunk_index + 1}").strip()
        page_num = int(seg.get("page_num") or (chunk_index + 1))
        sec_title = str(seg.get("section_title") or stem).strip()[:70]

        pieces = chunk_text(raw_content, chunk_size=effective_size, overlap=overlap)
        total_pieces = len(pieces)
        for sub_idx, piece in enumerate(pieces, 1):
            loc = base_loc if total_pieces == 1 else f"{base_loc} ({sub_idx}/{total_pieces})"
            topics = extract_chunk_topics(piece, section_title=sec_title, top_k=5)
            for t in topics:
                topic_counter[t] += 1
            chunks.append(
                {
                    "chunk_index": chunk_index,
                    "location": loc,
                    "page_num": page_num,
                    "section_title": sec_title,
                    "topics": topics,
                    "content": piece,
                }
            )
            chunk_index += 1

    file_topics = [t for t, _ in topic_counter.most_common(8)]
    return chunks, file_topics


def _chunk_search_doc(ch: Dict[str, Any]) -> str:
    title = str(ch.get("section_title") or "")
    topics = " ".join(ch.get("topics") or [])
    fname = str(ch.get("file_name") or "")
    content = str(ch.get("content") or "")
    # 标题与主题词加权重复一次以提升精准匹配度
    return f"{fname} {title} {title} {topics} {topics} {content}"


def _format_source_item(ch: Dict[str, Any], cite_id: str, score: float, pinned: bool = False) -> Dict[str, Any]:
    content = str(ch.get("content") or "")
    snippet = re.sub(r"\s+", " ", content).strip()[:180]
    return {
        "cite_id": cite_id,
        "chunk_id": str(ch.get("id") or ""),
        "file_id": str(ch.get("file_id") or ""),
        "doc_name": str(ch.get("file_name") or "未命名资料"),
        "location": str(ch.get("location") or f"片段 {int(ch.get('chunk_index', 0)) + 1}"),
        "page_num": int(ch.get("page_num") or (int(ch.get("chunk_index", 0)) + 1)),
        "section_title": str(ch.get("section_title") or ""),
        "topics": list(ch.get("topics") or [])[:6],
        "score": round(float(score), 4),
        "pinned": bool(pinned),
        "snippet": snippet,
        "content": content,
    }


def retrieve_chunks_with_scores(
    query: str,
    chunks: List[Dict[str, Any]],
    *,
    top_k: int = 5,
    threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
    pinned_chunk_id: str = "",
) -> Dict[str, Any]:
    """混合检索（TF-IDF 余弦 + BM25 + 词覆盖率），输出校准后的 [0,1] 相关度与拒答判定。"""
    if not chunks:
        return {
            "abstained": True,
            "max_score": 0.0,
            "threshold": threshold,
            "pinned_target": False,
            "results": [],
        }

    q_tokens = tokenize_for_rag(query)
    q_unique = set(q_tokens)

    N = len(chunks)
    doc_tokens_list: List[List[str]] = []
    doc_strings: List[str] = []
    df: Counter[str] = Counter()
    total_len = 0

    for ch in chunks:
        toks = tokenize_for_rag(_chunk_search_doc(ch))
        doc_tokens_list.append(toks)
        doc_strings.append(" ".join(toks) if toks else str(ch.get("content") or ""))
        total_len += len(toks)
        for t in set(toks):
            df[t] += 1

    # 1. TF-IDF Cosine Similarity (sklearn)
    tfidf_sims = [0.0] * N
    if _HAS_SKLEARN and TfidfVectorizer is not None and cosine_similarity is not None and q_tokens:
        try:
            q_str = " ".join(q_tokens)
            vec = TfidfVectorizer(tokenizer=str.split, preprocessor=None, token_pattern=None, lowercase=False)
            mat = vec.fit_transform(doc_strings + [q_str])
            sims = cosine_similarity(mat[-1], mat[:-1])[0]
            tfidf_sims = [float(max(0.0, min(1.0, s))) for s in sims]
        except Exception:
            tfidf_sims = [0.0] * N

    # 2. BM25 (饱和归一化到 [0, 1]) + 词覆盖率 + 关联规则查询扩展加权
    from agent.association_rules import expand_query_with_rules, mine_association_rules

    mined_rules = mine_association_rules(chunks)
    rule_info = expand_query_with_rules(query, mined_rules.get("rules") or [], max_expansions=4)
    expanded_terms_low = [t.lower() for t in (rule_info.get("expanded_terms") or [])]

    avgdl = max(1.0, total_len / max(1, N))
    k1 = 1.5
    b = 0.75
    scored_pairs: List[Tuple[float, int]] = []

    for idx, doc_tokens in enumerate(doc_tokens_list):
        tf = Counter(doc_tokens)
        dl = max(1, len(doc_tokens))
        bm25_raw = 0.0
        matched_q = 0
        for qt in q_unique:
            if qt not in tf:
                continue
            matched_q += 1
            freq = tf[qt]
            idf = math.log(1.0 + (N - df[qt] + 0.5) / (df[qt] + 0.5))
            denom = freq + k1 * (1.0 - b + b * dl / avgdl)
            bm25_raw += idf * (freq * (k1 + 1.0)) / max(1e-6, denom)

        # 主题词精确命中加分
        ch_topics_low = {str(t).lower() for t in (chunks[idx].get("topics") or [])}
        topic_hit = 0.0
        if q_unique and ch_topics_low:
            hits = sum(1 for t in ch_topics_low if t in query.lower() or t in q_unique)
            if hits > 0:
                topic_hit = min(0.18, 0.09 * hits)

        # 关联规则扩展词命中加分（提高跨概念召回）
        assoc_hit = 0.0
        if expanded_terms_low:
            ch_text_low = str(chunks[idx].get("content") or "").lower()
            exp_hits = sum(1 for et in expanded_terms_low if et in ch_topics_low or et in ch_text_low)
            if exp_hits > 0:
                assoc_hit = min(0.12, 0.045 * exp_hits)

        bm25_norm = bm25_raw / (bm25_raw + 3.2) if bm25_raw > 0 else 0.0
        coverage = (matched_q / max(1, len(q_unique))) if q_unique else 0.0
        hybrid = min(1.0, 0.48 * tfidf_sims[idx] + 0.34 * bm25_norm + 0.18 * coverage + topic_hit + assoc_hit)
        scored_pairs.append((hybrid, idx))

    scored_pairs.sort(key=lambda pair: pair[0], reverse=True)

    # 支持从「继续学习」点击指定切片追问：置顶该切片为 [S1]
    pinned_idx = -1
    if pinned_chunk_id:
        for i, ch in enumerate(chunks):
            if str(ch.get("id") or "") == str(pinned_chunk_id):
                pinned_idx = i
                break

    selected: List[Tuple[float, int, bool]] = []
    used_indices: Set[int] = set()
    used_texts: Set[str] = set()
    if pinned_idx >= 0:
        p_score = max(0.88, dict((i, s) for s, i in scored_pairs).get(pinned_idx, 0.88))
        selected.append((p_score, pinned_idx, True))
        used_indices.add(pinned_idx)
        used_texts.add(re.sub(r"\s+", "", str(chunks[pinned_idx].get("content") or "")))

    for score, idx in scored_pairs:
        if idx in used_indices:
            continue
        norm_txt = re.sub(r"\s+", "", str(chunks[idx].get("content") or ""))
        if norm_txt and norm_txt in used_texts:
            continue
        selected.append((score, idx, False))
        used_indices.add(idx)
        if norm_txt:
            used_texts.add(norm_txt)
        if len(selected) >= top_k:
            break

    results = [
        _format_source_item(chunks[idx], f"S{rank}", score, pinned=is_pinned)
        for rank, (score, idx, is_pinned) in enumerate(selected, 1)
    ]

    max_score = float(results[0]["score"]) if results else 0.0
    abstained = (pinned_idx < 0) and (max_score < threshold)

    return {
        "abstained": abstained,
        "max_score": round(max_score, 4),
        "threshold": round(float(threshold), 4),
        "pinned_target": pinned_idx >= 0,
        "rule_info": rule_info,
        "results": results,
    }


def retrieve_relevant_chunks(
    query: str,
    chunks: List[Dict[str, Any]],
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """兼容旧接口：返回 top_k 原始切片字典列表。"""
    out = retrieve_chunks_with_scores(query, chunks, top_k=top_k, threshold=0.0)
    id_map = {str(ch.get("id") or ""): ch for ch in chunks}
    return [id_map[r["chunk_id"]] for r in out["results"] if r["chunk_id"] in id_map]


def recommend_next_chunks(
    seed_chunk_ids: List[str],
    chunks: List[Dict[str, Any]],
    *,
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """基于内容相似度 + 主题词关联 + 文档顺序邻近 + MMR 多样性的「继续学习」推荐器。"""
    if not chunks or len(chunks) <= 1 or not seed_chunk_ids:
        return []

    id_to_idx = {str(ch.get("id") or ""): i for i, ch in enumerate(chunks)}
    seed_indices = [id_to_idx[cid] for cid in seed_chunk_ids if cid in id_to_idx]
    if not seed_indices:
        return []

    seed_set = set(seed_indices)
    seed_texts = {re.sub(r"\s+", "", str(chunks[i].get("content") or "")) for i in seed_indices}
    primary_seed = chunks[seed_indices[0]]
    seed_topics: Set[str] = set()
    for i in seed_indices:
        seed_topics.update(str(t) for t in (chunks[i].get("topics") or []))

    # 1. TF-IDF 相似度矩阵（用于候选相关性与 MMR 去重）
    N = len(chunks)
    doc_strings = [" ".join(tokenize_for_rag(_chunk_search_doc(ch))) or str(ch.get("content") or "") for ch in chunks]
    sim_matrix = None
    if _HAS_SKLEARN and TfidfVectorizer is not None and cosine_similarity is not None and np is not None:
        try:
            vec = TfidfVectorizer(tokenizer=str.split, preprocessor=None, token_pattern=None, lowercase=False)
            mat = vec.fit_transform(doc_strings)
            sim_matrix = cosine_similarity(mat)
        except Exception:
            sim_matrix = None

    # 2. 计算每个候选切片的综合推荐分与可读理由
    cand_scores: Dict[int, float] = {}
    cand_reasons: Dict[int, str] = {}

    for idx, ch in enumerate(chunks):
        if idx in seed_set:
            continue
        if re.sub(r"\s+", "", str(ch.get("content") or "")) in seed_texts:
            continue
        content_sim = 0.0
        if sim_matrix is not None:
            content_sim = float(max(sim_matrix[idx, s] for s in seed_indices))

        ch_topics = [str(t) for t in (ch.get("topics") or [])]
        ch_topic_set = set(ch_topics)
        shared_topics = sorted(seed_topics & ch_topic_set)
        topic_jaccard = (
            len(shared_topics) / max(1, len(seed_topics | ch_topic_set))
            if (seed_topics and ch_topic_set)
            else 0.0
        )

        # 文档内顺序邻近奖励
        seq_bonus = 0.0
        seq_label = ""
        if ch.get("file_id") == primary_seed.get("file_id"):
            diff = int(ch.get("chunk_index", 0)) - int(primary_seed.get("chunk_index", 0))
            if diff == 1:
                seq_bonus = 0.28
                seq_label = "进阶延伸（下一节）"
            elif diff == 2:
                seq_bonus = 0.14
                seq_label = "后续延伸"
            elif diff == -1:
                seq_bonus = 0.16
                seq_label = "前置基础（上一节）"

        total = 0.52 * content_sim + 0.30 * topic_jaccard + seq_bonus
        # 给有新主题词的候选轻微探索加成
        novel_topics = [t for t in ch_topics if t not in seed_topics]
        if novel_topics:
            total += 0.04

        if seq_label:
            reason = seq_label
        elif shared_topics:
            reason = f"关联主题：{shared_topics[0]}"
        elif ch.get("file_id") != primary_seed.get("file_id"):
            reason = "跨资料延伸"
        else:
            reason = "内容延伸"

        cand_scores[idx] = total
        cand_reasons[idx] = reason

    if not cand_scores:
        return []

    # 3. 轻量 MMR 选择，保证推荐的 top_k 切片覆盖不同子主题
    selected: List[int] = []
    remaining = set(cand_scores.keys())
    lambda_mmr = 0.72

    while remaining and len(selected) < top_k:
        best_idx = -1
        best_val = -1e9
        for idx in remaining:
            rel = cand_scores[idx]
            if not selected or sim_matrix is None:
                val = rel
            else:
                redundancy = float(max(sim_matrix[idx, s] for s in selected))
                val = lambda_mmr * rel - (1.0 - lambda_mmr) * redundancy
            if val > best_val:
                best_val = val
                best_idx = idx
        if best_idx < 0:
            break
        selected.append(best_idx)
        remaining.remove(best_idx)

    recs: List[Dict[str, Any]] = []
    for idx in selected:
        ch = chunks[idx]
        content = str(ch.get("content") or "")
        recs.append(
            {
                "chunk_id": str(ch.get("id") or ""),
                "file_id": str(ch.get("file_id") or ""),
                "doc_name": str(ch.get("file_name") or "未命名资料"),
                "location": str(ch.get("location") or f"片段 {int(ch.get('chunk_index', 0)) + 1}"),
                "page_num": int(ch.get("page_num") or (int(ch.get("chunk_index", 0)) + 1)),
                "section_title": str(ch.get("section_title") or ""),
                "topics": list(ch.get("topics") or [])[:6],
                "reason": cand_reasons.get(idx, "推荐学习"),
                "score": round(float(cand_scores.get(idx, 0.0)), 4),
                "snippet": re.sub(r"\s+", " ", content).strip()[:140],
                "content": content,
            }
        )
    return recs


def verify_citations(answer: str, valid_cite_ids: Set[str]) -> Dict[str, Any]:
    """事后核验回答中的 [Si] 引用标记，清除幻觉编号并识别模型主动拒答。"""
    found = re.findall(r"\[(S\d+)\]", answer or "")
    invalid = sorted({c for c in found if c not in valid_cite_ids})
    valid_used = sorted({c for c in found if c in valid_cite_ids})

    cleaned = (answer or "").strip()
    for bad in invalid:
        cleaned = cleaned.replace(f"[{bad}]", "")

    abstain_phrases = ["无法可靠回答", "无法回答", "资料中未", "没有找到", "未检索到", "我不知道", "不知道"]
    first_line = cleaned.splitlines()[0] if cleaned else ""
    starts_with_abstain = any(p in first_line for p in abstain_phrases)
    model_abstained = starts_with_abstain or (not valid_used and any(p in cleaned for p in abstain_phrases))

    warning = None
    if not model_abstained and valid_cite_ids and not valid_used:
        warning = "提示：模型回复未显式标注 [Si] 编号，已附上下方检索来源供核对。"

    return {
        "answer": cleaned.strip(),
        "valid_citations": valid_used,
        "invalid_citations_removed": invalid,
        "model_abstained": model_abstained,
        "citation_warning": warning,
    }
