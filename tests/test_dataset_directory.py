"""用虚构题集验证环境变量目录、路径边界和标注隔离，不调用模型或检索服务。"""

import json

import pytest

from app import runner


def write_question(directory, name="custom"):
    directory.mkdir(parents=True, exist_ok=True)
    item = {"query_id": "fake-1", "query": "虚构问题", "answer": "禁止进入研究的标注",
            "gold_docids": ["fake-gold"], "evidence_docids": ["fake-evidence"]}
    (directory / f"{name}.jsonl").write_text(json.dumps(item), encoding="utf-8")
    return item


@pytest.mark.parametrize("name", ["custom", "smoke20", "dev100"])
def test_external_directory_reads_named_dataset_and_strips_labels(tmp_path, monkeypatch, name):
    item = write_question(tmp_path, name)
    monkeypatch.setenv("DATASET_DIR", str(tmp_path))
    assert runner.read_dataset(name) == [item]
    assert runner.load_questions(name) == [{"query_id": "fake-1", "query": "虚构问题"}]


def test_relative_directory_is_relative_to_project(tmp_path, monkeypatch):
    write_question(tmp_path / "external")
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("DATASET_DIR", "external")
    assert runner.load_questions("custom")[0]["query_id"] == "fake-1"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_unconfigured_directory_keeps_existing_locations(tmp_path, monkeypatch, value):
    write_question(tmp_path / "builtin", "smoke20")
    write_question(tmp_path / "uploaded")
    monkeypatch.setattr(runner, "DATASET_DIR", tmp_path / "builtin")
    monkeypatch.setattr(runner, "UPLOADED_DATASET_DIR", tmp_path / "uploaded")
    monkeypatch.delenv("DATASET_DIR", raising=False)
    if value is not None:
        monkeypatch.setenv("DATASET_DIR", value)
    assert runner.load_questions("smoke20")[0]["query_id"] == "fake-1"
    assert runner.load_questions("custom")[0]["query_id"] == "fake-1"


def test_missing_external_file_does_not_fall_back(tmp_path, monkeypatch):
    write_question(tmp_path / "builtin", "smoke20")
    monkeypatch.setattr(runner, "DATASET_DIR", tmp_path / "builtin")
    monkeypatch.setenv("DATASET_DIR", str(tmp_path / "missing"))
    with pytest.raises(FileNotFoundError):
        runner.load_questions("smoke20")


@pytest.mark.parametrize("name", ["../custom", "a/b", "a\\b", "custom.jsonl"])
def test_external_directory_rejects_paths(tmp_path, monkeypatch, name):
    monkeypatch.setenv("DATASET_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        runner.load_questions(name)


def test_external_directory_does_not_redirect_upload_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("DATASET_DIR", str(tmp_path / "external"))
    monkeypatch.setattr(runner, "UPLOADED_DATASET_DIR", tmp_path / "uploaded")
    assert runner.dataset_path("custom") == tmp_path / "uploaded" / "custom.jsonl"


def test_grading_reads_same_external_dataset_with_labels(tmp_path, monkeypatch):
    from scripts import judge_openrouter
    item = write_question(tmp_path)
    monkeypatch.setenv("DATASET_DIR", str(tmp_path))
    assert judge_openrouter.load_grading_dataset("custom") == {"fake-1": item}


def test_grading_default_loader_is_unchanged(monkeypatch):
    from scripts import judge_openrouter
    monkeypatch.delenv("DATASET_DIR", raising=False)
    monkeypatch.setattr(judge_openrouter.judge, "load_dataset", lambda name: {"name": name})
    assert judge_openrouter.load_grading_dataset("dev100") == {"name": "dev100"}
