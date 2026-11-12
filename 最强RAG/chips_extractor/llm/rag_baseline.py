#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最强 RAG 基线：多查询扩展 + 父子分块 + BM25混合检索 + LLM Rerank。

Pipeline:
  离线:
    content.json
      → 父块（表格/段落，完整保留）
      → 子块（父块内的片段，用于检索）
      → embedding 子块 + 建 BM25 索引

  在线（每次查询）:
    query
      → LLM 生成 3 个查询变体
      → 每个变体做 (向量 + BM25) 混合检索，各取 top-10
      → RRF 融合去重，得到 ~20-30 个候选
      → LLM rerank 到 top-5
      → 取这 5 个的**父块**作为上下文
      → LLM 提取

用法:
    python -m chips_extractor.llm.rag_baseline_max
    python -m chips_extractor.llm.rag_baseline_max --rebuild
"""

import argparse
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _FILE.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from chips_extractor.llm.client import LLMClient               # noqa: E402
from chips_extractor.llm.config import LLMConfig               # noqa: E402
from chips_extractor.llm.extract_parameters import (            # noqa: E402
    OUT_DIR,
    load_content,
    load_content_list_map,
    _resolve_table_body,
    parse_json_loose,
    EXTRACT_SYSTEM_PROMPT,
)


# ─────────────────────────── 固定配置 ───────────────────────────

CHIP = "stm32f100vc"

TEST_QUERIES = [
    "Supply current",
    "Operating voltage VDD",
    "CPU frequency",
    "Operating temperature range",
    "Power dissipation",
    "ADC resolution",
    "DAC resolution",
    "Flash size",
    "Maximum clock frequency",
    "Package",
]

# 分块参数
PARENT_MAX = 2000            # 父块最大字符（表格不切）
CHILD_SIZE = 300             # 子块目标大小
CHILD_OVERLAP = 50           # 子块重叠

# 检索参数
N_QUERY_VARIANTS = 3         # query 扩展数量
TOP_K_PER_QUERY = 10         # 每个变体取 top-k
TOP_K_RERANK_INPUT = 25      # rerank 输入上限
TOP_K_FINAL = 5              # 最终保留

# Embedding
EMBED_MODEL = "text-embedding-v2"
EMBED_BATCH = 20


# ─────────────────────────── 分块 ───────────────────────────

def _make_parents_for_text(text: str, node_id: str, title: str) -> List[Dict]:
    """把一段 text 切成父块。"""
    if not text:
        return []
    text = text.strip()
    if len(text) <= PARENT_MAX:
        return [{"node_id": node_id, "title": title, "type": "text",
                 "text": text, "caption": ""}]
    # 超长，按段落累积
    parents = []
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    buf = ""
    for para in paras:
        if len(buf) + len(para) + 2 > PARENT_MAX and buf:
            parents.append({"node_id": node_id, "title": title,
                            "type": "text", "text": buf, "caption": ""})
            buf = para
        else:
            buf = (buf + "\n\n" + para).strip() if buf else para
    if buf:
        parents.append({"node_id": node_id, "title": title,
                        "type": "text", "text": buf, "caption": ""})
    return parents


def _make_parents_for_table(caption: str, body: str,
                            node_id: str, title: str) -> List[Dict]:
    """表格作为**单一父块**（不切断），保证表格完整性。"""
    if not body:
        return []
    full = f"[{caption}]\n{body}" if caption else body
    return [{"node_id": node_id, "title": title, "type": "table",
             "text": full, "caption": caption}]


def _split_to_children(parent: Dict) -> List[Dict]:
    """把父块切成子块（用于检索）。每个子块带 parent_id。"""
    text = parent["text"]
    pid = parent["_pid"]
    children = []

    # 表格：按行切成子块（每 5 行一块）
    if parent["type"] == "table":
        lines = text.splitlines()
        header = lines[0] if lines else ""
        rows = lines[1:] if len(lines) > 1 else []
        step = 5
        for i in range(0, len(rows), step):
            group = rows[i:i + step]
            chunk_text = header + "\n" + "\n".join(group)
            children.append({
                "_parent": pid, "text": chunk_text,
                "node_id": parent["node_id"], "title": parent["title"],
                "type": "table",
            })
        if not children:
            children.append({"_parent": pid, "text": text,
                             "node_id": parent["node_id"],
                             "title": parent["title"], "type": "table"})
        return children

    # 文本：滑动窗口切
    if len(text) <= CHILD_SIZE:
        children.append({"_parent": pid, "text": text,
                         "node_id": parent["node_id"],
                         "title": parent["title"], "type": "text"})
        return children

    start = 0
    while start < len(text):
        end = min(start + CHILD_SIZE, len(text))
        children.append({
            "_parent": pid,
            "text": text[start:end],
            "node_id": parent["node_id"],
            "title": parent["title"],
            "type": "text",
        })
        if end == len(text):
            break
        start = end - CHILD_OVERLAP
    return children


def build_corpus(chip: str) -> Tuple[List[Dict], List[Dict]]:
    """构建父子块。返回 (parents, children)。"""
    content_data, _ = load_content(chip)
    cl_map = load_content_list_map(content_data)

    parents: List[Dict] = []
    children: List[Dict] = []

    def walk(nodes):
        for n in nodes:
            nid = n.get("id", "")
            title = n.get("title", "")
            c = n.get("content", {}) or {}

            text = (c.get("text") or "").strip()
            if text:
                parents.extend(_make_parents_for_text(text, nid, title))

            for t in c.get("tables") or []:
                body = _resolve_table_body(t, cl_map)
                if not body:
                    continue
                cap = t.get("caption") or ""
                parents.extend(_make_parents_for_table(cap, body, nid, title))

            walk(n.get("children", []))

    walk(content_data.get("sections", []))

    # 分配 pid，生成 children
    for i, p in enumerate(parents):
        p["_pid"] = i
        children.extend(_split_to_children(p))

    return parents, children


# ─────────────────────────── BM25 ───────────────────────────

def _tokenize(text: str) -> List[str]:
    """简单分词：提取英文单词和数字（含小数）。"""
    return re.findall(r'[a-zA-Z][a-zA-Z0-9_]*|\d+\.?\d*', text.lower())


class BM25:
    """经典 BM25 实现。"""

    def __init__(self, docs: List[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_tokens: List[List[str]] = [_tokenize(d) for d in docs]
        self.doc_len = np.array([len(t) for t in self.doc_tokens], dtype=np.float32)
        self.avgdl = float(self.doc_len.mean()) if len(self.doc_len) else 1.0

        # df: 每个词出现在多少个文档中
        df = Counter()
        for tokens in self.doc_tokens:
            for w in set(tokens):
                df[w] += 1
        self.N = len(docs)
        self.idf = {
            w: math.log(1 + (self.N - c + 0.5) / (c + 0.5))
            for w, c in df.items()
        }

        # tf: 每个文档的词频
        self.tfs: List[Counter] = [Counter(t) for t in self.doc_tokens]

    def search(self, query: str, k: int = 10) -> List[Tuple[int, float]]:
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []
        scores = np.zeros(self.N, dtype=np.float32)
        for w in q_tokens:
            if w not in self.idf:
                continue
            idf = self.idf[w]
            for i, tf in enumerate(self.tfs):
                if w not in tf:
                    continue
                f = tf[w]
                dl = self.doc_len[i]
                score = idf * (f * (self.k1 + 1)) / (
                    f + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                )
                scores[i] += score
        top_idx = np.argsort(-scores)[:k]
        return [(int(i), float(scores[i])) for i in top_idx if scores[i] > 0]


# ─────────────────────────── Embedding ───────────────────────────

def _embed_batch(texts: List[str], client) -> List[List[float]]:
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def embed_texts(texts: List[str], verbose: bool = True) -> np.ndarray:
    from openai import OpenAI
    cfg = LLMConfig()
    client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
    all_vecs: List[List[float]] = []
    total = len(texts)
    for i in range(0, total, EMBED_BATCH):
        batch = texts[i:i + EMBED_BATCH]
        if verbose:
            print(f"    embedding {i + len(batch)}/{total}...", flush=True)
        try:
            all_vecs.extend(_embed_batch(batch, client))
        except Exception as e:
            print(f"    ✗ embedding 失败: {e}")
            for _ in batch:
                all_vecs.append([0.0] * 1536)
    arr = np.array(all_vecs, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return arr / norms


# ─────────────────────────── 索引 ───────────────────────────

# 索引按家族分目录存放：output/llm_output/rag_index/<FAMILY>/<chip>_rag_max/
# 目的：与大模型相关的产物统一收纳在 llm_output 下，且按家族分门别类。
RAG_INDEX_ROOT = _PROJECT_ROOT / "output" / "llm_output" / "rag_index"

_FAMILY_RULES = [
    ("STM32", ("stm32",)),
    ("ESP", ("esp", "0a-esp")),
    ("GD32", ("gd32",)),
    ("ADI", ("ad", "adp", "adsp", "aduc", "adum", "adxl", "adf", "adl")),
]


def index_family(chip: str) -> str:
    """按芯片名归入索引家族目录（STM32 / ESP / GD32 / ADI / OTHER）。"""
    n = (chip or "").lower()
    for name, prefixes in _FAMILY_RULES:
        if any(n.startswith(p) for p in prefixes):
            return name
    return "OTHER"


def _index_dir(chip: str) -> Path:
    return RAG_INDEX_ROOT / index_family(chip) / f"{chip}_rag_max"


def build_or_load_index(
    chip: str, verbose: bool = True
) -> Dict[str, Any]:
    """构建或加载完整索引。返回 dict 包含所有组件。"""
    idx_dir = _index_dir(chip)
    cache = idx_dir / "index.json"
    vecs_path = idx_dir / "child_vecs.npy"

    if cache.exists() and vecs_path.exists():
        if verbose:
            print(f"[RAG-max] 加载已有索引: {idx_dir}")
        idx = json.loads(cache.read_text(encoding="utf-8"))
        vecs = np.load(vecs_path)
        bm25 = BM25([c["text"] for c in idx["children"]])
        if verbose:
            print(f"[RAG-max] {len(idx['parents'])} 父块, "
                  f"{len(idx['children'])} 子块")
        return {"parents": idx["parents"], "children": idx["children"],
                "child_vecs": vecs, "bm25": bm25}

    if verbose:
        print(f"[RAG-max] 首次运行，构建索引...")
    parents, children = build_corpus(chip)
    if verbose:
        print(f"[RAG-max] {len(parents)} 父块, {len(children)} 子块")

    t0 = time.time()
    child_texts = [c["text"] for c in children]
    vecs = embed_texts(child_texts, verbose=verbose)
    if verbose:
        print(f"[RAG-max] embedding 完成，耗时 {time.time() - t0:.1f}s")

    # BM25
    bm25 = BM25(child_texts)

    idx_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"parents": parents, "children": children},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    np.save(vecs_path, vecs)
    if verbose:
        print(f"[RAG-max] 缓存: {idx_dir}")

    return {"parents": parents, "children": children,
            "child_vecs": vecs, "bm25": bm25}


# ─────────────────────────── Query 扩展 ───────────────────────────

QUERY_EXPAND_PROMPT = """你是芯片数据手册检索专家。

