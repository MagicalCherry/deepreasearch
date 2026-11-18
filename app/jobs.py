"""组织页面发起的后台评测与独立判分子进程，保存生命周期状态并在取消时清理子进程。"""

import asyncio
import os
from pathlib import Path
import sys

from app import runner
from app.config import PROJECT_ROOT, settings


TASKS: set[asyncio.Task] = set()


async def judge_run(run_id: str, dataset_path: Path) -> None:
    """按当前平台调用原有判分入口；参数只传路径和模型名，不传密钥。"""
    directory = runner.RUNS_DIR / run_id
    environment = os.environ.copy()
    environment["LLM_PROVIDER"] = settings.provider
    environment["PYTHONIOENCODING"] = "utf-8"
    if settings.provider == "openrouter":
        command = [sys.executable, "-X", "utf8", str(PROJECT_ROOT / "scripts" / "judge_openrouter.py"),
                   "--run", str(directory), "--dataset", str(dataset_path), "--execute"]
    else:
        command = [sys.executable, "-X", "utf8",
                   str(PROJECT_ROOT.parent / "MAS实操课程" / "04-评测工具" / "judge.py"),
                   "--run", str(directory), "--dataset", str(dataset_path),
                   "--judge-model", settings.model, "--base-url", settings.base_url,
                   "--api-key-env", "DASHSCOPE_API_KEY", "--concurrency", "2"]
    process = None
    with (directory / "judge.log").open("ab") as log:
        try:
            process = await asyncio.create_subprocess_exec(
                *command, cwd=PROJECT_ROOT, env=environment,
                stdout=log, stderr=asyncio.subprocess.STDOUT,
            )
            code = await process.wait()
            if code:
                raise RuntimeError(f"判分子进程退出码 {code}，详见该运行的 judge.log")
        finally:
            if process is not None and process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                await process.wait()


async def execute_run(dataset: str, version: str, concurrency: int, run_id: str) -> dict:
    """先评测后判分；欠费停止直接返回，失败与取消都记录状态。"""
    status = {"run_id": run_id, "status": "running", "pid": os.getpid()}
    directory = runner.RUNS_DIR / run_id
    phase = "run"
    try:
        status = await runner.run_eval(dataset, version, concurrency, run_id)
        if status["status"] not in {"completed", "completed_with_errors"}:
            return status
        final_status = dict(status)
        phase = "judge"
        status = {**status, "status": "judging", "pid": os.getpid()}
        runner.write_json(directory / "status.json", status)
        await judge_run(run_id, runner.dataset_path(dataset))
        runner.write_json(directory / "status.json", final_status)
        return final_status
    except asyncio.CancelledError:
        if directory.exists():
            runner.write_json(directory / "status.json", {
                **status, "status": "interrupted", "reason": "cancelled",
            })
        raise
    except Exception as exc:
        directory.mkdir(parents=True, exist_ok=True)
        status = {**status, "status": "judge_failed" if phase == "judge" else "failed",
                  "error": f"{type(exc).__name__}: {exc}"}
        runner.write_json(directory / "status.json", status)
        return status


def launch(dataset: str, version: str, concurrency: int, run_id: str) -> None:
    """保留后台任务引用，完成时释放；页面请求不等待评测结束。"""
    task = asyncio.create_task(execute_run(dataset, version, concurrency, run_id))
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)


async def shutdown() -> None:
    """后端退出时取消并等待所有页面后台任务，防止遗留判分进程。"""
    tasks = list(TASKS)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
