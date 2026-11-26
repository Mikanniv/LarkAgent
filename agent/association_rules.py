from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
from typing import Any, Dict, List, Sequence


def mine_association_rules(
    chunks: Sequence[Dict[str, Any]],
    *,
    min_support: float = 0.03,
    min_confidence: float = 0.28,
    min_lift: float = 1.05,
    min_term_freq: int = 2,
) -> Dict[str, Any]:
    """
    基于 Apriori 频繁项集思想的关联规则挖掘（纯 Python 实现，零额外重依赖）。
    将每个知识切片的去重主题词集合视为一条事务（Transaction），
    挖掘频繁 1-项集与 2-项集，计算 Support / Confidence / Lift。
    """
    raw_txs: List[List[str]] = []
    for ch in chunks or []:
        topics = ch.get("topics") or []
        clean = list(dict.fromkeys(str(t).strip() for t in topics if str(t).strip() and len(str(t).strip()) >= 2))
        if clean:
            raw_txs.append(clean)

    if not raw_txs:
        return {
            "num_transactions": 0,
            "num_unique_items": 0,
            "rules": [],
            "term_freq": {},
        }

    term_df = Counter(t for tx in raw_txs for t in tx)
    eff_min_freq = min_term_freq if sum(1 for c in term_df.values() if c >= min_term_freq) >= 4 else 1
    valid_terms = {t for t, cnt in term_df.items() if cnt >= eff_min_freq}

    transactions = [[t for t in tx if t in valid_terms] for tx in raw_txs]
    transactions = [tx for tx in transactions if len(tx) >= 2]
    n_tx = len(transactions)
    if n_tx == 0:
        return {
            "num_transactions": 0,
            "num_unique_items": len(valid_terms),
            "rules": [],
            "term_freq": dict(term_df),
        }

    item_counts: Counter[str] = Counter()
    pair_counts: Counter[tuple[str, str]] = Counter()
    for tx in transactions:
        for item in tx:
            item_counts[item] += 1
        for a, b in combinations(sorted(tx), 2):
            pair_counts[(a, b)] += 1

    eff_min_support = min_support if n_tx >= 10 else max(1.0 / n_tx, 0.01)
    rules: List[Dict[str, Any]] = []
    for (a, b), ab_cnt in pair_counts.items():
        sup_ab = ab_cnt / n_tx
        if sup_ab < eff_min_support:
            continue
        sup_a = item_counts[a] / n_tx
        sup_b = item_counts[b] / n_tx
        if sup_a <= 0 or sup_b <= 0:
            continue
        # Direction A -> B
        conf_ab = sup_ab / sup_a
        lift_ab = conf_ab / sup_b
        if conf_ab >= min_confidence and lift_ab >= min_lift:
            rules.append({
                "antecedents": [a],
                "consequents": [b],
                "support": round(sup_ab, 4),
                "confidence": round(conf_ab, 4),
                "lift": round(lift_ab, 4),
                "co_count": ab_cnt,
            })
        # Direction B -> A
        conf_ba = sup_ab / sup_b
        lift_ba = conf_ba / sup_a
        if conf_ba >= min_confidence and lift_ba >= min_lift:
            rules.append({
                "antecedents": [b],
                "consequents": [a],
                "support": round(sup_ab, 4),
                "confidence": round(conf_ba, 4),
                "lift": round(lift_ba, 4),
                "co_count": ab_cnt,
            })

    rules.sort(key=lambda r: (r["lift"], r["confidence"], r["support"]), reverse=True)
    return {
        "num_transactions": n_tx,
        "num_unique_items": len(item_counts),
        "rules": rules,
        "term_freq": dict(item_counts),
    }


def expand_query_with_rules(
    query: str,
    rules: Sequence[Dict[str, Any]],
    *,
    max_expansions: int = 4,
) -> Dict[str, Any]:
    """用挖掘出的关联规则对用户提问做查询扩展（Query Expansion）。"""
    q_low = (query or "").strip().lower()
    if not q_low or not rules:
        return {"query_terms": [], "expanded_terms": [], "matched_rules": []}

    query_terms: List[str] = []
    expanded_scores: Dict[str, float] = {}
    matched_rules: List[Dict[str, Any]] = []
    seen_q: set[str] = set()

    for rule in rules:
        ants = [str(x).strip() for x in (rule.get("antecedents") or []) if str(x).strip()]
        cons = [str(x).strip() for x in (rule.get("consequents") or []) if str(x).strip()]
        if not ants or not cons:
            continue
        if all(a.lower() in q_low for a in ants):
            for a in ants:
                if a not in seen_q:
                    seen_q.add(a)
                    query_terms.append(a)
            score = float(rule.get("lift") or 1.0) * float(rule.get("confidence") or 0.5)
            added_any = False
            for c in cons:
                if c.lower() in q_low:
                    continue
                if score > expanded_scores.get(c, 0.0):
                    expanded_scores[c] = score
                added_any = True
            if added_any and len(matched_rules) < 6:
                matched_rules.append({
                    "antecedent": " + ".join(ants),
                    "consequent": " + ".join(cons),
                    "support": rule.get("support", 0.0),
                    "confidence": rule.get("confidence", 0.0),
                    "lift": rule.get("lift", 1.0),
                })

    ranked_exp = sorted(expanded_scores.items(), key=lambda kv: kv[1], reverse=True)
    expanded_terms = [t for t, _ in ranked_exp[:max_expansions]]
    return {
        "query_terms": query_terms,
        "expanded_terms": expanded_terms,
        "matched_rules": matched_rules,
    }


