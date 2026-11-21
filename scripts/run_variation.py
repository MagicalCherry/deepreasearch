"""S20离线逐题对照与McNemar双侧精确检验；只读既有判分，不加载模型或题集答案。"""

import argparse
import json
import math
from pathlib import Path


def mcnemar_exact(improved, regressed):
    """条件于不一致配对数，在方向概率1/2下计算双侧二项尾概率。"""
    if any(type(value) is not int or value < 0 for value in (improved, regressed)):
        raise ValueError('改善和退步数必须是非负整数')
    n = improved + regressed
    if not n:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(improved, regressed) + 1))
    return min(1.0, (2 * tail) / (2 ** n))


def compare_records(before, after):
    """题号严格相同才比较；错误计入不正确，同时另列，不冒充普通答错。"""
    if set(before) != set(after):
        raise ValueError('两次运行题号集合不同，不能直接配对比较')
    result = {key: [] for key in (
        'improved', 'regressed', 'both_correct', 'both_incorrect',
        'identical_response_different_judgment', 'runner_errors_before', 'runner_errors_after')}
    for query_id in before:
        a, b = before[query_id], after[query_id]
        ac, bc = a.get('judge', {}).get('correct'), b.get('judge', {}).get('correct')
        if type(ac) is not bool or type(bc) is not bool:
            raise ValueError(f'{query_id}: 判分correct必须是布尔值')
        if (a.get('error') and ac) or (b.get('error') and bc):
            raise ValueError(f'{query_id}: 运行错误不能同时标为正确')
        key = ('both_correct' if ac else 'improved') if bc else ('regressed' if ac else 'both_incorrect')
        result[key].append(query_id)
        if ac != bc and isinstance(a.get('response'), str) and a.get('response') == b.get('response'):
            result['identical_response_different_judgment'].append(query_id)
        if a.get('error'):
            result['runner_errors_before'].append(query_id)
        if b.get('error'):
            result['runner_errors_after'].append(query_id)
    result['n'] = len(before)
    result['flips'] = len(result['improved']) + len(result['regressed'])
    result['mcnemar_exact_p'] = mcnemar_exact(len(result['improved']), len(result['regressed']))
    return result


def latest(path):
    """续跑时保留每题最后一条记录的内容和首次出现的题号顺序。"""
    records = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if line.strip():
            record = json.loads(line)
            records[str(record['query_id'])] = record
    return records


def load_run(directory):
    """核对判分对应最新研究输出，拒绝未完成或过期的配对。"""
    judged = latest(directory / 'judged.jsonl')
    results = latest(directory / 'results.jsonl')
    if not judged or set(judged) != set(results):
        raise ValueError(f'{directory.name}: 结果为空或判分题号不完整')
    for query_id, record in judged.items():
        source = results[query_id]
        if record.get('response') != source.get('response') or record.get('error') != source.get('error'):
            raise ValueError(f'{directory.name}/{query_id}: 判分与最新结果不匹配')
    return judged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    args = parser.parse_args()
    try:
        result = compare_records(load_run(args.before), load_run(args.after))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({'before': args.before.name, 'after': args.after.name, **result},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
