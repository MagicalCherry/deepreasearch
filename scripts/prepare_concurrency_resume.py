"""离线创建更换并发的续跑目录：保留成功结果原始行、原配置快照与来源，不调用模型或修改旧运行。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.history import process_alive


def prepare(source_id: str, target_id: str, concurrency: int) -> dict:
    """只允许同一研究代码的调度变更，拒绝活动源进程、覆盖目标及损坏结果。"""
    if concurrency < 1:
        raise ValueError("并发数必须为正数")
    for name in (source_id, target_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError("运行编号格式无效")
    source = ROOT / "runs" / source_id
    target = ROOT / "runs" / target_id
    status = json.loads((source / "status.json").read_text(encoding="utf-8"))
    if process_alive(status.get("pid")):
        raise ValueError("源进程尚未退出，请先正常中断")
    config_bytes = (source / "config.json").read_bytes()
    config = json.loads(config_bytes)
    old_sha = config["git_sha"]
    current_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    # git diff同时覆盖已提交差异及工作区差异；研究代码或依赖变化时拒绝混合结果。
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", old_sha, "--", "app", "pyproject.toml", "uv.lock"],
        cwd=ROOT, text=True,
    ).strip()
    if changed:
        raise ValueError("研究代码或依赖已变化，不能复用旧结果：" + changed)
    raw_results = (source / "results.jsonl").read_bytes()
    latest = {}
    for line in raw_results.splitlines(keepends=True):
        if line.strip():
            item = json.loads(line)
            latest[str(item["query_id"])] = (item, line)
    completed = {key: value for key, value in latest.items()
                 if value[0].get("error") is None and value[0].get("response", "").strip()}
    if len(completed) != status["completed"]:
        raise ValueError("状态与成功结果数量不一致，停止迁移")
    config["concurrency"] = concurrency
    config["git_sha"] = current_sha
    provenance = {
        "source_run": source_id, "source_git_sha": old_sha,
        "target_git_sha": current_sha, "source_concurrency": json.loads(config_bytes)["concurrency"],
        "target_concurrency": concurrency, "imported_query_ids": sorted(completed),
        "source_results_sha256": hashlib.sha256(raw_results).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "note": "复用原始成功记录；各导入题的实际提交与并发以source_config.json为准。未完成题重新研究，未保存的中断调用费用不在结果用量内。",
    }
    target.mkdir(exist_ok=False)
    (target / "source_config.json").write_bytes(config_bytes)
    (target / "results.jsonl").write_bytes(b"".join(
        line if line.endswith(b"\n") else line + b"\n" for _, line in completed.values()
    ))
    for name, value in {
        "config.json": config, "resume_provenance.json": provenance,
        "status.json": {"run_id": target_id, "status": "prepared", "total": status["total"],
                        "completed": len(completed), "errors": 0},
    }.items():
        (target / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"run_id": target_id, "imported": len(completed),
            "remaining": status["total"] - len(completed), "concurrency": concurrency,
            "execute": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.target, args.concurrency), ensure_ascii=False, indent=2))
