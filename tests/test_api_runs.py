"""离线验证后台评测接口、先运行后判分、上传题集路径和欠费停止；替换所有收费入口。"""

import asyncio
import json

import httpx
import pytest

from app import api, jobs, runner


@pytest.fixture
def offline_jobs(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(runner, "UPLOADED_DATASET_DIR", tmp_path / "uploaded")
    runner.UPLOADED_DATASET_DIR.mkdir()
    (runner.UPLOADED_DATASET_DIR / "offline-set.jsonl").write_text(json.dumps({
        "query_id": "1", "query": "虚构题面", "answer": "仅供判分的标注",
    }) + "\n", encoding="utf-8")
    return tmp_path


async def test_post_run_returns_before_background_finishes(monkeypatch, offline_jobs):
    started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    async def fake_execute(dataset, version, concurrency, run_id):
        calls.append((dataset, version, concurrency, run_id))
        started.set()
        try:
            await release.wait()
        finally:
            finished.set()

    monkeypatch.setattr(jobs, "execute_run", fake_execute)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app), base_url="http://test"
    ) as client:
        try:
            response = await asyncio.wait_for(client.post("/api/runs", json={
                "dataset": "offline-set", "version": "v0-single", "concurrency": 2,
            }), timeout=2)
            assert response.status_code == 200
            run_id = response.json()["run_id"]
            await asyncio.wait_for(started.wait(), timeout=2)
            assert calls == [("offline-set", "v0-single", 2, run_id)]
            assert not finished.is_set()
        finally:
            release.set()
            if started.is_set():
                await asyncio.wait_for(finished.wait(), timeout=2)


@pytest.mark.parametrize("dataset,version", [
    ("missing", "v0-single"), ("offline-set", "unknown-version"),
])
async def test_invalid_run_never_launches(monkeypatch, offline_jobs, dataset, version):
    async def forbidden(*args):
        pytest.fail("无效请求不应启动后台任务")

    monkeypatch.setattr(jobs, "execute_run", forbidden)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app), base_url="http://test"
    ) as client:
        response = await client.post("/api/runs", json={
            "dataset": dataset, "version": version, "concurrency": 1,
        })
    assert response.status_code == 400


async def test_completed_run_is_judged_with_uploaded_path(monkeypatch, offline_jobs):
    order = []

    async def fake_eval(dataset, version, concurrency, run_id):
        order.append("run")
        directory = runner.RUNS_DIR / run_id
        directory.mkdir(parents=True)
        status = {"status": "completed", "total": 1, "completed": 1, "errors": 0}
        runner.write_json(directory / "status.json", status)
        return status

    async def fake_judge(run_id, dataset_path):
        order.append("judge")
        assert dataset_path == runner.UPLOADED_DATASET_DIR / "offline-set.jsonl"
        status = json.loads((runner.RUNS_DIR / run_id / "status.json").read_text(encoding="utf-8"))
        assert status["status"] == "judging"

    monkeypatch.setattr(runner, "run_eval", fake_eval)
    monkeypatch.setattr(jobs, "judge_run", fake_judge)
    await jobs.execute_run("offline-set", "v0-single", 1, "offline-job")
    assert order == ["run", "judge"]
    status = json.loads((runner.RUNS_DIR / "offline-job" / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "completed"


async def test_stopped_run_does_not_start_judge(monkeypatch, offline_jobs):
    async def fake_eval(*args):
        return {"status": "stopped", "reason": "arrearage"}

    async def forbidden(*args):
        pytest.fail("欠费停批后不应继续请求判分模型")

    monkeypatch.setattr(runner, "run_eval", fake_eval)
    monkeypatch.setattr(jobs, "judge_run", forbidden)
    result = await jobs.execute_run("offline-set", "v0-single", 1, "stopped-job")
    assert result["status"] == "stopped"


async def test_judge_failure_is_recorded(monkeypatch, offline_jobs):
    async def fake_eval(*args):
        directory = runner.RUNS_DIR / "judge-error"
        directory.mkdir(parents=True)
        status = {"status": "completed", "total": 1, "completed": 1, "errors": 0}
        runner.write_json(directory / "status.json", status)
        return status

    async def fake_judge(*args):
        raise RuntimeError("offline judge failed")

    monkeypatch.setattr(runner, "run_eval", fake_eval)
    monkeypatch.setattr(jobs, "judge_run", fake_judge)
    await jobs.execute_run("offline-set", "v0-single", 1, "judge-error")
    status = json.loads((runner.RUNS_DIR / "judge-error" / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "judge_failed"
    assert "offline judge failed" in status["error"]
