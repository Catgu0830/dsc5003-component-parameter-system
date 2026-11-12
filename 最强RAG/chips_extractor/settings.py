"""集中配置模块：读取项目根目录 config.yaml，敏感密钥一律走环境变量。

密钥解析优先级：环境变量 (MINERU_API_KEY / DASHSCOPE_API_KEY) > config.yaml > 空字符串。
非敏感参数（base_url、模型版本、路径等）统一从 config.yaml 的 config.* 段读取。
"""

import os
from pathlib import Path

# 项目根目录 = chips_extractor 包的父目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_env_file() -> None:
    """加载项目根目录 .env 文件中的 KEY=VALUE（零依赖、不覆盖已有环境变量）。

    支持 # 注释、引号包裹的值。仅读取 .env，不引入 python-dotenv 依赖。
    """
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # 去掉成对引号
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass


# 先加载 .env，后续密钥解析统一走环境变量优先级
_load_env_file()


def _load_yaml() -> dict:
    """加载 config.yaml 中的 config 段；文件缺失或解析失败时返回空 dict。"""
    cfg_path = PROJECT_ROOT / "config.yaml"
    if not cfg_path.exists():
        return {}
    try:
        import yaml

        with open(cfg_path, "r", encoding="utf-8-sig") as f:
            data = yaml.safe_load(f) or {}
        return data.get("config", data) or {}
    except Exception:
        return {}


_YAML = _load_yaml()


def get(section: str, key: str, default=None):
    """读取非敏感配置项：config.yaml -> config.<section>.<key>。

    支持 ${ENV_VAR} 插值；若插值后仍为未解析的 ${...} 占位符，视为空。
    """
    sec = _YAML.get(section) or {}
    value = sec.get(key, default)
    if isinstance(value, str):
        value = os.path.expandvars(value)
        if value.startswith("${") and value.endswith("}"):
            value = ""
    return value


def api_key(env_var: str, section: str, key: str = "api_key", default: str = "") -> str:
    """按 环境变量 > config.yaml > default 的优先级解析 API Key。"""
    env_value = (os.environ.get(env_var) or "").strip()
    if env_value:
        return env_value
    yaml_value = get(section, key, "") or ""
    return yaml_value or default


def mineru_api_key() -> str:
    """MinerU Token：请通过环境变量 MINERU_API_KEY 提供。"""
    return api_key("MINERU_API_KEY", "mineru")


def llm_api_key() -> str:
    """DashScope/Qwen Key：请通过环境变量 DASHSCOPE_API_KEY 提供。"""
    return api_key("DASHSCOPE_API_KEY", "llm")


def _path(section: str, key: str, default_rel: str) -> Path:
    """解析路径配置：相对路径以项目根目录为基准。"""
    value = get(section, key, None)
    if value:
        p = Path(str(value))
        return p if p.is_absolute() else (PROJECT_ROOT / p)
    return (PROJECT_ROOT / default_rel).resolve()


# ── 项目统一路径（可在 config.yaml -> config.paths 中覆盖）──────────────
DATASETS_DIR = _path("paths", "datasets_dir", "Datasets")
OUTPUT_DIR = _path("paths", "output_dir", "output")
MINERU_OUTPUT_DIR = _path("paths", "mineru_output_dir", "output/mineru_output")
STRUCTURE_TREE_OUTPUT_DIR = _path(
    "paths", "structure_tree_output_dir", "output/structure_tree_output")
LLM_OUTPUT_DIR = _path("paths", "llm_output_dir", "output/llm_output")
PROCESSED_DIR = _path("paths", "processed_dir", "output/processed")
LOGS_DIR = _path("paths", "logs_dir", "output/logs")
