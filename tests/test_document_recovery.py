"""用虚构模型和检索响应验证文档404纠正、预算约束及其他错误的保留，不调用云服务。"""

import json
from types import SimpleNamespace

import httpx
import pytest

from app.agents.react import Tools, react_loop
from app.trace import Trace


class DocumentService:
    """编号12存在；其他编号模拟指定HTTP错误。"""

    def __init__(self, status=404):
        self.status = status
        self.calls = []

    async def document(self, docid, max_tokens=None):
        self.calls.append(docid)
        if docid == "12":
            return {"docid": "12", "url": "https://example.org/12",
                    "title": "虚构文档", "text": "虚构正文"}
        request = httpx.Request("GET", "http://example.test/document/missing")
        response = httpx.Response(self.status, request=request)
        response.raise_for_status()


class CorrectingModel:
    """第一次传标题，看到真实404后改用编号，最后作答。"""

    def __init__(self):
        self.requests = []

    async def chat(self, messages, **kwargs):
        self.requests.append({"messages": list(messages), **kwargs})
        turn = len(self.requests)
        if turn == 2:
            tool_reply = next(m for m in reversed(messages) if m["role"] == "tool")
            result = json.loads(tool_reply["content"])
            assert result["error"] == "document_not_found"
            assert result["status_code"] == 404
            assert "text" not in result
        if turn < 3 and kwargs.get("tools"):
            docid = "虚构标题" if turn == 1 else "12"
            message = SimpleNamespace(content=None, tool_calls=[SimpleNamespace(
                id=f"call-{turn}", function=SimpleNamespace(
                    name="get_document", arguments=json.dumps({"docid": docid})))])
        else:
            message = SimpleNamespace(tool_calls=None, content=(
                "Explanation: 虚构测试。[12]\nExact Answer: 示例\nConfidence: 10%"))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


async def test_404_is_returned_to_model_and_corrected():
    trace = Trace()
    service = DocumentService()
    model = CorrectingModel()
    result = await react_loop(model, [{"role": "user", "content": "虚构问题"}],
                              Tools(service, trace, recover_document_404=True),
                              max_tool_calls=3)
    assert "Exact Answer: 示例" in result
    assert service.calls == ["虚构标题", "12"]
    assert trace.n_read == 1
    assert trace.retrieved == {"12"}
    assert [e["event"] for e in trace.events] == ["read"]


async def test_failed_document_call_consumes_budget():
    trace = Trace()
    service = DocumentService()
    model = CorrectingModel()
    await react_loop(model, [{"role": "user", "content": "虚构问题"}],
                     Tools(service, trace, recover_document_404=True), max_tool_calls=1)
    assert service.calls == ["虚构标题"]
    assert trace.n_read == 0
    assert trace.stop_reason == "tool_budget"
    assert "tools" not in model.requests[-1]


@pytest.mark.parametrize("status,recover", [(404, False), (400, True), (403, True), (500, True)])
async def test_baseline_and_other_http_errors_still_raise(status, recover):
    trace = Trace()
    tools = Tools(DocumentService(status), trace, recover_document_404=recover)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        await tools.call("get_document", {"docid": "missing"})
    assert caught.value.response.status_code == status
    assert trace.n_read == 0
    assert not trace.retrieved
