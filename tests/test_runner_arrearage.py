"""验证评测遇欠费立即停批、取消在途任务及原编号续跑；用临时目录和假版本隔离真实数据。"""

import asyncio
import json
import os
from types import SimpleNamespace

import pytest

from app import runner
from app.llm import LLMError


ANSWER = "Explanation: 离线测试。\nExact Answer: 示例\nConfidence: 50%"


@pytest.fixture
def offline_runner(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(runner, "git_sha", lambda: "fixed-offline-commit")
    monkeypatch.setattr(runner, "load_questions", lambda _: [
        {"query_id": str(i), "query": f"问题{i}"} for i in range(1, 5)
    ])

    async def search_config(enabled):
        return {"enabled": enabled, "index": "offline", "parameters": {"k1": 0.9, "b": 0.4}}

    monkeypatch.setattr(runner, "search_config", search_config)
    return tmp_path


async def test_arrearage_stops_pending_and_resumes_same_run(monkeypatch, offline_runner):
    calls = []
    funded = False

    async def fake_run(question, trace, options):
        calls.append(question)
        if question == "问题2" and not funded:
            raise LLMError("arrearage", "Arrearage: offline balance exhausted")
        return ANSWER

    monkeypatch.setattr(runner, "get_version", lambda _: SimpleNamespace(run=fake_run, options={}))
    first = await runner.run_eval("smoke20", "offline", 1, "arrearage-test")
    assert first["status"] == "stopped"
    assert first["reason"] == "arrearage"
    assert first["pid"] == os.getpid()
    assert (first["completed"], first["errors"]) == (1, 1)
    assert calls == ["问题1", "问题2"]
    directory = offline_runner / "arrearage-test"
    assert json.loads((directory / "status.json").read_text(encoding="utf-8")) == first
    records = runner.load_results(directory / "results.jsonl")
    assert set(records) == {"1", "2"}
    assert "Arrearage: offline balance exhausted" in records["2"]["error"]
    assert records["2"]["stop_reason"] == "arrearage"
    assert not (directory / ".running.lock").exists()

    funded = True
    second = await runner.run_eval("smoke20", "offline", 1, "arrearage-test")
    assert second["status"] == "completed"
    assert (second["completed"], second["errors"]) == (4, 0)
    assert second.get("reason") != "arrearage"
    assert calls == ["问题1", "问题2", "问题2", "问题3", "问题4"]


async def test_arrearage_cancels_inflight_research(monkeypatch, offline_runner):
    started = asyncio.Event()
    cancelled = asyncio.Event()
    calls = []

    async def fake_run(question, trace, options):
        calls.append(question)
        if question == "问题1":
            await started.wait()
            raise LLMError("arrearage", "Arrearage: offline")
        if question == "问题2":
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
        pytest.fail("欠费后不应启动排队题目")

    monkeypatch.setattr(runner, "get_version", lambda _: SimpleNamespace(run=fake_run, options={}))
    status = await asyncio.wait_for(
        runner.run_eval("smoke20", "offline", 2, "cancel-test"), timeout=3,
    )
    assert status["status"] == "stopped"
    assert status["reason"] == "arrearage"
    assert cancelled.is_set()
    assert calls == ["问题1", "问题2"]
    assert status["completed"] == 0
    assert status["errors"] >= 1
    assert not (offline_runner / "cancel-test" / ".running.lock").exists()
