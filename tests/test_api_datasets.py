"""验证题集接口的上传删除、内置保护和运行器标注隔离；仅使用临时目录中的虚构题目。"""

import json

import httpx
import pytest

from app import api, runner


@pytest.fixture
async def dataset_client(monkeypatch, tmp_path):
    builtin = tmp_path / "builtin"
    uploaded = tmp_path / "uploaded"
    builtin.mkdir()
    for name in ("smoke20", "dev100"):
        (builtin / f"{name}.jsonl").write_text(json.dumps({
            "query_id": "1", "query": "虚构题面", "answer": "虚构标注",
            "evidence_docids": ["offline-evidence"],
        }) + "\n", encoding="utf-8")
    monkeypatch.setattr(runner, "DATASET_DIR", builtin)
    monkeypatch.setattr(runner, "UPLOADED_DATASET_DIR", uploaded, raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app), base_url="http://test"
    ) as client:
        yield client, builtin, uploaded


async def test_builtin_listing_and_protection(dataset_client):
    client, builtin, uploaded = dataset_client
    original = (builtin / "smoke20.jsonl").read_bytes()
    response = await client.get("/api/datasets")
    assert response.status_code == 200
    assert {item["name"] for item in response.json()} == {"smoke20", "dev100"}
    assert all(item["source"] == "builtin" and item["has_evidence"] for item in response.json())
    assert (await client.delete("/api/datasets/smoke20")).status_code == 404
    response = await client.post("/api/datasets", json={
        "name": "smoke20", "items": [{"query": "替换题面", "answer": "替换答案"}],
    })
    assert response.status_code == 400
    assert (builtin / "smoke20.jsonl").read_bytes() == original


async def test_upload_read_isolation_and_delete(dataset_client):
    client, builtin, uploaded = dataset_client
    response = await client.post("/api/datasets", json={
        "name": "my-set", "items": [{"query": "离线题面", "answer": "仅给评测的标注"}],
    })
    assert response.status_code == 200
    assert response.json() == {"name": "my-set", "n": 1, "source": "uploaded", "has_evidence": False}
    assert (uploaded / "my-set.jsonl").exists()
    assert not (builtin / "my-set.jsonl").exists()
    response = await client.get("/api/datasets/my-set")
    assert response.status_code == 200
    items = response.json()
    assert items[0]["answer"] == "仅给评测的标注"
    assert str(items[0]["query_id"])
    # 页面评测接口可读标注；Agent 的数据加载边界必须剥离标注。
    assert runner.load_questions("my-set") == [
        {"query_id": str(items[0]["query_id"]), "query": "离线题面"}
    ]
    assert (await client.delete("/api/datasets/my-set")).json() == {"ok": True}
    assert not (uploaded / "my-set.jsonl").exists()
    assert (await client.get("/api/datasets/my-set")).status_code == 404


@pytest.mark.parametrize("body", [
    {"name": "../escape", "items": [{"query": "题", "answer": "答"}]},
    {"name": "bad name", "items": [{"query": "题", "answer": "答"}]},
    {"name": "missing-query", "items": [{"answer": "答"}]},
    {"name": "missing-answer", "items": [{"query": "题"}]},
    {"name": "blank", "items": [{"query": "  ", "answer": "答"}]},
    {"name": "empty", "items": []},
    {"name": "duplicate-ids", "items": [
        {"query_id": "1", "query": "题一", "answer": "答"},
        {"query_id": "1", "query": "题二", "answer": "答"},
    ]},
])
async def test_invalid_upload_is_400_without_writing(dataset_client, body):
    client, builtin, uploaded = dataset_client
    response = await client.post("/api/datasets", json=body)
    assert response.status_code == 400
    assert not uploaded.exists() or not list(uploaded.iterdir())


async def test_uploaded_evidence_stays_out_of_agent_questions(dataset_client):
    client, builtin, uploaded = dataset_client
    response = await client.post("/api/datasets", json={
        "name": "with-evidence", "items": [{
            "query_id": "example-1", "query": "虚构检索问题", "answer": "标注答案",
            "gold_docids": ["offline-gold"], "evidence_docids": ["offline-evidence"],
        }],
    })
    assert response.status_code == 200
    assert response.json()["has_evidence"] is True
    assert runner.load_questions("with-evidence") == [
        {"query_id": "example-1", "query": "虚构检索问题"}
    ]
