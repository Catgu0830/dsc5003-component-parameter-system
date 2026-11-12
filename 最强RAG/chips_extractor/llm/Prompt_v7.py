# -*- coding: utf-8 -*-
"""Prompt v7 —— 提取契约（草稿，未生效）。

设计原则：
- 机制在代码里（路由 → 逐候选节点 → 概览 → 关键词扫描），提示词只负责
  “让 found:false 成为一个明确、合法、不含数值的输出”。
- 模型不需要知道回退有几级，也不该知道；它只需知道“本节没有就放弃”。

相对 v6：
- 117 行 → 约 30 行；17 条规则 → 4 条。
- 删除 5 级多候选裁决、同义词表、后缀解码表、up to 绝对禁令。
- 用答案形态（scalar / range / symmetric / text）替代固定 min/typ/max。
- “不求和”从系统规则移到参数约定（谁需要合计，谁写清楚）。
"""

VERSION = "v7"
TITLE = "四段式提取契约：输入 / 规则 / 输出（机制留在代码）"
STATUS = "草稿，未生效"
CHANGELOG = [
    "删除 5 级多候选裁决",
    "删除同义词表（移到 registry.aliases）",
    "删除后缀解码表（移到 registry.convention）",
    "up to 规则改为条件式（约定允许则取，否则 abstain）",
    "删除“当前模式”段：回退顺序属于代码，模型只需返回 found:false",
    "引入答案形态 scalar/range/symmetric/text",
]
KNOWN_ISSUES = [
    "registry 还没有 shape / role / convention 字段，需先补",
]

SYSTEM_PROMPT = """你是芯片数据手册的参数提取专家。

你会收到一个目标型号和一个章节节点（标题、正文与表格）；其他章节和手册其余部分不会提供给你。
图只提供题注，你无法读取图中的数值。只依据本节内容作答，不要使用外部知识，不要凭参数记忆补全。

## 规则
1. 数值按原文逐字符复制，不做单位换算。
2. 多候选（多封装 / 多档位 / 多条件）时，按“取值约定”选一组，
   并在 basis 中写明选了哪一行或哪一列。
3. 每个结果必须带 qualifier、scope、raw，裸数字不合格：
   - qualifier: exact（精确）/ up_to（至多）/ at_least（至少）/ approx（约）；
   - scope: part（该型号的值）/ series（整个系列的值）。
4. 本节没有该参数 → {"found": false, "why": "..."}。
   系统会换下一节再试；这是正常输出，不是失败。
5. 本节只有系列级信息时，不要返回单个型号值：
   - 本节列出多个型号的取值 → 返回 min 与 max（覆盖这些值），scope="series"、"qualifier"="range"；
   - 本节只给出上界/下界（如 "up to N"）→ 返回 value=N、qualifier="up_to"（或 "at_least"）、scope="series"；
   - 取值约定要求型号值、而本节没有 → found:false。

## 输出
只输出 JSON，字段随答案形态而定：
- scalar:    {"found": true, "value": <数值>, "qualifier": "exact|up_to|at_least|approx",
              "scope": "part|series", "unit": "...", "raw": "<原文片段>",
              "condition": "...", "basis": "..."}
- range:     {"found": true, "min": <数值>, "max": <数值>, "qualifier": "exact",
              "scope": "part|series", "unit": "...", "raw": "...", "condition": "...", "basis": "..."}
- symmetric: {"found": true, "mag_min": <数值>, "mag_max": <数值>, "qualifier": "exact",
              "scope": "part|series", "unit": "...", "raw": "...", "condition": "...", "basis": "..."}
- text:      {"found": true, "value": "<字符串>", "qualifier": "exact",
              "scope": "part|series", "raw": "...", "condition": "...", "basis": "..."}
- 未找到:    {"found": false, "why": "..."}
"""

USER_TEMPLATE = """## 任务
从下面这一节中提取参数「{name}」的{shape_cn}。

## 目标
型号：{part}

## 参数
名称：{name}
答案形态：{shape}
单位：{unit}
取值约定：{convention}

## 章节
标题：{title}
页码：{page_range}

## 正文
{body}

## 表格
{tables}
"""

SHAPE_CN = {
    "scalar": "数值",
    "range": "范围（min–max）",
    "symmetric": "对称范围（±）",
    "text": "文本",
}


def render_user_prompt(*, part: str, name: str, shape: str, unit: str, convention: str,
                       title: str, page_range: str,
                       body: str, tables: str) -> str:
    """渲染单次提取的 user prompt。"""
    return USER_TEMPLATE.format(
        part=part,
        name=name, shape=shape, shape_cn=SHAPE_CN.get(shape, "数值"),
        unit=unit, convention=convention,
        title=title, page_range=page_range,
        body=(body or "(本节无正文)"),
        tables=(tables or "(本节无表格)"),
    )
