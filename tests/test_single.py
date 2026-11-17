"""验证单Agent的官方提示词填充、默认工具预算及客户端清理，不调用云服务。"""

from app.agents import single
from app.trace import Trace
from app.versions import get_version


async def test_single_wires_official_prompt_and_closes_clients(monkeypatch):
    closed = []

    class FakeLLM:
        def __init__(self, trace):
            self.trace = trace

        async def close(self):
            closed.append("llm")

    class FakeSearch:
        async def close(self):
            closed.append("search")

    async def fake_loop(llm, messages, tools, max_tool_calls, max_turns):
        assert messages == [{"role": "user", "content": single.QUERY_TEMPLATE.format(Question="虚构问题")}]
        assert (tools.k, tools.snippet_tokens, tools.document_tokens) == (5, 512, 8000)
        assert max_tool_calls == 30
        assert max_turns == 40
        return "Explanation: 示例。\nExact Answer: 示例答案\nConfidence: 20%"

    monkeypatch.setattr(single, "LLM", FakeLLM)
    monkeypatch.setattr(single, "SearchClient", FakeSearch)
    monkeypatch.setattr(single, "react_loop", fake_loop)
    trace = Trace()
    version = get_version("v0-single")
    result = await version.run("虚构问题", trace, version.options)
    assert "Exact Answer: 示例答案" in result
    assert trace.events[0]["event"] == "agent_start"
    assert closed == ["search", "llm"]
