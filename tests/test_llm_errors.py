"""用假 SDK 请求验证云端错误分类、重试上限、截短回调和取消传播，不访问网络。"""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError, APITimeoutError

from app import llm
from app.llm import LLMError


def status_error(status, message):
    response = httpx.Response(status, request=httpx.Request("POST", "https://offline.invalid"))
    return APIStatusError(message, response=response, body={"message": message})


@pytest.fixture
def fake_model(monkeypatch):
    calls, delays = [], []
    outcomes = []

    async def create(**kwargs):
        calls.append(deepcopy(kwargs))
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def sleep(seconds):
        delays.append(seconds)

    async def close():
        pass

    monkeypatch.setattr(llm, "settings", SimpleNamespace(
        api_key="offline-placeholder", base_url="https://offline.invalid",
        provider="openrouter", model="offline-test", max_tokens=100,
    ))
    monkeypatch.setattr(llm, "AsyncOpenAI", lambda **kwargs: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=close,
    ))
    monkeypatch.setattr(llm.asyncio, "sleep", sleep)
    return llm.LLM(), outcomes, calls, delays


@pytest.mark.parametrize("status,message", [
    (400, "Arrearage: account balance exhausted"),
    (402, "Insufficient credits"),
])
async def test_arrearage_is_not_retried(fake_model, status, message):
    model, outcomes, calls, delays = fake_model
    outcomes.append(status_error(status, message))
    with pytest.raises(LLMError) as error:
        await model.chat([{"role": "user", "content": "测试"}])
    assert error.value.kind == "arrearage"
    assert message in str(error.value)
    assert len(calls) == 1
    assert delays == []


async def test_content_filter_without_callback_is_not_retried(fake_model):
    model, outcomes, calls, delays = fake_model
    outcomes.append(status_error(400, "DataInspectionFailed: inappropriate content"))
    with pytest.raises(LLMError) as error:
        await model.chat([{"role": "user", "content": "虚构长文本"}])
    assert error.value.kind == "content_filter"
    assert len(calls) == 1


async def test_content_filter_truncates_at_most_twice(fake_model):
    model, outcomes, calls, delays = fake_model
    outcomes.extend(status_error(400, "DataInspectionFailed") for _ in range(3))
    original = [{"role": "user", "content": "abcdefgh"}]
    shortened = []

    def truncate(messages):
        shortened.append(deepcopy(messages))
        return [{"role": "user", "content": messages[0]["content"][:len(messages[0]["content"]) // 2]}]

    with pytest.raises(LLMError) as error:
        await model.chat(original, truncate=truncate)
    assert error.value.kind == "content_filter"
    assert len(shortened) == 2
    assert [call["messages"][0]["content"] for call in calls] == ["abcdefgh", "abcd", "ab"]
    assert all("truncate" not in call for call in calls)
    assert original == [{"role": "user", "content": "abcdefgh"}]


@pytest.mark.parametrize("kind", ["timeout", "other"])
async def test_transient_error_has_three_attempt_limit(fake_model, kind):
    model, outcomes, calls, delays = fake_model
    for _ in range(3):
        outcomes.append(
            APITimeoutError(request=httpx.Request("POST", "https://offline.invalid"))
            if kind == "timeout" else status_error(503, "upstream unavailable")
        )
    with pytest.raises(LLMError) as error:
        await model.chat([{"role": "user", "content": "测试"}])
    assert error.value.kind == kind
    assert len(calls) == 3
    assert delays == [1, 2]


async def test_cancellation_is_not_wrapped_or_retried(fake_model):
    model, outcomes, calls, delays = fake_model
    outcomes.append(asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await model.chat([{"role": "user", "content": "测试"}])
    assert len(calls) == 1
    assert delays == []
