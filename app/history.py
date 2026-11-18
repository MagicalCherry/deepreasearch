"""只读加载运行配置、状态、结果和判分，转换成成品前端需要的数据，并检查进程是否仍存在。"""

import json
import os
import re
from pathlib import Path

from app import runner
from app.answer import parse


def process_alive(pid: int) -> bool:
    """只读检查进程；Windows 使用进程句柄，不发送信号。"""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            # 访问被拒绝说明进程存在，但当前用户无权打开。
            return ctypes.get_last_error() == 5
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0x102
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False


def run_directory(run_id: str) -> Path:
    """限制运行编号及解析后的目录范围，拒绝访问 runs 以外的文件。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise FileNotFoundError(run_id)
    directory = runner.RUNS_DIR / run_id
    if (directory.resolve().parent != runner.RUNS_DIR.resolve()
            or not (directory / "config.json").is_file()):
        raise FileNotFoundError(run_id)
    return directory


def read_json(path: Path, default=None):
    """读取可选 JSON 文件，不创建或改写文件。"""
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


def read_records(path: Path) -> dict[str, dict]:
    """同编号取最后记录；忽略正在写入的残缺末行，绝不修复原文件。"""
    if not path.exists():
        return {}
    records = {}
    lines = path.read_bytes().splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            if index == len(lines) - 1 and not line.endswith(b"\n"):
                break
            raise
        records[str(record["query_id"])] = record
    return records


def run_info(run_id: str, alive=process_alive) -> dict:
    """适配 status/completed/git_sha 字段；仅在响应中标出已退出的运行。"""
    directory = run_directory(run_id)
    config = read_json(directory / "config.json", {})
    summary = read_json(directory / "summary.json")
    raw = read_json(directory / "status.json", {})
    state = raw.get("state", raw.get("status", "completed" if summary else "unknown"))
    status = {**raw, "state": state, "done": raw.get("done", raw.get("completed", 0))}
    if state in {"running", "judging"} and raw.get("pid") is not None and not alive(raw["pid"]):
        status.update(state="interrupted", reason="process_exited")
    return {"run_id": run_id,
            "config": {**config, "git_commit": config.get("git_commit", config.get("git_sha"))},
            "status": status, "summary": summary}


def run_items(run_id: str) -> dict[str, dict]:
    """合并逐题结果与对应响应的判分；避免旧判分覆盖续跑后的新答案。"""
    directory = run_directory(run_id)
    records = read_records(directory / "results.jsonl")
    judged = read_records(directory / "judged.jsonl")
    result = {}
    for query_id, record in records.items():
        item = {**record, "query_id": query_id}
        judgement = judged.get(query_id)
        if judgement and judgement.get("response") == record.get("response"):
            item["judge"] = judgement.get("judge")
        result[query_id] = item
    return result


def item_summary(item: dict) -> dict:
    """提取同题对照所需字段，尚未判分时 correct 为 null。"""
    answer = parse(item.get("response", ""))
    judgement = item.get("judge") or {}
    return {"query_id": item["query_id"], "exact_answer": answer["exact_answer"],
            "confidence": answer["confidence"], "correct": judgement.get("correct"),
            **{key: item.get(key, 0) for key in (
                "n_search", "n_read", "prompt_tokens", "completion_tokens", "seconds")},
            "error": item.get("error"), "stop_reason": item.get("stop_reason")}
