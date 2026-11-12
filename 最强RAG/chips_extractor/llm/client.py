"""LLM (大语言模型) 客户端：调用通义千问 Qwen API."""

from openai import OpenAI

from .config import LLMConfig
from .models import LLMResponse


class LLMClient:
    """通过 OpenAI 兼容接口调用 DashScope / 其他 LLM API."""

    def __init__(self, cfg=None):
        self.cfg = cfg or LLMConfig()
        self.client = OpenAI(
            api_key=self.cfg.api_key,
            base_url=self.cfg.base_url,
            timeout=self.cfg.timeout_sec,
        )

    # --- Public ---
    def chat(self, messages: list[dict]) -> LLMResponse:
        """发起一轮对话，返回文本结果或错误信息."""
        try:
            resp = self.client.chat.completions.create(
                model=self.cfg.model,
                messages=messages,
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
            )
            choice = resp.choices[0]
            result = LLMResponse(
                success=True,
                text=choice.message.content if choice.message else "",
                model=resp.model,
                prompt_tokens=resp.usage.prompt_tokens if resp.usage else 0,
                completion_tokens=resp.usage.completion_tokens if resp.usage else 0,
                total_tokens=resp.usage.total_tokens if resp.usage else 0,
            )
            return result

        except Exception as e:
            return LLMResponse(
                success=False, error_msg=str(e))
