"""用替身模型验证闭卷调用边界、客户端清理和版本登记，不产生云端费用。"""

from types import SimpleNamespace

import pytest

from app.agents import closedbook
from app.trace import Trace
from app.versions import get_version, list_versions


async def test_closedbook_uses_question_without_tools(monkeypatch):
    calls = []
    clients = []

    class FakeLLM:
        def __init__(self, trace):
            self.trace = trace
            self.closed = False
            clients.append(self)

        async def chat(self, **kwargs):
            calls.append(kwargs)
            self.trace.prompt_tokens += 10
            self.trace.completion_tokens += 5
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="Explanation: 示例。\nExact Answer: 示例答案\nConfidence: 50%"
            ))])

        async def close(self):
            self.closed = True

    monkeypatch.setattr(closedbook, "LLM", FakeLLM)
    trace = Trace()
    result = await get_version("v0-closedbook").run("虚构示例问题", trace, {})

    assert "Exact Answer: 示例答案" in result
    assert len(calls) == 1
    assert calls[0]["messages"][1] == {"role": "user", "content": "虚构示例问题"}
    assert "tools" not in calls[0]
    assert trace.n_search == trace.n_read == 0
    assert trace.retrieved == set()
    assert (trace.prompt_tokens, trace.completion_tokens) == (10, 5)
    assert trace.events[0]["event"] == "agent_start"
    assert clients[0].closed


async def test_closedbook_closes_client_on_failure(monkeypatch):
    closed = []

    class FailingLLM:
        def __init__(self, trace):
            pass

        async def chat(self, **kwargs):
            raise RuntimeError("模拟调用失败")

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(closedbook, "LLM", FailingLLM)
    with pytest.raises(RuntimeError, match="模拟调用失败"):
        await closedbook.run("示例问题", Trace(), {})
    assert closed == [True]


def test_version_registry():
    assert list_versions()[0]["id"] == "v0-closedbook"
    with pytest.raises(ValueError, match="未知版本"):
        get_version("missing-version")
