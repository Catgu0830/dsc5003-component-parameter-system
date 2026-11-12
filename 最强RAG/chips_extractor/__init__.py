"""
ChipDSS Extractor — 芯片数据手册结构解析与参数提取系统

三级级联流水线：
  Stage 1: MinerU 版面粗筛 + DistilBERT 精修 → 候选标题列表
  Stage 2: Qwen LLM 拓扑推导 → 文档结构树 JSON
  Stage 3: 结构树节点路由 → 主参数提取 & 消歧
"""

__version__ = "0.1.0"
__author__ = "谷君阳"
