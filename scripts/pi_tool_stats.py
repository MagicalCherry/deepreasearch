"""S17离线汇总已保存事件中的搜索、翻页、分块阅读与标题直读；不调用检索或模型。"""

import argparse
import json
from pathlib import Path


def summarize(records):
    """仅统计每题最后一条成功结果，避免续跑重复行使次数膨胀。"""
    latest = {}
    for record in records:
        latest[str(record['query_id'])] = record
    rows = []
    for query_id, record in latest.items():
        if record.get('error'):
            continue
        events = record.get('events', [])
        reads = [e for e in events if e['event'] == 'read']
        rows.append({'query_id': query_id,
                     'search_calls': sum(e['event'] == 'search' and not e.get('cached') for e in events),
                     'page_calls': sum(e['event'] == 'search' and bool(e.get('cached')) for e in events),
                     'read_calls': len(reads),
                     'unique_read_documents': len({str(e['docid']) for e in reads}),
                     'title_only_read_documents': len({str(e['docid']) for e in reads if e.get('title_only')})})
    keys = ('search_calls', 'page_calls', 'read_calls', 'unique_read_documents', 'title_only_read_documents')
    totals = {k: sum(r[k] for r in rows) for k in keys}
    return {'n': len(rows), 'totals': totals,
            'per_question': {k: round(v / len(rows), 3) if rows else None for k, v in totals.items()},
            'questions_with_paging': sum(r['page_calls'] > 0 for r in rows),
            'note': 'read_calls是分块工具调用；unique_read_documents去重。标题直读按该Scout首次读前未展示片段判断，再按题去重。',
            'items': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    args = parser.parse_args()
    path = args.run / 'results.jsonl'
    records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    print(json.dumps(summarize(records), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