用户查询: {query}

请生成 {n} 个**语义等价但表达不同**的查询变体，用于检索芯片数据手册中的相关参数。

每个变体应该：
1. 使用数据手册常见的英文术语或缩写（如 IDD、VDD、Typ.、RDS(on)）
2. 涵盖同义词和常见的表述差异
3. 保持原查询的核心意图

输出 JSON（仅 JSON，不要解释）:
{{"queries": ["变体1", "变体2", "变体3"]}}
"""


def expand_queries(query: str, llm: LLMClient,
                   n: int = N_QUERY_VARIANTS,
                   verbose: bool = True) -> Tuple[List[str], int]:
    """LLM 生成查询变体。返回 (变体列表, tokens)。"""
    prompt = QUERY_EXPAND_PROMPT.format(query=query, n=n)

    resp = llm.chat([
        {"role": "system", "content": "你是芯片数据手册检索专家，只输出 JSON。"},
        {"role": "user", "content": prompt},
    ])

    if not resp.success:
        if verbose:
            print(f"    [扩展] ✗ LLM 失败，只用原 query")
        return [query], 0

    try:
        data = parse_json_loose(resp.text)
        variants = data.get("queries", [])
        variants = [str(v).strip() for v in variants if str(v).strip()]
        # 原 query 加上
        all_queries = [query] + variants[:n]
        if verbose:
            print(f"    [扩展] 变体: {all_queries[1:]}")
        return all_queries, resp.total_tokens
    except Exception as e:
        if verbose:
            print(f"    [扩展] ✗ 解析失败 ({e})")
        return [query], resp.total_tokens


# ─────────────────────────── 混合检索 ───────────────────────────

def _vector_search(q_vec: np.ndarray, child_vecs: np.ndarray,
                   k: int) -> List[Tuple[int, float]]:
    scores = child_vecs @ q_vec
    top_idx = np.argsort(-scores)[:k]
    return [(int(i), float(scores[i])) for i in top_idx]


def hybrid_search_one(
    query: str,
    child_vecs: np.ndarray,
    bm25: BM25,
    k: int = TOP_K_PER_QUERY,
) -> Tuple[List[int], List[int]]:
    """单个 query 的混合检索。返回 (向量结果索引, BM25 结果索引)。"""
    q_vec = embed_texts([query], verbose=False)[0]
    vec_hits = [i for i, _ in _vector_search(q_vec, child_vecs, k)]
    bm_hits = [i for i, _ in bm25.search(query, k)]
    return vec_hits, bm_hits


def rrf_fuse(
    ranked_lists: List[List[int]],
    k: int = 60,
) -> List[Tuple[int, float]]:
    """RRF (Reciprocal Rank Fusion)。"""
    scores: Dict[int, float] = defaultdict(float)
    for rlist in ranked_lists:
        for rank, idx in enumerate(rlist, 1):
            scores[idx] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: -x[1])


def multi_query_retrieve(
    queries: List[str],
    child_vecs: np.ndarray,
    bm25: BM25,
    top_n: int = TOP_K_RERANK_INPUT,
) -> List[int]:
    """多查询 + 混合检索 + RRF 融合，返回候选子块索引列表。"""
    all_rankings: List[List[int]] = []
    for q in queries:
        vec_hits, bm_hits = hybrid_search_one(q, child_vecs, bm25)
        all_rankings.append(vec_hits)
        all_rankings.append(bm_hits)

    fused = rrf_fuse(all_rankings)
    return [idx for idx, _ in fused[:top_n]]


# ─────────────────────────── Rerank ───────────────────────────

RERANK_PROMPT = """你是芯片数据手册检索专家。

