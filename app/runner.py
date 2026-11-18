"""组织单题研究和批量评测，隔离题集标注，保存配置、逐题结果及续跑状态。"""

import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from app.answer import normalize, parse
from app.config import PROJECT_ROOT, settings
from app.llm import LLMError
from app.search import SearchClient
from app.trace import Trace
from app.versions import get_version


DATASET_DIR = PROJECT_ROOT.parent / "MAS实操课程" / "01-项目任务书" / "验收题集"
RUNS_DIR = PROJECT_ROOT / "runs"
UPLOADED_DATASET_DIR = PROJECT_ROOT / "data" / "uploaded_datasets"
BUILTIN_DATASETS = ("smoke20", "dev100")


def dataset_path(dataset: str) -> Path:
    """只解析允许的题集名；内置题集固定白名单，其他题集仅从上传目录读取。"""
    if not isinstance(dataset, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", dataset):
        raise ValueError("题集名只能包含字母、数字、下划线和短横线")
    directory = DATASET_DIR if dataset in BUILTIN_DATASETS else UPLOADED_DATASET_DIR
    path = directory / f"{dataset}.jsonl"
    if path.resolve().parent != directory.resolve():
        raise ValueError("题集路径超出指定目录")
    return path


def read_dataset(dataset: str) -> list[dict]:
    """读取完整评测标注，仅供题集页面和评测代码；Agent 使用 load_questions。"""
    return [json.loads(line) for line in dataset_path(dataset).read_text(
        encoding="utf-8-sig"
    ).splitlines() if line.strip()]


async def search_config(enabled: bool) -> dict:
    """从服务健康接口读取索引快照；记录配置不等于向模型提供检索工具。"""
    client = SearchClient()
    try:
        health = await client.health()
    finally:
        await client.close()
    name = health["default_index"]
    index = next((item for item in health["indexes"] if item["name"] == name), None)
    if health.get("status") != "ok" or index is None or index.get("status") != "ready":
        raise ValueError("默认检索索引未就绪，无法保存评测配置")
    return {
        "enabled": enabled, "url": settings.search_url,
        "index": name,
        "parameters": {key: index[key] for key in ("k1", "b", "unit")},
        "docs": health["docs"],
    }


def load_questions(dataset: str) -> list[dict[str, str]]:
    """只保留编号与题面，标注字段不离开数据加载边界。"""
    questions = [{"query_id": str(item["query_id"]), "query": item["query"]}
                 for item in read_dataset(dataset)]
    if len({item["query_id"] for item in questions}) != len(questions):
        raise ValueError("题集中存在重复编号")
    return questions


def git_sha() -> str:
    """记录代码提交号，不读取仓库配置或环境文件。"""
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True,
    ).strip()


def write_json(path: Path, value: Any) -> None:
    """先写临时文件再替换，防止中断留下半份状态或配置。"""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


async def research(question: str, version: str, trace: Trace, opts: dict | None = None) -> str:
    """执行指定版本，统一输出答案与结束事件，保留并上抛运行错误。"""
    try:
        registered = get_version(version)
        options = deepcopy(registered.options)
        options.update(deepcopy(opts or {}))
        async with asyncio.timeout(600):
            response = normalize(await registered.run(question, trace, options))
        trace.emit("answer", **parse(response))
        trace.stop_reason = trace.stop_reason or "completed"
        trace.emit(
            "done", usage={"prompt_tokens": trace.prompt_tokens, "completion_tokens": trace.completion_tokens},
            seconds=trace.seconds, n_search=trace.n_search, n_read=trace.n_read,
        )
        return response
    except asyncio.CancelledError:
        trace.stop_reason = "cancelled"
        trace.emit("error", message="研究已取消")
        raise
    except Exception as exc:
        trace.stop_reason = (exc.kind if isinstance(exc, LLMError)
                             else "timeout" if isinstance(exc, TimeoutError) else "error")
        trace.emit("error", message=f"{type(exc).__name__}: {exc}")
        raise


def load_results(path: Path) -> dict[str, dict]:
    """同一编号取最后一次尝试；仅修复中断造成的末行不完整记录。"""
    records = {}
    if not path.exists():
        return records
    with path.open("r+b") as stream:
        while True:
            offset = stream.tell()
            line = stream.readline()
            if not line:
                break
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                if not line.endswith(b"\n") and not stream.read(1):
                    stream.truncate(offset)
                    break
                raise ValueError("results.jsonl 存在损坏的完整行，请先检查记录") from None
            records[str(record["query_id"])] = record
        # 合法的末行也可能缺换行，避免续写时两条记录黏连。
        stream.seek(0, 2)
        if stream.tell():
            stream.seek(-1, 2)
            if stream.read(1) != b"\n":
                stream.write(b"\n")
    return records


