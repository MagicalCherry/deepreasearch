"""用虚构运行文件和假检索服务验证历史列表、逐题对照数据、进程状态与文档转发。"""

import json

import httpx
import pytest

from app import api, runner


@pytest.fixture
async def history_client(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "RUNS_DIR", tmp_path)
    directory = tmp_path / "offline-run"
    directory.mkdir()
    config = {"version": "v0-single", "dataset": "smoke20", "git_sha": "offline-commit"}
    status = {"run_id": "offline-run", "status": "completed", "total": 1, "completed": 1, "errors": 0}
    summary = {"n": 1, "correct": 1, "accuracy": 100.0}
    record = {"query_id": "1", "response": "Explanation: 示例。\nExact Answer: 示例答案\nConfidence: 50%",
              "retrieved_docids": ["offline-doc"], "n_search": 1, "n_read": 1,
              "prompt_tokens": 10, "completion_tokens": 5, "seconds": 1.0,
              "error": None, "stop_reason": "completed",
              "events": [{"event": "done", "t": 1.0, "agent": "agent"}]}
    for filename, value in (("config.json", config), ("status.json", status), ("summary.json", summary)):
        (directory / filename).write_text(json.dumps(value), encoding="utf-8")
    (directory / "results.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    judged = {**record, "judge": {"correct": True, "extracted_final_answer": "示例答案"}}
    (directory / "judged.jsonl").write_text(json.dumps(judged) + "\n", encoding="utf-8")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app), base_url="http://test"
    ) as client:
        yield client, directory, record


async def test_run_list_and_detail_match_frontend_contract(history_client):
    client, directory, record = history_client
    response = await client.get("/api/runs")
    assert response.status_code == 200
    assert len(response.json()) == 1
    info = response.json()[0]
    assert info["run_id"] == "offline-run"
    assert info["status"]["state"] == "completed"
    assert info["status"]["done"] == 1
    assert info["config"]["git_commit"] == "offline-commit"
    assert info["summary"]["accuracy"] == 100.0
    assert (await client.get("/api/runs/offline-run")).json() == info


async def test_item_summary_and_detail_include_judgement(history_client):
    client, directory, record = history_client
    response = await client.get("/api/runs/offline-run/items")
    assert response.status_code == 200
    item = response.json()[0]
    assert item["exact_answer"] == "示例答案"
    assert item["confidence"] == 50
    assert item["correct"] is True
    assert item["query_id"] == "1"
    detail = await client.get("/api/runs/offline-run/items/1")
    assert detail.status_code == 200
    assert detail.json()["events"] == record["events"]
    assert detail.json()["judge"]["correct"] is True


async def test_history_read_does_not_repair_or_modify_results(history_client):
    client, directory, record = history_client
    path = directory / "results.jsonl"
    partial = json.dumps(record).encode() + b'\n{"query_id":'
    path.write_bytes(partial)
    response = await client.get("/api/runs/offline-run/items")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert path.read_bytes() == partial


async def test_dead_process_is_displayed_as_interrupted(monkeypatch, history_client):
    client, directory, record = history_client
    (directory / "status.json").write_text(json.dumps({
        "status": "running", "pid": 12345, "total": 2, "completed": 1, "errors": 0,
    }), encoding="utf-8")
    original = (directory / "status.json").read_bytes()
    monkeypatch.setattr(api, "process_alive", lambda pid: False, raising=False)
    response = await client.get("/api/runs/offline-run")
    assert response.status_code == 200
    assert response.json()["status"]["state"] == "interrupted"
    assert (directory / "status.json").read_bytes() == original


@pytest.mark.parametrize("path", [
    "/api/runs/missing", "/api/runs/missing/items", "/api/runs/offline-run/items/missing",
])
async def test_missing_history_is_404(history_client, path):
    client, directory, record = history_client
    assert (await client.get(path)).status_code == 404


async def test_document_is_forwarded_and_client_closed(monkeypatch, history_client):
    client, directory, record = history_client
    closed = []

    class FakeSearch:
        async def document(self, docid):
            assert docid == "offline-doc"
            return {"docid": docid, "title": "虚构文档", "text": "虚构原文", "url": "https://offline.invalid"}

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(api, "SearchClient", FakeSearch)
    response = await client.get("/api/documents/offline-doc")
    assert response.status_code == 200
    assert response.json()["text"] == "虚构原文"
    assert closed == [True]