用户查询: {query}

下面是从数据手册中检索到的 {n} 个候选片段（编号 0~{n_minus_1}）。
请从**用户真正需要的信息**出发，选出最相关的 {k} 个。

关键判断标准（按优先级）：
1. **数值完整性**：该片段是否包含用户查询参数的具体数值？
   例如查询"IDD"，应优先选带 "14.1 mA" 这类具体值的片段。
2. **条件匹配**：片段描述的工作条件是否与用户意图一致？
   例如查询"Supply current"（默认指运行时的典型消耗），应选 Run mode 的典型值，
   而不是 Sleep/Stop 模式或最大值。
3. **表格优先**：如果片段是表格，优先选带完整表头（Symbol/Parameter/Conditions）
   的，而不是被切断的碎片。
4. **避免过度补充**：不要为了"覆盖面广"而选择多个描述同一参数的相似片段，
   只选用户真正需要的那 1-2 个。

候选片段:
{chunks}

输出 JSON（仅 JSON，不要解释）:
{{"selected": [索引1, 索引2, ...], "reasons": {{"索引1": "简短理由", ...}}}}
"""


def llm_rerank(
    query: str,
    candidates: List[Dict],
    llm: LLMClient,
    k: int = TOP_K_FINAL,
    verbose: bool = True,
) -> Tuple[List[Dict], int]:
    """LLM rerank。返回 (选中的 k 个, tokens)。"""
    if len(candidates) <= k:
        return candidates, 0

    parts = []
    for i, c in enumerate(candidates):
        loc = f"[{c['node_id']} {c['title']}]"
        snippet = c["text"][:280].replace("\n", " ")
        parts.append(f"[{i}] {loc} ({c['type']})  {snippet}")
    chunks_text = "\n\n".join(parts)

    prompt = RERANK_PROMPT.format(
        query=query, n=len(candidates),
        n_minus_1=len(candidates) - 1, k=k, chunks=chunks_text,
    )

    if verbose:
        print(f"    [rerank] prompt {len(prompt)} 字符 → LLM")

    resp = llm.chat([
        {"role": "system", "content": "你是芯片数据手册检索专家，只输出 JSON。"},
        {"role": "user", "content": prompt},
    ])

    if not resp.success:
        if verbose:
            print(f"    [rerank] ✗ LLM 失败，退回前 {k} 个")
        return candidates[:k], 0

    if verbose:
        print(f"    [rerank] tokens={resp.total_tokens}")

    try:
        data = parse_json_loose(resp.text)
        idxs = data.get("selected", [])
        idxs = [i for i in idxs
                if isinstance(i, int) and 0 <= i < len(candidates)]
        if not idxs:
            return candidates[:k], resp.total_tokens
        return [candidates[i] for i in idxs[:k]], resp.total_tokens
    except Exception as e:
        if verbose:
            print(f"    [rerank] ✗ 解析失败 ({e})")
        return candidates[:k], resp.total_tokens


# ─────────────────────────── 生成 ───────────────────────────

RAG_USER_TEMPLATE = """## 用户需求: {query}