async def run_eval(dataset: str, version: str, concurrency: int, run_id: str) -> dict:
    """受限并发评测：完成即落盘，续跑跳过成功题并重试错误题。"""
    if concurrency < 1:
        raise ValueError("并发数必须大于0")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("run_id 只能包含字母、数字、下划线和短横线")
    registered = get_version(version)
    questions = load_questions(dataset)
    config = {
        "version": version, "model": settings.model, "dataset": dataset,
        "llm_provider": settings.provider, "llm_base_url": settings.base_url,
        "concurrency": concurrency, "options": deepcopy(registered.options),
        "git_sha": git_sha(), "max_tokens": settings.max_tokens,
        "budget": {"seconds": 600, "n_search": 50},
        "search": await search_config(enabled=version != "v0-closedbook"),
        "questions_sha256": hashlib.sha256(json.dumps(questions, sort_keys=True).encode()).hexdigest(),
    }
    directory = RUNS_DIR / run_id
    directory.mkdir(parents=True, exist_ok=True)
    # 排他锁避免同一次运行被两个进程同时追加。
    lock_path = directory / ".running.lock"
    try:
        lock = lock_path.open("x")
    except FileExistsError:
        raise ValueError("该运行已被锁定；确认旧进程已退出后再移除 .running.lock") from None
    try:
        config_path = directory / "config.json"
        if config_path.exists():
            if json.loads(config_path.read_text(encoding="utf-8")) != config:
                raise ValueError("续跑配置或代码提交已改变，请使用新的 run_id")
        else:
            write_json(config_path, config)
        results_path = directory / "results.jsonl"
        records = load_results(results_path)
        expected = {item["query_id"] for item in questions}
        stop_reason: str | None = None
        tasks: list[asyncio.Task] = []

        def save_status(state: str) -> dict:
            selected = [item for key, item in records.items() if key in expected]
            status = {
                "run_id": run_id, "status": state, "total": len(questions),
                "pid": os.getpid(),
                "completed": sum(item.get("error") is None for item in selected),
                "errors": sum(item.get("error") is not None for item in selected),
            }
            if stop_reason is not None:
                status["reason"] = stop_reason
            write_json(directory / "status.json", status)
            return status

        semaphore = asyncio.Semaphore(concurrency)

        async def run_one(item: dict) -> None:
            nonlocal stop_reason
            async with semaphore:
                # 必须在获得并发位置后再检查，避免欠费后启动排队题目。
                if stop_reason is not None:
                    return
                trace = Trace()
                response, error = "", None
                try:
                    response = await research(item["query"], version, trace)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    if isinstance(exc, LLMError) and exc.kind == "arrearage":
                        # 在释放 semaphore 前封住入口，并通知在途任务取消。
                        stop_reason = "arrearage"
                        current = asyncio.current_task()
                        for task in tasks:
                            if task is not current and not task.done():
                                task.cancel()
                record = {
                    "query_id": item["query_id"], "response": response,
                    "retrieved_docids": sorted(trace.retrieved),
                    "n_search": trace.n_search, "n_read": trace.n_read,
                    "prompt_tokens": trace.prompt_tokens, "completion_tokens": trace.completion_tokens,
                    "seconds": trace.seconds, "error": error,
                    "events": trace.events, "stop_reason": trace.stop_reason,
                }
                with results_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                    stream.flush()
                records[item["query_id"]] = record
                status = save_status("stopped" if stop_reason else "running")
                print(f"完成 {status['completed']}/{status['total']}，运行错误 {status['errors']}", flush=True)

        pending = [item for item in questions if item["query_id"] not in records
                   or records[item["query_id"]].get("error") is not None]
        save_status("running")
        tasks = [asyncio.create_task(run_one(item)) for item in pending]
        try:
            await asyncio.gather(*tasks)
        except BaseException as exc:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            # 子任务因欠费被取消是正常停批；外部取消仍按中断上抛。
            if (stop_reason == "arrearage" and isinstance(exc, asyncio.CancelledError)
                    and not asyncio.current_task().cancelling()):
                return save_status("stopped")
            save_status("interrupted")
            raise
        if stop_reason is not None:
            return save_status("stopped")
        return save_status("completed" if not any(
            records[item["query_id"]].get("error") is not None for item in questions
        ) else "completed_with_errors")
    finally:
        lock.close()
        lock_path.unlink(missing_ok=True)
