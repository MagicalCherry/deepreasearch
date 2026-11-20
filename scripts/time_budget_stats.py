"""S18离线统计已保存运行的平均/P90/最长耗时及时间预算撞线题；不调用模型或检索。"""

import argparse
import json
import math
from pathlib import Path


def summarize(records):
    """同题只取最后一次结果；P90使用最近秩ceil(0.9*n)，同时列出错误题数。"""
    latest = {}
    for record in records:
        latest[str(record['query_id'])] = record
    rows = list(latest.values())
    seconds = sorted(float(r['seconds']) for r in rows)
    if any(not math.isfinite(v) or v < 0 for v in seconds):
        raise ValueError('运行耗时必须为有限非负数')
    hit = sorted(str(r['query_id']) for r in rows if r.get('stop_reason') == 'time_budget')
    return {'n':len(rows), 'avg_seconds':round(sum(seconds)/len(seconds), 3) if seconds else None,
            'p90_seconds':seconds[math.ceil(.9*len(seconds))-1] if seconds else None,
            'max_seconds':seconds[-1] if seconds else None,
            'time_budget_count':len(hit), 'time_budget_query_ids':hit,
            'runner_errors':sum(bool(r.get('error')) for r in rows),
            'p90_method':'nearest_rank_ceil',
            'scope':'每题最后记录，含错误题；不含被续跑替代的失败尝试耗时，不是批次吞吐或全部计费。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    args = parser.parse_args()
    records = [json.loads(line) for line in (args.run/'results.jsonl').read_text(
        encoding='utf-8').splitlines() if line.strip()]
    print(json.dumps(summarize(records), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
