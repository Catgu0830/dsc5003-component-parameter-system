"""项目路径与中间文件布局（单一出口）。

目的：把「与大模型相关的全部产出」统一收纳在 llm_output 下，并按家族分目录，
避免根目录被中间文件淹没，同时与解析类产物（mineru / 结构树）分开。

目录约定：
    output/
    ├── llm_output/                     ← 所有与大模型相关的产出
    │   ├── intermediate/               ← 中间文件（每次运行覆盖，可随时删）
    │   │   ├── STM32/  <chip>_routed.json / <chip>_params.json
    │   │   ├── ESP/  GD32/  ADI/  OTHER/
    │   │   └── _debug/  JSON 解析失败时的原始输出
    │   ├── rag_index/                  ← RAG 索引缓存（按家族）
    │   │   ├── STM32/ ESP/ GD32/ ADI/
    │   └── test_*/                     ← 正式实验结果（论文数据来源）
    ├── mineru_output/                  ← 版面解析产物
    └── structure_tree_output/          ← 结构树与章节内容

用法：
    from chips_extractor.paths import routed_path, params_path, work_dir

    routed_path("stm32f100vc")   # output/llm_output/intermediate/STM32/stm32f100vc_routed.json
    params_path("esp32-c3_datasheet_en")
    work_dir("ad8000")           # output/llm_output/intermediate/ADI/
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = PROJECT_ROOT / "output"
LLM_OUTPUT_ROOT = OUTPUT_ROOT / "llm_output"

# 与大模型相关的产物统一放在 llm_output 下，并按家族分目录
INTERMEDIATE_ROOT = LLM_OUTPUT_ROOT / "intermediate"
RAG_INDEX_ROOT = LLM_OUTPUT_ROOT / "rag_index"

_FAMILY_RULES = [
    ("STM32", ("stm32",)),
    ("ESP", ("esp", "0a-esp")),
    ("GD32", ("gd32",)),
    ("ADI", ("ad", "adp", "adsp", "aduc", "adum", "adxl", "adf", "adl", "lt", "hmc")),
]


def family_dir(chip: str) -> str:
    """按芯片名归入家族目录（STM32 / ESP / GD32 / ADI / OTHER）。"""
    n = (chip or "").lower()
    for name, prefixes in _FAMILY_RULES:
        if any(n.startswith(p) for p in prefixes):
            return name
    return "OTHER"


def work_dir(chip: str, create: bool = False) -> Path:
    """该芯片的中间文件目录。"""
    d = INTERMEDIATE_ROOT / family_dir(chip)
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def routed_path(chip: str) -> Path:
    """第一阶段（路由）中间文件。"""
    return work_dir(chip) / f"{chip}_routed.json"


def params_path(chip: str) -> Path:
    """第二阶段（提取/回退）中间文件。"""
    return work_dir(chip) / f"{chip}_params.json"


def debug_path(chip: str, name: str) -> Path:
    """任意调试产物，落在该芯片的中间目录下。"""
    return work_dir(chip, create=True) / f"{chip}__{name}"


def ensure_intermediate() -> Path:
    INTERMEDIATE_ROOT.mkdir(parents=True, exist_ok=True)
    return INTERMEDIATE_ROOT