## 参考片段（来自多查询混合检索 + LLM rerank）:
{context}

## 输出一行 JSON:
"""


def rag_extract(
    chip: str,
    query: str,
    idx: Dict[str, Any],
    llm: LLMClient,
    verbose: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, int], List[Dict]]:
    """最强 RAG 完整流程。"""
    tokens = {"expand": 0, "rerank": 0, "generate": 0, "total": 0}

    parents = idx["parents"]
    children = idx["children"]
    child_vecs = idx["child_vecs"]
    bm25 = idx["bm25"]

    # 1. Query 扩展
    queries, t_expand = expand_queries(query, llm, verbose=verbose)
    tokens["expand"] = t_expand

    # 2. 多查询混合检索 → 候选子块
    if verbose:
        print(f"    [检索] {len(queries)} 个 query 变体，混合检索...")
    cand_idx = multi_query_retrieve(queries, child_vecs, bm25,
                                     top_n=TOP_K_RERANK_INPUT)

    # 候选子块 → 对应父块（去重）
    parent_idxs: List[int] = []
    seen: Set[int] = set()
    for ci in cand_idx:
        pid = children[ci]["_parent"]
        if pid not in seen:
            seen.add(pid)
            parent_idxs.append(pid)

    if verbose:
        print(f"    [检索] 候选 {len(cand_idx)} 子块 → {len(parent_idxs)} 父块")

    candidates = [parents[pi] for pi in parent_idxs]

    # 3. LLM rerank
    selected, t_rerank = llm_rerank(query, candidates, llm,
                                     k=TOP_K_FINAL, verbose=verbose)
    tokens["rerank"] = t_rerank

    if verbose:
        print(f"    [rerank] 选中 {len(selected)} 个:")
        for i, s in enumerate(selected, 1):
            print(f"      [{i}] [{s['node_id']}] {s['title']}  ({s['type']})")

    # 4. 生成
    context_parts = []
    for i, s in enumerate(selected, 1):
        loc = f"[{s['node_id']} {s['title']}]"
        context_parts.append(f"--- 片段 {i} {loc} ---\n{s['text']}")
    context = "\n\n".join(context_parts)

    user_prompt = RAG_USER_TEMPLATE.format(query=query, context=context)

    if verbose:
        print(f"    [生成] prompt {len(user_prompt)} 字符")

    resp = llm.chat([
        {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ])

    if not resp.success:
        tokens["total"] = sum(tokens.values())
        return {"found": False, "error": resp.error_msg}, tokens, selected

    tokens["generate"] = resp.total_tokens
    tokens["total"] = sum(tokens.values())

    if verbose:
        print(f"    [生成] tokens={resp.total_tokens}")

    try:
        result = parse_json_loose(resp.text)
    except Exception as e:
        result = {"found": False, "raw": resp.text, "parse_error": str(e)}

    result["_selected"] = [
        {"node_id": s["node_id"], "title": s["title"],
         "type": s["type"]}
        for s in selected
    ]

    return result, tokens, selected


# ─────────────────────────── 单次查询 ───────────────────────────

def one_query(chip: str, query: str, idx: Dict[str, Any],
              llm: LLMClient) -> Dict[str, Any]:
    t0 = time.time()

    print(f"\n▶ {query}")

    try:
        result, tokens, selected = rag_extract(chip, query, idx, llm, verbose=True)
    except Exception as e:
        print(f"  ✗ 异常: {e}")
        return {"query": query, "ok": False, "error": str(e)}

    elapsed = time.time() - t0

    ok = result.get("found") is not False and \
         any(result.get(k) is not None for k in ("min", "typ", "max"))

    if not ok:
        print(f"  ✗ 未找到")
    else:
        name = result.get("name", "?")
        unit = result.get("unit", "")
        vals = []
        if result.get("min") is not None:
            vals.append(f"min={result['min']}")
        if result.get("typ") is not None:
            vals.append(f"typ={result['typ']}")
        if result.get("max") is not None:
            vals.append(f"max={result['max']}")
        print(f"  ✓ {name} = {' / '.join(vals)} {unit}")
        if result.get("condition"):
            print(f"    条件: {result['condition']}")
        if result.get("reason"):
            print(f"    理由: {result['reason']}")

    t = tokens["total"]
    print(f"  [{elapsed:.1f}s | 扩展 {tokens['expand']} + "
          f"rerank {tokens['rerank']} + 生成 {tokens['generate']} = {t} tokens]")

    return {
        "query": query,
        "ok": ok,
        "result": result,
        "tokens": tokens,
        "elapsed": round(elapsed, 1),
        "selected": result.get("_selected", []),
    }


# ─────────────────────────── 主流程 ───────────────────────────

def run_all(chip: str, queries: List[str]):
    print("=" * 70)
    print("  最强 RAG 基线（多查询 + 父子块 + 混合检索 + LLM Rerank）")
    print(f"  芯片: {chip}")
    print(f"  Query 数: {len(queries)}")
    print("=" * 70)

    print("\n初始化索引")
    try:
        idx = build_or_load_index(chip, verbose=True)
    except Exception as e:
        print(f"✗ 索引构建失败: {e}")
        return

    llm = LLMClient()
    results: List[Dict[str, Any]] = []

    for query in queries:
        r = one_query(chip, query, idx, llm)
        results.append(r)

    # 汇总
    total_tokens = sum(r.get("tokens", {}).get("total", 0) for r in results)
    total_expand = sum(r.get("tokens", {}).get("expand", 0) for r in results)
    total_rerank = sum(r.get("tokens", {}).get("rerank", 0) for r in results)
    total_generate = sum(r.get("tokens", {}).get("generate", 0) for r in results)
    total_time = sum(r.get("elapsed", 0) for r in results)
    ok_count = sum(1 for r in results if r.get("ok"))
    n = max(len(queries), 1)

    print("\n" + "=" * 70)
    print("  最强 RAG 汇总")
    print("=" * 70)
    print(f"  Query 数:      {len(queries)}")
    print(f"  命中:          {ok_count}/{len(queries)}")
    print(f"  总 token:      {total_tokens}")
    print(f"    扩展:        {total_expand}")
    print(f"    rerank:      {total_rerank}")
    print(f"    生成:        {total_generate}")
    print(f"  平均 token:    {total_tokens / n:.0f}")
    print(f"  总耗时:        {total_time:.1f}s")
    print(f"  平均耗时:      {total_time / n:.1f}s")

    print("\n  明细:")
    print(f"  {'Query':<18} {'结果':<36} {'Token':>8} {'时间':>7}")
    print("  " + "─" * 72)
    for r in results:
        query = r["query"]
        if not r.get("ok"):
            summary = "✗ 未找到"
        else:
            res = r.get("result", {})
            name = res.get("name", "?")
            unit = res.get("unit", "")
            vals = []
            if res.get("typ") is not None:
                vals.append(f"typ={res['typ']}")
            elif res.get("min") is not None or res.get("max") is not None:
                vals.append(f"{res.get('min','?')}-{res.get('max','?')}")
            summary = f"{name} = {'/'.join(vals)} {unit}"
        tokens = r.get("tokens", {}).get("total", 0)
        elapsed = r.get("elapsed", 0)
        print(f"  {query:<18} {summary:<36} {tokens:>8} {elapsed:>6.1f}s")

    from chips_extractor.paths import work_dir
    out_path = work_dir(chip, create=True) / f"{chip}_rag_max_results.json"
    out_path.write_text(
        json.dumps({
            "chip": chip,
            "method": "rag_max",
            "total_tokens": total_tokens,
            "total_expand_tokens": total_expand,
            "total_rerank_tokens": total_rerank,
            "total_generate_tokens": total_generate,
            "total_elapsed": round(total_time, 1),
            "ok_count": ok_count,
            "results": results,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n  结果已保存: {out_path}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="最强 RAG 基线")
    parser.add_argument("--chip", default=CHIP, help="芯片名")
    parser.add_argument("--rebuild", action="store_true",
                        help="强制重建索引")
    args = parser.parse_args()

    if args.rebuild:
        idx_dir = _index_dir(args.chip)
        import shutil
        if idx_dir.exists():
            shutil.rmtree(idx_dir)
        print("[RAG-max] 已清除缓存")

    run_all(args.chip, TEST_QUERIES)


if __name__ == "__main__":
    main()