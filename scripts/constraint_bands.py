"""S13离线分档：只读当前结果、对应判分及最后一次核查比例，输出四档正确率和缺失情况。"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = ('全部验证', '至少75%但未全部', '50%至不足75%', '不足50%')


def band(verified, total):
    """零约束、非法计数不混入全部验证或其他比例档。"""
    if (type(verified) is not int or type(total) is not int
            or total <= 0 or not 0 <= verified <= total):
        return None
    ratio = verified / total
    return LABELS[0] if ratio == 1 else LABELS[1] if ratio >= .75 else LABELS[2] if ratio >= .5 else LABELS[3]


def latest(path):
    records = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if line.strip():
            item = json.loads(line)
            records[str(item['query_id'])] = item
    return records


def summarize(results, judged):
    groups = {name: {'n': 0, 'correct': 0} for name in LABELS}
    excluded = {'runner_errors': 0, 'missing_verification': 0}
    for key, result in results.items():
        if result.get('error'):
            excluded['runner_errors'] += 1
            continue
        verdict = judged.get(key, {})
        correct = verdict.get('judge', {}).get('correct')
        if verdict.get('error') or verdict.get('response') != result.get('response') or type(correct) is not bool:
            raise ValueError(f'题号{key}缺少与当前结果一致的判分')
        events = [e for e in result.get('events', []) if e.get('event') == 'verify' and e.get('agent') == 'critic']
        label = band(events[-1].get('verified'), events[-1].get('total')) if events else None
        if label is None:
            excluded['missing_verification'] += 1
            continue
        groups[label]['n'] += 1
        groups[label]['correct'] += int(correct)
    for group in groups.values():
        group['accuracy'] = round(100 * group['correct'] / group['n'], 2) if group['n'] else None
    return {'total': len(results), 'bands': groups, 'excluded': excluded}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    directory = Path(args.run).resolve()
    if ROOT / 'runs' not in directory.parents:
        parser.error('run必须位于本项目runs目录')
    print(json.dumps(summarize(latest(directory / 'results.jsonl'), latest(directory / 'judged.jsonl')),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
