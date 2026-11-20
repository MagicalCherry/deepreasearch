"""S19离线规则重标：连接已有判分与最后核对事件，使用课程metrics重算，仅写*-rule副本，不调用模型。"""

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agents.dr.confidence import confidence_value, last_verification


def latest(path):
    result = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if line.strip():
            item = json.loads(line)
            result[str(item['query_id'])] = item
    return result


def recalibrate_records(results, judged):
    """保留正确性、答案和错误，仅在实验副本改变具备有效审核的成功题judge.confidence。"""
    if set(results) != set(judged):
        raise ValueError('结果与判分题号不一致，请先完成对应判分')
    output, audit = [], []
    for query_id, record in judged.items():
        original = results[query_id]
        if (record.get('response') != original.get('response')
                or record.get('error') != original.get('error')
                or not isinstance(record.get('judge'), dict)
                or type(record['judge'].get('correct')) is not bool):
            raise ValueError(f'题号{query_id}判分与当前结果不匹配')
        derived = deepcopy(record)
        counts = last_verification(original.get('events', []))
        reason = 'runner_error' if original.get('error') else 'no_valid_last_verification'
        if not original.get('error') and counts is not None:
            derived['judge']['confidence'] = confidence_value(*counts)
            derived['judge']['confidence_source'] = 'rule_last_verify'
            reason = 'rule_applied'
        audit.append({'query_id':query_id,'reason':reason,'counts':counts,
                      'before':record['judge'].get('confidence'),
                      'after':derived['judge'].get('confidence')})
        output.append(derived)
    return output, audit


def load_metrics():
    """只加载课程指标函数；不调用load_env或judge，材料目录只读。"""
    directory = ROOT.parent/'MAS实操课程'/'04-评测工具'
    sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location('s19_course_metrics', directory/'metrics.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def recalibrate_run(directory, questions, metrics):
    paths = [directory/name for name in ('results.jsonl','judged.jsonl','summary.json','config.json')]
    before_hashes = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    results, judged = latest(paths[0]), latest(paths[1])
    if not results or set(results) - set(questions):
        raise ValueError('运行为空或含题集外编号')
    derived, audit = recalibrate_records(results, judged)
    original_summary = json.loads(paths[2].read_text(encoding='utf-8'))
    before = metrics.summarize(list(judged.values()), questions)
    after = {**original_summary, **metrics.summarize(derived, questions),
             'confidence_source':'rule_last_verify_else_original',
             'experiment':'offline_recalibration', 'model_calls':0,
             'rule_applied':sum(a['reason']=='rule_applied' for a in audit)}
    assert after['accuracy'] == before['accuracy'] and after['runner_errors'] == before['runner_errors']
    (directory/'judged-rule.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in derived),encoding='utf-8')
    (directory/'summary-rule.json').write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    provenance = {'purpose':'S19仅置信度实验副本；原研究与判分保持不动','model_calls':0,
                  'rule':'round_half_up(20 + 75 * verified / total)',
                  'before':before['calibration_error'],'after':after['calibration_error'],
                  'original_sha256':before_hashes,'items':audit}
    (directory/'recalibration-rule.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if any(hashlib.sha256(p.read_bytes()).hexdigest() != before_hashes[p.name] for p in paths):
        raise RuntimeError('原始运行文件发生变化，请检查并行写入')
    return before, after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--dataset', choices=['smoke20','dev100'])
    args = parser.parse_args()
    directory = args.run.resolve()
    if ROOT/'runs' not in directory.parents:
        parser.error('run必须位于本项目runs目录')
    config = json.loads((directory/'config.json').read_text(encoding='utf-8'))
    dataset = args.dataset or config.get('dataset')
    if dataset not in ('smoke20','dev100') or dataset != config.get('dataset'):
        parser.error('仅支持与运行匹配的smoke20/dev100')
    questions = latest(ROOT.parent/'MAS实操课程'/'01-项目任务书'/'验收题集'/f'{dataset}.jsonl')
    before, after = recalibrate_run(directory, questions, load_metrics())
    print(f"{directory.name}: {before['calibration_error']} → {after['calibration_error']}")
    print(json.dumps({'before':before['calibration_error'],'after':after['calibration_error'],
                      'correct':after['correct'],'n':after['n'],'runner_errors':after['runner_errors'],
                      'rule_applied':after['rule_applied'],'model_calls':0},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
