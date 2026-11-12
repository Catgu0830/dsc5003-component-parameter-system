#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 2: 参数提取（主提取）。

读 {chip}_routed.json，按 target_sections 从 {chip}_content.json 拿章节内容，
调用 LLM 提取参数的 min/typ/max、测试条件、选择理由。

不做回退——回退由 fallback.py 负责。
extract_from_node 等工具函数对外暴露，供 fallback.py 复用。

用法：
    python extract.py --chip stm32f100vc
    python extract.py --chip stm32f100vc --query "工作电流 IDD"
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _FILE.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from chips_extractor.llm.client import LLMClient  # noqa: E402


# ─────────────────────────── 路径 ───────────────────────────

CONTENTS_DIR = _PROJECT_ROOT / "output" / "structure_tree_output" / "contents"
OUT_DIR = _PROJECT_ROOT / "output" / "llm_output"      # 正式结果目录（兼容保留）

# 中间文件统一出口（不再写进 llm_output 根目录）
from chips_extractor.paths import (                      # noqa: E402
    routed_path, params_path, INTERMEDIATE_ROOT,
)

MAX_TABLE_LINES = 120   # 表格正文按行截断上限（规格表最长约 102 行，统一取 120）

# 多候选章节策略：
#   True  = 按路由给出的优先级依次尝试，**第一个成功即停**（省 token、避免同参数多值）
#   False = 旧行为：所有目标章节都跑一遍，结果全收
FIRST_HIT_ONLY = True
# 最多尝试几个目标章节（路由最多给 3 个）
MAX_TARGET_TRIES = 3

# 父节下探：若目标节点自身正文少于该字数且存在子节点，则把子节点也作为候选
TARGET_CHILD_DESCENT = True
MIN_PARENT_CHARS = 300
MAX_CHILD_TRIES = 3

# 有据性闸门：取到的数值必须能在该节点原文中找到，否则视为无依据并放弃该节点
# （放弃后会自动尝试下一个候选章节；全部无依据则触发概览回退）
GROUNDING_CHECK = True

# 量纲闸门：结果单位必须与参数声明的量纲相容（如 SPI 接口数不能返回 MHz）
UNIT_KIND_CHECK = True


def _nums(s) -> List[float]:
    """提取文本中的数值；先归一化各种破折号与千分位。

    数据手册里负号可能是 ASCII '-'、U+2212 '−'、en dash '–'（U+2013）
    或 em dash '—'，甚至全角 '－'。不归一化会导致 -65 与 –65 被判为不同，
    进而让「有据性闸门」误杀正确结果。
    """
    s = s or ""
    for ch in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015",
               "\u2212", "\uff0d", "−"):
        s = s.replace(ch, "-")
    s = s.replace(",", "").replace("\uff0c", "")
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", s)]


def value_in_text(text: str, result: Dict) -> bool:
    """检查结果里的每个数值是否都出现在 text 中（1% 容差）。

    额外处理 `±N` 记号：数据手册大量使用 ±5 V / ±18 V 表示双极性电源，
    此时文本里没有 "-5"，但语义上 -5 是存在的。这里把 `±N` 同时展开为 +N 与 -N。
    """
    vals = [result.get(k) for k in ("min", "typ", "max") if result.get(k) is not None]
    if not vals or not text:
        return False
    tn = set(_nums(text))
    # ±N / +/-N 展开为 +N 与 -N
    for m in re.finditer(r"(?:±|\+/-|＋／－)\s*(\d+(?:\.\d+)?)", text):
        try:
            x = float(m.group(1))
        except ValueError:
            continue
        tn.add(x)
        tn.add(-x)
    for v in vals:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return False
        tol = max(abs(v) * 0.01, 1e-9)
        if not any(abs(x - v) <= tol for x in tn):
            return False
    return True


GROUNDING_WINDOW = 150          # 严格判据：数值必须出现在参数名 ± 该字符内
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-]{1,}")


def _query_tokens(query: str) -> List[str]:
    stop = {"of", "the", "a", "an", "and", "or", "in", "for", "range",
            "value", "values", "max", "min", "maximum", "minimum", "number"}
    toks = [t.lower() for t in _TOKEN_RE.findall(query or "")]
    return [t for t in toks if t not in stop]


