"""封装百炼 OpenAI 兼容接口的异步对话、重试和 token 用量统计。"""

import asyncio
from typing import Any

from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError

from app.config import settings


class LLM:
    """异步调用百炼聊天接口，并累计 prompt 与 completion token。"""

    def __init__(self) -> None:
        if not settings.api_key:
            raise ValueError("缺少 DASHSCOPE_API_KEY，请在本地 .env 中配置。")

        self.client = AsyncOpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            max_retries=0,
        )
        self.prompt_tokens = 0
        self.completion_tokens = 0

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> Any:
        """发送聊天请求；网络或限流错误按指数间隔重试。"""
        request: dict[str, Any] = {
            "model": settings.model,
            "messages": messages,
            "max_tokens": settings.max_tokens,
            "extra_body": {"enable_thinking": False},
            **kwargs,
        }

        if tools is not None:
            request["tools"] = tools
        if json_mode:
            request["response_format"] = {"type": "json_object"}

        for attempt in range(3): #请求最多3次
            try:
                response = await self.client.chat.completions.create(**request)
                if response.usage:
                    self.prompt_tokens += response.usage.prompt_tokens or 0
                    self.completion_tokens += response.usage.completion_tokens or 0
                return response
            except (APIConnectionError, RateLimitError):
                if attempt == 2:
                    raise
                await asyncio.sleep(2**attempt)
            except APIStatusError as exc:
                if exc.status_code < 500 or attempt == 2:
                    raise
                await asyncio.sleep(2**attempt)

        raise RuntimeError("百炼请求重试失败")

    async def close(self) -> None:
        """关闭异步 HTTP 客户端。"""
        await self.client.close()