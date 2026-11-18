"""封装百炼及OpenRouter异步对话、四类云端错误、有限重试和token统计。"""

import asyncio
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from app.config import settings
from app.trace import Trace


class LLMError(RuntimeError):
    """保留错误类别与原始消息，供事件流和运行器决定是否停止或重试。"""

    def __init__(self, kind: str, message: str) -> None:
        if kind not in {"arrearage", "content_filter", "timeout", "other"}:
            raise ValueError(f"未知模型错误类别：{kind}")
        self.kind = kind
        self.message = message
        super().__init__(f"{kind}: {message}")


def classify_error(exc: Exception) -> LLMError:
    """统一 SDK 错误；兼容百炼欠费标识及 OpenRouter 的余额不足响应。"""
    if isinstance(exc, LLMError):
        return exc
    message = str(exc)
    lowered = message.lower()
    if "arrearage" in lowered or (
        isinstance(exc, APIStatusError) and exc.status_code == 402
    ):
        kind = "arrearage"
    elif "datainspectionfailed" in lowered or "inappropriate content" in lowered:
        kind = "content_filter"
    elif isinstance(exc, (APITimeoutError, TimeoutError)):
        kind = "timeout"
    else:
        kind = "other"
    return LLMError(kind, message)


class LLM:
    """调用当前平台的聊天接口，并累计 prompt 与 completion token。"""

    def __init__(self, trace: Trace | None = None) -> None:
        self.trace = trace
        if not settings.api_key:
            key_name = "OPENROUTER_API_KEY" if settings.provider == "openrouter" else "DASHSCOPE_API_KEY"
            raise ValueError(f"缺少{key_name}，请在对应平台的本地配置中填写。")

        self.client = AsyncOpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            max_retries=0,
        )
        self.prompt_tokens = 0
        self.completion_tokens = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        truncate: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
        **kwargs: Any,
    ) -> Any:
        """最多请求三次；欠费立即抛出，审核仅在提供截短回调时重试。"""
        request: dict[str, Any] = {
            "model": settings.model,
            "messages": deepcopy(messages),
            "max_tokens": settings.max_tokens,
            "extra_body": ({"reasoning": {"enabled": False}}
                           if settings.provider == "openrouter" else {"enable_thinking": False}),
            **kwargs,
        }
        # 旧版本显式传入更大上限时也不能超过当前模型支持值；S4的16000保持不变。
        request["max_tokens"] = min(request["max_tokens"], settings.max_tokens)

        if tools is not None:
            request["tools"] = tools
        if json_mode:
            request["response_format"] = {"type": "json_object"}

        for attempt in range(3):
            try:
                response = await self.client.chat.completions.create(**request)
                if response.usage:
                    self.prompt_tokens += response.usage.prompt_tokens or 0
                    self.completion_tokens += response.usage.completion_tokens or 0
                    if self.trace is not None:
                        self.trace.prompt_tokens += response.usage.prompt_tokens or 0
                        self.trace.completion_tokens += response.usage.completion_tokens or 0
                return response
            except (APIConnectionError, APIStatusError, TimeoutError, LLMError) as exc:
                error = classify_error(exc)
                if error.kind == "arrearage" or attempt == 2:
                    raise error from exc
                if error.kind == "content_filter":
                    if truncate is None:
                        raise error from exc
                    request["messages"] = deepcopy(truncate(deepcopy(request["messages"])))
                    continue
                await asyncio.sleep(2**attempt)

        raise RuntimeError("模型请求重试失败")

    async def close(self) -> None:
        """关闭异步 HTTP 客户端。"""
        await self.client.close()
