"""LLM (大语言模型) 配置：非敏感项读取项目根目录 config.yaml，Key 走环境变量 DASHSCOPE_API_KEY。"""

from .. import settings


class LLMConfig:
    """通义千问 (Qwen) LLM API 配置."""

    # ⚠️ 不要在此硬编码密钥！通过环境变量 DASHSCOPE_API_KEY 提供（见 .env.example）
    api_key: str = settings.llm_api_key()

    model: str = str(settings.get("llm", "model", "qwen-plus"))
    base_url: str = str(settings.get(
        "llm", "base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    temperature: float = float(settings.get("llm", "temperature", 0.7))
    max_tokens: int = int(settings.get("llm", "max_tokens", 4096))
    timeout_sec: int = int(settings.get("llm", "timeout_sec", 120))
