"""离线验证置信度确定性提取、原判分保留、备份及重算幂等；禁止调用真实模型。"""

from copy import deepcopy
import json

import pytest

from scripts.judge_confidence import normalized_record, recalculate


def record(confidence='25%', **changes):
    return {'query_id': 'fictional', 'response': f'Explanation: Demo.\nExact Answer: Demo\nConfidence: {confidence}',
            'error': None, 'judge': {'correct': True, 'confidence': 100, 'raw': 'original model judgement'}, **changes}


@pytest.mark.parametrize('value,expected', [('0%', 0), ('25%', 25), ('50', 50), ('100%', 100),
                                          ('20.9%', 20), ('-1%', 0), ('101%', 100)])
def test_response_confidence_is_authoritative(value, expected):
    original = record(value)
    unchanged = deepcopy(original)
    fixed = normalized_record(original)
    assert original == unchanged
    assert fixed['response'] == original['response']
    assert fixed['judge']['confidence'] == expected
    assert fixed['judge']['model_confidence'] == 100
    assert fixed['judge']['raw'] == original['judge']['raw']
    assert fixed['judge']['correct'] is True
    assert normalized_record(fixed) == fixed


def test_crlf_fields_and_zero_are_preserved():
    item = record('0%')
    item['response'] = item['response'].replace('\n', '\r\n')
    assert normalized_record(item)['judge']['confidence'] == 0


@pytest.mark.parametrize('changes', [{'error': 'Fictional failure'}, {'response': ''},
    {'response': 'Explanation: Demo\nExact Answer: Demo'},
    {'response': 'Exact Answer: Demo\nConfidence: invalid'},
    {'response': 'Exact Answer: Demo\nConfidence: 20%\nConfidence: 80%'}])
def test_invalid_or_ambiguous_field_keeps_original_policy(changes):
    item = record(**changes)
    assert normalized_record(item) == item


def load_jsonl(path):
    return {row['query_id']: row for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip() for row in [json.loads(line)]}


def prepare(tmp_path):
    item = record('0%')
    (tmp_path / 'results.jsonl').write_text(json.dumps(item) + '\n', encoding='utf-8')
    (tmp_path / 'judged.jsonl').write_text(json.dumps(item) + '\n', encoding='utf-8')
    (tmp_path / 'summary.json').write_text(json.dumps({'avg_confidence': 100, 'judge_model': 'fictional'}), encoding='utf-8')
    (tmp_path / 'config.json').write_text(json.dumps({'dataset': 'smoke20', 'version': 'fictional'}), encoding='utf-8')
    return {'fictional': {'query': 'Fictional question'}}


def summarize(rows, questions):
    assert len(rows) == 1 and 'fictional' in questions
    return {'avg_confidence': rows[0]['judge']['confidence'], 'correct': int(rows[0]['judge']['correct'])}


def test_offline_recalculation_backs_up_and_does_not_change_answers(tmp_path):
    questions = prepare(tmp_path)
    original = {name: (tmp_path / name).read_bytes() for name in ('results.jsonl', 'judged.jsonl', 'summary.json', 'config.json')}
    summary, changed = recalculate(tmp_path, questions, summarize, load_jsonl)
    assert changed == 1 and summary['avg_confidence'] == 0
    assert summary['judge_model'] == 'fictional'
    assert summary['correct'] == 1
    for name in ('results.jsonl', 'config.json'):
        assert (tmp_path / name).read_bytes() == original[name]
    for name in ('judged.jsonl', 'summary.json'):
        assert (tmp_path / (name + '.before-confidence-fix')).read_bytes() == original[name]
    again, changed = recalculate(tmp_path, questions, summarize, load_jsonl)
    assert changed == 0 and again == summary
    assert (tmp_path / 'judged.jsonl.before-confidence-fix').read_bytes() == original['judged.jsonl']


def test_stale_judgement_is_rejected_before_writing(tmp_path):
    questions = prepare(tmp_path)
    stale = record(response='Old answer')
    (tmp_path / 'judged.jsonl').write_text(json.dumps(stale) + '\n', encoding='utf-8')
    before = (tmp_path / 'summary.json').read_bytes()
    with pytest.raises(ValueError, match='缺少与当前结果一致'):
        recalculate(tmp_path, questions, summarize, load_jsonl)
    assert (tmp_path / 'summary.json').read_bytes() == before
    assert not (tmp_path / 'judged.jsonl.before-confidence-fix').exists()
