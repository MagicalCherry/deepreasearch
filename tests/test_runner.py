"""用虚构题目验证研究事件、错误保留、标注隔离和评测续跑，不调用云服务。"""

import json
from types import SimpleNamespace

import pytest

from app import runner
from app.trace import Trace


async def test_research_normalizes_and_emits(monkeypatch):
    async def fake_run(question, trace, opts):
        assert question == "示例问题"
        trace.emit("agent_start", role="作答", task=question)
        return "Explanation: 示例。\nExact Answer: 示例答案"

    monkeypatch.setattr(runner, "get_version", lambda _: SimpleNamespace(run=fake_run, options={}))
    trace = Trace()
    response = await runner.research("示例问题", "fake", trace)
    assert response.endswith("Confidence: 50%")
    assert [event["event"] for event in trace.events] == ["agent_start", "answer", "done"]
    assert trace.stop_reason == "completed"


async def test_research_preserves_errors(monkeypatch):
    async def fake_run(question, trace, opts):
        raise RuntimeError("模拟服务异常")

    monkeypatch.setattr(runner, "get_version", lambda _: SimpleNamespace(run=fake_run, options={}))
    trace = Trace()
    with pytest.raises(RuntimeError, match="模拟服务异常"):
        await runner.research("示例问题", "fake", trace)
    assert trace.events[-1]["event"] == "error"
    assert "模拟服务异常" in trace.events[-1]["message"]
    assert trace.stop_reason == "error"


def test_dataset_boundary_discards_labels(tmp_path, monkeypatch):
    fake = {"query_id": 1, "query": "虚构问题", "answer": "测试标注",
            "gold_docids": ["999"], "evidence_docids": ["888"]}
    (tmp_path / "smoke20.jsonl").write_text(json.dumps(fake), encoding="utf-8")
    monkeypatch.setattr(runner, "DATASET_DIR", tmp_path)
    assert runner.load_questions("smoke20") == [{"query_id": "1", "query": "虚构问题"}]


async def test_eval_resumes_success_and_retries_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(runner, "git_sha", lambda: "test-commit")
    monkeypatch.setattr(runner, "load_questions", lambda _: [
        {"query_id": "1", "query": "问题一"}, {"query_id": "2", "query": "问题二"},
    ])
    calls = []

    async def fake_run(question, trace, opts):
        calls.append(question)
        if question == "问题二" and calls.count(question) == 1:
            raise RuntimeError("首次模拟失败")
        return "Explanation: 示例。\nExact Answer: 答案\nConfidence: 20%"

    monkeypatch.setattr(runner, "get_version", lambda _: SimpleNamespace(run=fake_run, options={}))
    first = await runner.run_eval("smoke20", "fake", 1, "test-run")
    assert (first["completed"], first["errors"]) == (1, 1)
    second = await runner.run_eval("smoke20", "fake", 1, "test-run")
    assert second["status"] == "completed"
    assert (second["completed"], second["errors"]) == (2, 0)
    assert calls == ["问题一", "问题二", "问题二"]
    records = runner.load_results(tmp_path / "test-run" / "results.jsonl")
    assert records["2"]["error"] is None
    assert records["1"]["events"][-1]["event"] == "done"
    config = json.loads((tmp_path / "test-run" / "config.json").read_text(encoding="utf-8"))
    assert config["git_sha"] == "test-commit"
    monkeypatch.setattr(runner, "git_sha", lambda: "different-commit")
    with pytest.raises(ValueError, match="续跑配置或代码提交已改变"):
        await runner.run_eval("smoke20", "fake", 1, "test-run")


def test_resume_repairs_incomplete_last_line(tmp_path):
    path = tmp_path / "results.jsonl"
    path.write_bytes(b'{"query_id":"1","error":null}\n{"query_id":')
    assert list(runner.load_results(path)) == ["1"]
    assert path.read_bytes() == b'{"query_id":"1","error":null}\n'
