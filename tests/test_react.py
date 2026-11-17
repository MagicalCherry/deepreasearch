"""用剧本模型和假检索验证ReAct工具事件、文档记录及预算耗尽后的收尾调用。"""

import json
from types import SimpleNamespace

from app.agents.react import Tools, react_loop
from app.trace import Trace


class FakeSearch:
    """只返回虚构文档的检索替身，不访问真实服务或评测标注。"""

    async def search(self, q, k=5):
        return {"results": [{"docid": "12", "title": "示例文档", "score": 1.2,
                             "snippet": "示例片段"}]}


class ScriptedLLM:
    """前若干轮请求搜索；收回工具或达到剧本轮次后返回答案。"""

    def __init__(self, search_turns):
        self.search_turns = search_turns
        self.requests = []

    async def chat(self, messages, **kwargs):
        self.requests.append({"messages": list(messages), **kwargs})
        turn = len(self.requests)
        if kwargs.get("tools") and turn <= self.search_turns:
            message = SimpleNamespace(
                role="assistant", content=None,
                tool_calls=[SimpleNamespace(
                    id=f"call-{turn}", type="function",
                    function=SimpleNamespace(name="search", arguments=json.dumps({"query": "虚构搜索"})),
                )],
            )
        else:
            message = SimpleNamespace(role="assistant", tool_calls=None,
                content="Explanation: 示例。\nExact Answer: 示例答案\nConfidence: 20%")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


async def test_react_records_searches_and_returns_answer():
    trace = Trace()
    tools = Tools(search=FakeSearch(), trace=trace, k=5)
    llm = ScriptedLLM(search_turns=2)
    response = await react_loop(llm, [{"role": "user", "content": "虚构问题"}],
                                tools, max_tool_calls=3, max_turns=5)

    assert "Exact Answer: 示例答案" in response
    assert trace.n_search == 2
    assert trace.retrieved == {"12"}
    searches = [event for event in trace.events if event["event"] == "search"]
    assert len(searches) == 2
    assert all({"docid", "title", "score"} <= result.keys()
               for event in searches for result in event["results"])
    tool_messages = [message for message in llm.requests[-1]["messages"] if message["role"] == "tool"]
    assert len(tool_messages) == 2
    assert tool_messages[0]["tool_call_id"] == "call-1"


async def test_react_withdraws_tools_after_three_calls():
    trace = Trace()
    tools = Tools(search=FakeSearch(), trace=trace, k=5)
    llm = ScriptedLLM(search_turns=20)
    response = await react_loop(llm, [{"role": "user", "content": "虚构问题"}],
                                tools, max_tool_calls=3, max_turns=10)

    assert trace.n_search == 3
    assert len(llm.requests) == 4
    assert all(request.get("tools") for request in llm.requests[:3])
    assert not llm.requests[3].get("tools")
    assert "Exact Answer:" in response
