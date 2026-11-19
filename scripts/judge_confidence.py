"""判分置信度适配：确定性提取最终答案字段，保留模型判分原文，并备份后离线重算汇总。"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from app.answer import parse


def normalized_record(record):
    """只修正置信度及来源标记；正确性、研究答案与判分原文保持原样。"""
    result = deepcopy(record)
    judgement = result.get('judge')
    if not isinstance(judgement, dict):
        raise ValueError('缺少有效judge记录')
    if result.get('error') or not (result.get('response') or '').strip():
        return result
    response = result['response']
    labels = re.findall(r'^[ \t]*Confidence:[ \t]*([^\r\n]*)\r?$', response, re.MULTILINE)
    if len(labels) != 1 or not re.fullmatch(r'[+-]?\d+(?:\.\d+)?[ \t]*%?', labels[0].strip()):
        return result
    judgement.setdefault('model_confidence', judgement.get('confidence'))
    judgement['confidence'] = parse(response)['confidence']
    judgement['confidence_source'] = 'response_field'
    return result


def atomic_write(path, content):
    """在同目录准备文件后替换，避免写入中断留下半份JSONL。"""
    descriptor, temp = tempfile.mkstemp(dir=path.parent, prefix='.confidence-', suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def recalculate(directory, questions, summarize, load_jsonl):
    """只接受与当前结果完全对应的完整判分；备份原文件，不请求模型或改变研究配置。"""
    directory = Path(directory)
    results = load_jsonl(directory / 'results.jsonl')
    judged = load_jsonl(directory / 'judged.jsonl')
    if not results or any(key not in questions for key in results):
        raise ValueError('结果为空或含题集外编号')
    ordered = []
    for key, record in results.items():
        cached = judged.get(key)
        if (not isinstance(cached, dict) or cached.get('response') != record.get('response')
                or bool(cached.get('error')) != bool(record.get('error'))
                or not isinstance(cached.get('judge'), dict)
                or type(cached.get('judge', {}).get('correct')) is not bool):
            raise ValueError(f'题号{key}缺少与当前结果一致的有效判分；离线模式不会补判')
        ordered.append(normalized_record(cached))
    summary_path = directory / 'summary.json'
    original_summary = json.loads(summary_path.read_bytes())
    config = json.loads((directory / 'config.json').read_bytes())
    # 校验题集由调用方完成；模型身份保留历史元数据，不以当前环境覆盖。
    summary = {**original_summary, **summarize(ordered, questions), 'run': directory.name,
               'version': config.get('version'), 'dataset': config.get('dataset'),
               'confidence_source': 'response_field_when_valid_else_original_judge'}
    before = {}
    for name in ('judged.jsonl', 'summary.json'):
        path = directory / name
        raw = path.read_bytes()
        backup = directory / (name + '.before-confidence-fix')
        if not backup.exists():
            with backup.open('xb') as stream:
                stream.write(raw)
        before[name] = hashlib.sha256(backup.read_bytes()).hexdigest()
    changed = sum(judged[key]['judge'].get('confidence') != new['judge'].get('confidence')
                  for key, new in zip(results, ordered))
    atomic_write(directory / 'judged.jsonl', ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in ordered).encode('utf-8'))
    atomic_write(summary_path, json.dumps(summary, ensure_ascii=False, indent=2).encode('utf-8'))
    provenance = directory / 'confidence_repair.json'
    if not provenance.exists():
        atomic_write(provenance, json.dumps({'method': 'response_field_v1', 'changed_confidences': changed,
            'original_backup_sha256': before, 'model_calls': 0}, indent=2).encode('utf-8'))
    return summary, changed
