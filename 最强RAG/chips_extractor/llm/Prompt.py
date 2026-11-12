# -*- coding: utf-8 -*-
"""提示词版本指针（切换当前生效版本只改这里）。

**当前口径（2026-11-05 起）：提取用 v7，路由用 v4，全部取最后一版。**

保留的版本：
    Prompt_v7.py   当前生效 —— shape/unit/convention 口径，run_* 脚本与主流水线一致使用
    Prompt_v6.py   上一版（型号后缀解码），仅为追溯保留

已归档到 `_archive/2026-11-05_cleanup/旧代码/`：
    Prompt_v1.py   原始版本（废弃）
    Prompt_v2.py   多候选裁决顺序 + 禁止单位换算
    Prompt_v3.py   同源约束 + 纯数字 + found:false 边界
    Prompt_v4.py   抗抖动（实测未采用）
    Prompt_v5.py   参数名同义变体

用法：
    from chips_extractor.llm.Prompt import SYSTEM_PROMPT, VERSION
"""
from chips_extractor.llm.Prompt_v7 import (  # noqa: F401
    SYSTEM_PROMPT, VERSION, TITLE, STATUS, CHANGELOG, KNOWN_ISSUES,
)
