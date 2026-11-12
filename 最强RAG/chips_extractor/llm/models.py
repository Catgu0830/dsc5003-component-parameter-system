"""LLM 响应结果的数据模型."""

from dataclasses import dataclass, field


@dataclass
class Message:
    """聊天消息."""

    role: str = "user"  # user / assistant / system
    content: str = ""


@dataclass
class LLMResponse:
    """LLM API 调用结果封装."""

    success: bool = True
    text: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    error_msg: str = ""
