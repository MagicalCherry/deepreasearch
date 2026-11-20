"""离线复用同模型同代码的smoke20结果及判分，准备只补80题的dev100目录并保存来源；不调用模型。"""

import asyncio
import argparse
from copy import deepcopy
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['LLM_PROVIDER'] = 'openrouter'
os.environ['LLM_MODEL_PROFILE'] = 'economy'
from app.config import settings
from app.history import process_alive
from app.runner import load_questions, search_config
from app.versions import get_version

PAIRS = (
    ('s08-qwen37-closedbook-smoke20', 's08-qwen37-closedbook-dev100-reuse20'),
    ('s08-qwen37-single-smoke20', 's08-qwen37-single-dev100-reuse20'),
    ('s08-qwen37-s4-smoke20', 's08-qwen37-s4-dev100-reuse20'),
)


def latest_lines(path):
    """按编号选择最后一条原始记录，不改写答案、事件或判分。"""
    records = {}
    for line in path.read_bytes().splitlines(keepends=True):
        if line.strip():
            item = json.loads(line)
            records[str(item['query_id'])] = (item, line)
    return records


async def main(pairs=PAIRS):
    """先验证所有来源及目标，再建立新目录；检索健康快照为本地只读请求。"""
    # 不在旧dev100仍运行时创建替代批次，避免学员意外重复付费。
    for path in (ROOT / 'runs').glob('s08-qwen37-*dev100*/status.json'):
        status = json.loads(path.read_bytes())
        if status.get('status') == 'running' and process_alive(status.get('pid')):
            raise ValueError('已有dev100运行，请先Ctrl+C中断：' + path.parent.name)
    questions = load_questions('dev100')
    smoke = {q['query_id']: q['query'] for q in load_questions('smoke20')}
    dev = {q['query_id']: q['query'] for q in questions}
    if len(smoke) != 20 or len(dev) != 100 or any(dev.get(k) != v for k, v in smoke.items()):
        raise ValueError('题集重叠或题面不一致')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    plans = []
    for source_id, target_id in pairs:
        if any(not re.fullmatch(r'[A-Za-z0-9_-]+', name) for name in (source_id, target_id)):
            raise ValueError('运行名称只能使用字母、数字、下划线、短横线')
        source, target = ROOT / 'runs' / source_id, ROOT / 'runs' / target_id
        if target.exists():
            raise ValueError('目标已存在，不覆盖：' + target_id)
        original = (source / 'config.json').read_bytes()
        config = json.loads(original)
        smoke_questions = load_questions('smoke20')
        smoke_hash = hashlib.sha256(json.dumps(smoke_questions, sort_keys=True).encode()).hexdigest()
        if config.get('dataset') != 'smoke20' or config.get('questions_sha256') != smoke_hash:
            raise ValueError('来源不是当前smoke20题面配置：' + source_id)
        summary = json.loads((source / 'summary.json').read_bytes())
        if summary.get('judge_model') != settings.model:
            raise ValueError('来源判分模型与当前模型不一致：' + source_id)
        status = json.loads((source / 'status.json').read_bytes())
        if status.get('status') != 'completed' or status.get('errors') != 0:
            raise ValueError('来源尚未全部成功完成：' + source_id)
        changed = subprocess.check_output(
            ['git', 'diff', '--name-only', config['git_sha'], '--', 'app', 'pyproject.toml', 'uv.lock'],
            cwd=ROOT, text=True).strip()
        if changed:
            raise ValueError('研究代码或依赖已改变：' + changed)
        expected = {'model': settings.model, 'llm_provider': settings.provider,
                    'llm_base_url': settings.base_url, 'max_tokens': settings.max_tokens,
                    'options': deepcopy(get_version(config['version']).options)}
        if any(config[k] != v for k, v in expected.items()):
            raise ValueError('当前模型或版本配置与来源不同：' + source_id)
        snapshot = await search_config(config['version'] != 'v0-closedbook',
            **{key: config['options'][key] for key in ('index', 'snippet') if key in config['options']})
        if snapshot != config['search']:
            raise ValueError('检索索引配置与来源不同')
        results = latest_lines(source / 'results.jsonl')
        if set(results) != set(smoke) or any(r.get('error') or not r.get('response', '').strip() for r, _ in results.values()):
            raise ValueError('来源缺少成功冒烟结果')
        judged = latest_lines(source / 'judged.jsonl')
        if any(k not in judged or judged[k][0].get('response') != r['response'] for k, (r, _) in results.items()):
            raise ValueError('来源缺少与答案对应的判分')
        config.update(dataset='dev100', concurrency=8, git_sha=head,
                      questions_sha256=hashlib.sha256(json.dumps(questions, sort_keys=True).encode()).hexdigest())
        plans.append((source, target, original, config, results, judged))
    for source, target, original, config, results, judged in plans:
        target.mkdir(exist_ok=False)
        (target / 'source_config.json').write_bytes(original)
        for filename, records in [('results.jsonl', results), ('judged.jsonl', judged)]:
            (target / filename).write_bytes(b''.join(
                line if line.endswith(b'\n') else line + b'\n' for _, line in records.values()))
        provenance = {'source_run': source.name, 'imported_query_ids': sorted(results),
                      'source_results_sha256': hashlib.sha256((source / 'results.jsonl').read_bytes()).hexdigest(),
                      'note': '复用已完成20题原始结果与判分，只补80题；原题实际并发和提交见来源配置，非全程同并发性能实验。'}
        for extra in ['resume_provenance.json', 'source_config.json']:
            if (source / extra).exists():
                provenance['source_' + extra.replace('.', '_')] = json.loads((source / extra).read_bytes())
        for name, data in [('config.json', config), ('resume_provenance.json', provenance),
                           ('status.json', {'run_id': target.name, 'status': 'prepared', 'total': 100, 'completed': 20, 'errors': 0})]:
            (target / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'run_id': target.name, 'imported': 20, 'remaining': 80, 'judge_reused': len(judged), 'execute': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', help='已完成并判分的smoke20运行名称')
    parser.add_argument('--target', help='新dev100运行名称；不会覆盖已有目录')
    args = parser.parse_args()
    if bool(args.source) != bool(args.target):
        parser.error('--source与--target必须同时提供')
    asyncio.run(main(((args.source, args.target),) if args.source else PAIRS))
