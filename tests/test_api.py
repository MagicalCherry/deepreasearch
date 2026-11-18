"""验证评测 API 的健康状态、版本、SSE 和真实网络断开取消；全部使用假 Agent，不调用云模型。"""

import asyncio
import json
import socket

import httpx
import pytest
import uvicorn

from app import api, versions
from app.versions import Version


@pytest.fixture
def client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app), base_url="http://test"
    )


def install_version(monkeypatch, run):
    monkeypatch.setattr(versions, "_VERSIONS", dict(versions._VERSIONS))
    versions.register(Version("test-offline", "测试", "不调用模型", run))


def decode_events(text):
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        lines = block.splitlines()
        names = [line[6:].strip() for line in lines if line.startswith("event:")]
        data = [line[5:].strip() for line in lines if line.startswith("data:")]
        if names and data:
            events.append((names[0], json.loads("\n".join(data))))
    return events


async def test_health_reports_search_down(monkeypatch, client):
    async def search_down():
        return False

    async def llm_ok():
        return True

    monkeypatch.setattr(api, "check_search", search_down)
    monkeypatch.setattr(api, "check_llm", llm_ok)
    async with client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "search": "down", "llm": "ok"}


async def test_versions_include_baselines(client):
    async with client:
        response = await client.get("/api/versions")
    assert response.status_code == 200
    assert {"v0-closedbook", "v0-single"} <= {item["id"] for item in response.json()}


async def test_research_streams_ordered_events(monkeypatch, client):
    async def fake_run(question, trace, options):
        assert question == "虚构问题"
        trace.emit("agent_start", role="搜索与作答", task=question)
        trace.emit("search", query="虚构检索词", k=1, results=[])
        return "Explanation: 测试依据。\nExact Answer: 测试答案\nConfidence: 50%"

    install_version(monkeypatch, fake_run)
    async with client:
        response = await client.post(
            "/api/research", json={"question": "虚构问题", "version": "test-offline"}
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = decode_events(response.text)
    assert [name for name, _ in events] == ["agent_start", "search", "answer", "done"]
    assert all(isinstance(data["t"], (int, float)) and data["agent"] for _, data in events)
    assert events[2][1]["exact_answer"] == "测试答案"


async def test_arrearage_ends_stream_with_error(monkeypatch, client):
    async def fake_run(question, trace, options):
        trace.emit("agent_start", role="测试", task=question)
        raise RuntimeError("arrearage: offline simulated insufficient balance")

    install_version(monkeypatch, fake_run)
    async with client:
        response = await client.post(
            "/api/research", json={"question": "虚构问题", "version": "test-offline"}
        )
    events = decode_events(response.text)
    assert events[-1][0] == "error"
    assert "arrearage" in events[-1][1]["message"].lower()
    assert "done" not in [name for name, _ in events]


async def test_disconnect_cancels_research_over_real_tcp(monkeypatch):
    cancelled = asyncio.Event()

    async def fake_run(question, trace, options):
        trace.emit("agent_start", role="测试", task=question)
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    install_version(monkeypatch, fake_run)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(api.app, log_level="warning", lifespan="off"))
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if serving.done():
                    await serving
                    raise AssertionError("临时测试服务未启动")
                await asyncio.sleep(0.01)
        async with httpx.AsyncClient(timeout=5, trust_env=False) as network_client:
            async with network_client.stream(
                "POST", f"http://127.0.0.1:{port}/api/research",
                json={"question": "取消测试", "version": "test-offline"},
            ) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        assert json.loads(line[5:].strip())["event"] == "agent_start"
                        break
        await asyncio.wait_for(cancelled.wait(), timeout=5)
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(serving, timeout=5)
        finally:
            if not serving.done():
                serving.cancel()
                await asyncio.gather(serving, return_exceptions=True)
            sock.close()
