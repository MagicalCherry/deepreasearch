"""仅供离线评测：按证据召回分档统计正确数、工具预算和判分费用，不调用模型或输出标注。"""

import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
COURSE = ROOT.parent / "MAS实操课程" / "04-评测工具"
sys.path.insert(0, str(COURSE))
from common import load_dataset, load_jsonl
from metrics import evidence_recall


def main():
    """使用课程相同召回口径，仅输出聚合统计并保存报告。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--dataset", default="dev100")
    args = parser.parse_args()
    directory = Path(args.run).resolve()
    if ROOT / "runs" not in directory.parents:
        parser.error("运行目录必须位于本项目runs下")
    questions = load_dataset(args.dataset)
    results = load_jsonl(directory / "results.jsonl")
    judged = load_jsonl(directory / "judged.jsonl")
    if set(questions) - set(judged) or any(
        judged[k].get("response") != results[k].get("response") for k in questions
    ):
        parser.error("请先完成与当前结果一致的整份题集判分")
    bands = [{"recall_band": label, "n": 0, "correct": 0}
             for label in ("0%", "0% < recall < 50%", "recall >= 50%")]
    missing = 0
    for key, item in questions.items():
        record = judged[key]
        if not item.get("evidence_docids"):
            missing += 1
        recall = evidence_recall(record, item)
        band = bands[0 if recall == 0 else 1 if recall < 0.5 else 2]
        band["n"] += 1
        band["correct"] += int(bool(record["judge"]["correct"]))
    for band in bands:
        band["accuracy"] = round(100 * band["correct"] / band["n"], 2) if band["n"] else None
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    limit = config["options"]["max_tool_calls"]
    exhausted = sum(r.get("stop_reason") == "tool_budget" or
                    r.get("n_search", 0) + r.get("n_read", 0) >= limit
                    for key, r in results.items() if key in questions)
    usage_file = directory / "judge_usage.jsonl"
    costs = []
    unknown_cost = 0
    if usage_file.exists():
        for line in usage_file.read_text(encoding="utf-8").splitlines():
            usage = json.loads(line).get("usage", {})
            if usage.get("cost") is None:
                unknown_cost += 1
            else:
                costs.append(Decimal(str(usage["cost"])))
    report = {"run": directory.name, "recall_bands": bands,
              "missing_evidence_annotations": missing, "tool_limit": limit,
              "tool_budget_exhausted": exhausted,
              "judge_recorded_cost_usd": str(sum(costs, Decimal(0))),
              "judge_calls_with_cost": len(costs), "judge_calls_without_cost": unknown_cost}
    raw = json.dumps(report, ensure_ascii=False, indent=2)
    (directory / "recall_bands.json").write_text(raw, encoding="utf-8")
    print(raw)


if __name__ == "__main__":
    main()