def build_knowledge_graph(
    chunks: Sequence[Dict[str, Any]],
    *,
    max_nodes: int = 34,
    max_edges: int = 64,
) -> Dict[str, Any]:
    """基于关联规则构建资料库无向知识图谱，并为每个节点挂接关联度最高的切片。"""
    mined = mine_association_rules(chunks)
    rules = mined.get("rules") or []
    term_freq: Dict[str, int] = mined.get("term_freq") or {}

    # 合并双向规则为无向边（不标注边关系，保留最高 lift / confidence / support）
    edge_map: Dict[tuple[str, str], Dict[str, Any]] = {}
    for r in rules:
        a = (r.get("antecedents") or [""])[0]
        b = (r.get("consequents") or [""])[0]
        if not a or not b or a == b:
            continue
        key = (a, b) if a < b else (b, a)
        prev = edge_map.get(key)
        if not prev or r["lift"] > prev["lift"]:
            edge_map[key] = {
                "source": key[0],
                "target": key[1],
                "support": r["support"],
                "confidence": r["confidence"],
                "lift": r["lift"],
                "co_count": r.get("co_count", 1),
            }

    all_edges = sorted(edge_map.values(), key=lambda e: (e["lift"], e["confidence"], e["support"]), reverse=True)
    selected_edges = all_edges[:max_edges]

    # 确定节点集合：优先包含边端点，按度与频次截断
    degree_counter: Counter[str] = Counter()
    for e in selected_edges:
        degree_counter[e["source"]] += 1
        degree_counter[e["target"]] += 1

    candidate_terms = list(degree_counter.keys())
    if not candidate_terms:
        candidate_terms = [t for t, _ in Counter(term_freq).most_common(max_nodes)]
    candidate_terms.sort(key=lambda t: (degree_counter.get(t, 0), term_freq.get(t, 0)), reverse=True)
    selected_terms = candidate_terms[:max_nodes]
    selected_set = set(selected_terms)

    final_edges = [e for e in selected_edges if e["source"] in selected_set and e["target"] in selected_set]

    # 为每个节点找出关联度最高的切片（优先标题命中 + 主题词命中 + 正文出现频次）
    term_chunks: Dict[str, List[tuple[float, Dict[str, Any]]]] = defaultdict(list)
    for ch in chunks or []:
        ch_topics = set(str(t).strip() for t in (ch.get("topics") or []))
        content = str(ch.get("content") or "")
        title = str(ch.get("section_title") or "")
        c_low = content.lower()
        t_low = title.lower()
        for term in selected_terms:
            in_topics = term in ch_topics
            cnt = c_low.count(term.lower())
            in_title = term.lower() in t_low
            if not in_topics and cnt == 0:
                continue
            score = (3.0 if in_topics else 0.0) + (2.5 if in_title else 0.0) + min(cnt, 6) * 0.6
            term_chunks[term].append((score, ch))

    nodes: List[Dict[str, Any]] = []
    for term in selected_terms:
        ranked = sorted(term_chunks.get(term, []), key=lambda x: x[0], reverse=True)
        top_chunks = []
        seen_ids: set[str] = set()
        for sc, ch in ranked:
            cid = str(ch.get("id") or "")
            if cid and cid in seen_ids:
                continue
            if cid:
                seen_ids.add(cid)
            raw_content = str(ch.get("content") or "")
            top_chunks.append({
                "chunk_id": cid,
                "file_id": str(ch.get("file_id") or ""),
                "doc_name": str(ch.get("file_name") or ""),
                "location": str(ch.get("location") or ""),
                "section_title": str(ch.get("section_title") or ""),
                "topics": list(ch.get("topics") or [])[:5],
                "snippet": raw_content[:120] + ("…" if len(raw_content) > 120 else ""),
                "content": raw_content,
                "score": round(sc, 2),
            })
            if len(top_chunks) >= 3:
                break
        nodes.append({
            "id": term,
            "label": term,
            "freq": int(term_freq.get(term, 1)),
            "degree": int(degree_counter.get(term, 0)),
            "top_chunks": top_chunks,
        })

    return {
        "nodes": nodes,
        "edges": final_edges,
        "stats": {
            "num_chunks": len(chunks or []),
            "num_transactions": mined.get("num_transactions", 0),
            "num_nodes": len(nodes),
            "num_edges": len(final_edges),
            "num_rules": len(rules),
        },
    }