def value_in_text_strict(text: str, result: Dict, query: str) -> bool:
    """严格有据判据：所有数值必须**同时**落在某个「参数名出现位置」的窗口内。

    宽松判据只问"这个数字在本章节里出现过吗"，对 2、3、12 这类小整数极易误判为有据；
    严格判据要求数值与参数名邻近，能压掉这类假阳性。
    仍处理 ±N 展开与破折号归一化。
    """
    vals = [result.get(k) for k in ("min", "typ", "max") if result.get(k) is not None]
    toks = _query_tokens(query)
    if not vals or not text or not toks:
        return False
    low = text
    for v in vals:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return False
    targets = [float(v) for v in vals]
    tol = [max(abs(v) * 0.01, 1e-9) for v in targets]
    need = len(toks) if len(toks) <= 3 else max(2, len(toks) // 2)

    def window_has(seg: str) -> bool:
        sn = set(_nums(seg))
        for m in re.finditer(r"(?:±|\+/-|＋／－)\s*(\d+(?:\.\d+)?)", seg):
            try:
                x = float(m.group(1))
            except ValueError:
                continue
            sn.add(x)
            sn.add(-x)
        return all(any(abs(x - t) <= tl for x in sn) for t, tl in zip(targets, tol))

    for tok in toks:
        for m in re.finditer(re.escape(tok), low, re.I):
            s = max(0, m.start() - GROUNDING_WINDOW)
            e = min(len(low), m.end() + GROUNDING_WINDOW)
            seg = low[s:e]
            # 多词查询：要求其余关键词也出现在同一窗口内（避免只靠 "voltage" 命中）
            if need > 1:
                present = sum(1 for t in toks if re.search(re.escape(t), seg, re.I))
                if present < need:
                    continue
            if window_has(seg):
                return True
    return False


# ─────────────────────────── 工具 ───────────────────────────

def parse_json_loose(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError("LLM 返回为空")
    m = re.search(r"```(?:json)?\s*\n([\s\S]*?)```", text)
    if m:
        return json.loads(m.group(1).strip())
    m = re.search(r"(\{[\s\S]*\})", text)
    if m:
        return json.loads(m.group(1).strip())
    return json.loads(text.strip())


def load_routed(chip: str) -> Tuple[Dict, Path]:
    path = routed_path(chip)
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path}，请先运行 route.py")
    return json.loads(path.read_text(encoding="utf-8")), path


def load_content(chip: str) -> Tuple[Dict, Path]:
    path = CONTENTS_DIR / f"{chip}_content.json"
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path}")
    return json.loads(path.read_text(encoding="utf-8")), path


# ─────────────────────────── 内容查找 ───────────────────────────

def find_node_by_title(content_data: Dict, title: str) -> Optional[Dict]:
    def norm(s: str) -> str:
        s = re.sub(r'^\d+(\.\d+)*\s*', '', s or '')
        s = re.sub(r'\s+', '', s)
        return s.lower()

    target = norm(title)
    exact = None
    fallback = None

    def walk(nodes):
        nonlocal exact, fallback
        for n in nodes:
            t = n.get("title", "")
            if t == title and exact is None:
                exact = n
            elif norm(t) == target and fallback is None:
                fallback = n
            walk(n.get("children", []))

    walk(content_data.get("sections", []))
    return exact or fallback


def html_to_text(html: str) -> str:
    if not html:
        return ""
    t = re.sub(r'</t[dh]>\s*<t[dh][^>]*>', ' | ', html)
    t = re.sub(r'</tr>', '\n', t)
    t = re.sub(r'<[^>]+>', '', t)
    lines = [re.sub(r'[ \t]+', ' ', ln).strip() for ln in t.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def load_content_list_map(content_data: Dict) -> Dict[str, Dict]:
    mineru_dir = content_data.get("mineru_dir")
    if not mineru_dir:
        return {}
    d = Path(mineru_dir)
    if not d.is_dir():
        return {}

    # MinerU 产物的命名有两种：`content_list.json` 与 `<name>_content_list.json`。
    # 早期只匹配后者，导致 8 份 MPU（stm32mp1xx）的 cl_map 为空、所有表格不可见。
    cands = [c for c in d.glob("*content_list.json")
             if "v2" not in c.name.lower()]
    if not cands:
        cands = list(d.glob("*content_list.json"))
    if not cands:
        return {}

    data = json.loads(cands[0].read_text(encoding="utf-8"))
    m: Dict[str, Dict] = {}
    for blk in data:
        if blk.get("type") == "table" and blk.get("img_path"):
            m[blk["img_path"]] = blk
    return m


def _resolve_table_body(table_ref: Dict,
                        content_list_map: Dict[str, Dict]) -> str:
    blk = content_list_map.get(table_ref.get("img_path", ""))
    if not blk:
        return ""
    body = html_to_text(blk.get("table_body", ""))
    lines = body.splitlines()
    if len(lines) > MAX_TABLE_LINES:
        total = len(lines)
        lines = lines[:MAX_TABLE_LINES] + [f"... (共 {total} 行，已截断)"]
    return "\n".join(lines)


def collect_node_content(node: Dict) -> Dict:
    content = node.get("content", {}) or {}
    text = (content.get("text") or "").strip()
    tables = list(content.get("tables") or [])
    figures = list(content.get("figures") or [])

    if text or tables:
        return {"text": text, "tables": tables, "figures": figures}

    sub_texts: List[str] = []
    for child in node.get("children", []):
        cc = collect_node_content(child)
        if cc["text"]:
            sub_texts.append(f"### {child.get('title', '')}\n{cc['text']}")
        tables.extend(cc["tables"])
        figures.extend(cc["figures"])

    if sub_texts:
        text = "\n\n".join(sub_texts)

    return {"text": text, "tables": tables, "figures": figures}


# ─────────────────────────── 提取提示词 ───────────────────────────

# 提示词按版本管理，见 chips_extractor/llm/Prompt_v*.py
# 切换版本改 chips_extractor/llm/Prompt.py 即可
from chips_extractor.llm.Prompt import SYSTEM_PROMPT as EXTRACT_SYSTEM_PROMPT  # noqa: E402


def build_section_prompt(query: str, node: Dict,
                         content_list_map: Dict[str, Dict],
                         is_fallback: bool = False) -> str:
    content = node.get("content", {})
    parts: List[str] = [f"## 用户需求: {query}", ""]

    if is_fallback:
        parts.append(
            "（注意：以下内容来自**概览章节**，不是详细的电气特性章节。"
            "数值可能不完整或不够精确，但如果能匹配用户需求的相关规格，"
            "请返回。如果确实没有相关内容，返回 found=false。）"
        )
        parts.append("")

    parts.append(f"## 章节: {node.get('title', '')}")
    if node.get("page_start") is not None:
        parts.append(f"（物理页 {node['page_start']}-{node['page_end']}）")

    text = (content.get("text") or "").strip()
    if text:
        parts.append("\n## 正文:\n" + text)

    tables = content.get("tables") or []
    if tables:
        parts.append("\n## 表格:")
        for i, t in enumerate(tables, 1):
            cap = t.get("caption") or "(无题注)"
            fn = t.get("footnote") or ""
            parts.append(f"\n### 表 {i}: {cap}")
            if fn:
                parts.append(f"注: {fn}")
            body = _resolve_table_body(t, content_list_map)
            if body:
                parts.append(body)
            else:
                parts.append(f"[表格图片: {t.get('img_path','')}]")

    figures = content.get("figures") or []
    if figures:
        parts.append("\n## 图（仅题注，实际内容在图片里）:")
        for i, f in enumerate(figures, 1):
            cap = f.get("caption") or "(无题注)"
            parts.append(f"- 图 {i}: {cap}")

    parts.append("\n## 输出一行 JSON:")
    return "\n".join(parts)


# ─────────────────────────── 单章节提取（公用） ───────────────────────────

def extract_from_node(
    query: str,
    node: Dict,
    nid: str,
    cl_map: Dict[str, Dict],
    llm: LLMClient,
    is_fallback: bool = False,
    verbose: bool = True,
    param_query: Optional[str] = None,
) -> Tuple[Optional[Dict], int]:
    """从单个章节节点提取参数。返回 (结果字典或None, 消耗tokens)。

    param_query: 原始参数名（不含芯片名），用于严格有据判据。
                 不传则退回 query——但 query 可能带芯片名前缀，会让严格判据失败。
    """
    bare_query = param_query or query
    collected = collect_node_content(node)
    node = dict(node)
    node["content"] = collected

    text_len = len(collected.get("text") or "")
    table_cnt = len(collected.get("tables") or [])
    tag = "[回退] " if is_fallback else ""

    if verbose:
        print(f"\n{tag}[提取] [{nid}] {node.get('title', '')}  "
              f"(text={text_len}字符, tables={table_cnt}张)")

    if text_len == 0 and table_cnt == 0:
        if verbose:
            print(f"    → 章节内容为空，跳过")
        return None, 0

    section_prompt = build_section_prompt(
        query, node, cl_map, is_fallback=is_fallback
    )
    messages = [
        {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": section_prompt},
    ]

    if verbose:
        print(f"    prompt {len(section_prompt)} 字符 → LLM", flush=True)

    resp = llm.chat(messages)
    if not resp.success:
        if verbose:
            print(f"    → 失败: {resp.error_msg}")
        return None, 0

    if verbose:
        print(f"    → tokens={resp.total_tokens}")

    try:
        result = parse_json_loose(resp.text)
    except Exception as e:
        d = INTERMEDIATE_ROOT / "_debug"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{nid}_raw.txt").write_text(
            resp.text, encoding="utf-8")
        if verbose:
            print(f"    → JSON 解析失败: {e}，原始文本已保存")
        return None, resp.total_tokens

    if result.get("found") is False:
        if verbose:
            print(f"    → 未在章节中找到「{query}」")
        return None, resp.total_tokens

    if not any(result.get(k) is not None
               for k in ("min", "typ", "max")):
        if verbose:
            print(f"    → 未在章节中找到「{query}」")
        return None, resp.total_tokens

    # ── 有据性判定：无论闸门是否开启，都计算一次并记入结果
    # 闸门关闭时用于离线统计，闸门开启时用于拦截；两者用同一判据，保证可比。
    node_text = (collected.get("text") or "")
    for tb in (collected.get("tables") or []):
        node_text += "\n" + (tb.get("caption") or "") + "\n" + (
            _resolve_table_body(tb, cl_map) or "")
    grounded = value_in_text(node_text, result)                    # 宽松
    grounded_strict = value_in_text_strict(node_text, result, bare_query)  # 严格（邻近）

    if GROUNDING_CHECK and not grounded:
        if verbose:
            print(f"    → 值 {result.get('min')}/{result.get('typ')}/{result.get('max')} "
                  f"不在本节原文中，判定为无依据，放弃本节点")
        return None, resp.total_tokens

    # ── 量纲闸门：单位必须与参数声明的量纲相容（拦截"接口数答成 MHz"）
    if UNIT_KIND_CHECK:
        from chips_extractor.params import unit_kind_ok
        if not unit_kind_ok(bare_query, result.get("unit", "")):
            if verbose:
                print(f"    → 单位 {result.get('unit')!r} 与参数「{bare_query}」的量纲不符，放弃本节点")
            return None, resp.total_tokens

    result["_section_id"] = nid
    result["_section_title"] = node.get("title", "")
    result["_grounded"] = grounded
    result["_grounded_strict"] = grounded_strict
    if is_fallback:
        result["_fallback"] = True

    if verbose:
        name = result.get("name", "?")
        unit = result.get("unit", "")
        cond = result.get("condition", "")
        print(f"    → {name}: "
              f"min={result.get('min')} "
              f"typ={result.get('typ')} "
              f"max={result.get('max')} {unit}"
              + (f"  ({cond})" if cond else ""))
        if result.get("reason"):
            print(f"      理由: {result['reason']}")

    return result, resp.total_tokens


# ─────────────────────────── 主流程 ───────────────────────────

def run(chip: str, query_override: Optional[str] = None,
        verbose: bool = True) -> Optional[Dict]:
    if verbose:
        print("=" * 70)
        print("  Stage 2: 参数提取（主提取）")
        print(f"  芯片: {chip}")
        print("=" * 70)

    routed, routed_path = load_routed(chip)
    query = query_override or routed.get("query", "")
    targets = routed.get("target_sections", [])
    stage1_tokens = routed.get("total_tokens", 0)

    # ★ 给提取 LLM 用的 query：带上芯片型号
    llm_query = query if chip.lower() in query.lower() else f"{chip} 的 {query}"

    if verbose:
        print(f"[加载] 路由: {routed_path.name}")
        print(f"  query  : {query}")
        print(f"  llm_q  : {llm_query}")
        print(f"  targets: {len(targets)} 个\n")

    # ── 空路由
    if not targets:
        payload = {
            "chip": chip, "query": query,
            "routed_sections": [],
            "overview_section": routed.get("overview_section"),
            "stage1_tokens": stage1_tokens,
            "stage2_tokens": 0,
            "fallback_tokens": 0,
            "total_tokens": stage1_tokens,
            "total_params": 0,
            "parameters": [],
        }
        out_path = params_path(chip)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if verbose:
            print("[提取] 路由结果为空，结束")
        return payload

    content_data, content_path = load_content(chip)
    if verbose:
        print(f"[加载] 内容: {content_path.name}  "
              f"({content_data.get('total_sections', 0)} 节)")

    cl_map = load_content_list_map(content_data)
    if verbose:
        if cl_map:
            print(f"[提取] 表格 HTML 映射: {len(cl_map)} 张")
        else:
            print("[提取] ⚠ 无表格映射，表格将以占位符形式提供")

    llm = LLMClient()
    all_params: List[Dict] = []
    stage2_tokens = 0

    if verbose:
        print("\n" + "─" * 70)

    # 展开候选：路由给的是父节点时，若父节点自身正文很少（说明数据在子节点里），
    # 把子节点追加为候选。这是结构性规则，与具体文档无关。
    attempts: List[Dict] = []
    for tgt in targets[:MAX_TARGET_TRIES]:
        node = find_node_by_title(content_data, tgt.get("title", ""))
        if node is None:
            continue
        attempts.append({"node_id": tgt.get("node_id", ""),
                         "title": tgt.get("title", ""), "node": node})
        if TARGET_CHILD_DESCENT and node.get("children"):
            own = collect_node_content(node).get("text") or ""
            if len(own) < MIN_PARENT_CHARS:
                for ch in node["children"][:MAX_CHILD_TRIES]:
                    attempts.append({"node_id": ch.get("node_id") or tgt.get("node_id", ""),
                                     "title": ch.get("title", ""), "node": ch})
    if verbose and len(attempts) > len(targets[:MAX_TARGET_TRIES]):
        print(f"[提取] 父节下探：候选章节 {len(targets[:MAX_TARGET_TRIES])} → {len(attempts)}")

    for att in attempts:
        tgt, node = att, att["node"]
        nid = tgt.get("node_id", "")
        title = tgt.get("title", "")

        result, tokens = extract_from_node(
            llm_query, node, nid, cl_map, llm, verbose=verbose,
            param_query=query,
        )
        stage2_tokens += tokens
        if result is not None:
            # 还原 name 为原 query
            result["name"] = query
            all_params.append(result)
            # 首个命中即停：按路由优先级只取第一个成功的章节
            if FIRST_HIT_ONLY:
                break

    # ── 输出
    out_path = params_path(chip)
    out_payload = {
        "chip": chip,
        "query": query,
        "routed_sections": [
            {"node_id": t.get("node_id"), "title": t.get("title"),
             "reason": t.get("reason", "")}
            for t in targets
        ],
        "overview_section": routed.get("overview_section"),
        "stage1_tokens": stage1_tokens,
        "stage2_tokens": stage2_tokens,
        "fallback_tokens": 0,
        "total_tokens": stage1_tokens + stage2_tokens,
        "total_params": len(all_params),
        "parameters": all_params,
    }
    out_path.write_text(
        json.dumps(out_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if verbose:
        print("\n" + "=" * 70)
        print(f"  完成: {len(all_params)} 个参数")
        print(f"  Stage1 路由:  {stage1_tokens} tokens")
        print(f"  Stage2 提取:  {stage2_tokens} tokens")
        print(f"  合计:         {stage1_tokens + stage2_tokens} tokens")
        print(f"  输出: {out_path}")
        print("=" * 70)

        if all_params:
            print("\n结果:")
            for p in all_params:
                name = p.get("name", "?")
                unit = p.get("unit", "")
                cond = p.get("condition", "")
                reason = p.get("reason", "")
                sec = p.get("_section_id", "?")
                print(f"  [{sec}] {name} ({unit})")
                if p.get("min") is not None:
                    print(f"        min: {p['min']} {unit}")
                if p.get("typ") is not None:
                    print(f"        typ: {p['typ']} {unit}")
                if p.get("max") is not None:
                    print(f"        max: {p['max']} {unit}")
                if cond:
                    print(f"        条件: {cond}")
                if reason:
                    print(f"        理由: {reason}")

    return out_payload


def main():
    parser = argparse.ArgumentParser(description="Stage 2: 参数提取")
    parser.add_argument("--chip", default="stm32f100vc", help="芯片名")
    parser.add_argument("--query", default=None,
                        help="覆盖 routed.json 里的 query（可选）")
    args = parser.parse_args()
    run(args.chip, args.query)


if __name__ == "__main__":
    main()