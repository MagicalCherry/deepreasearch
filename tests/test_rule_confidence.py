"""S19先定义规则置信度的数值、只改置信度行及版本隔离契约；不调用模型或读取题集标注。"""

from copy import deepcopy

import pytest

from app.agents.dr import pipeline
from app.versions import get_version


ANSWER = 'Explanation: Fictional evidence [12].\nExact Answer: Demo\nConfidence: 41%'


@pytest.mark.parametrize('verified,total,expected', [(2,4,58),(4,4,95),(0,4,20)])
def test_rule_confidence_changes_only_confidence_line(verified, total, expected):
    result = pipeline.rule_confidence(ANSWER, verified, total)
    assert result == ANSWER.replace('Confidence: 41%', f'Confidence: {expected}%')


def test_rule_confidence_keeps_original_when_no_checks_exist():
    assert pipeline.rule_confidence(ANSWER, 0, 0) == ANSWER


def test_v23_adds_only_rule_confidence_and_keeps_600_second_default():
    previous = deepcopy(get_version('v2.2').options)
    assert get_version('v2.3').options == {**previous, 'confidence':'rule'}
    assert get_version('v2.2').options == previous
    assert previous['time_budget'] == 600


@pytest.mark.parametrize('nv,nt', [(5,4),(-1,4),(True,4),(1,None),(1,0)])
def test_invalid_check_counts_keep_original(nv, nt):
    assert pipeline.rule_confidence(ANSWER,nv,nt) == ANSWER


def test_rule_keeps_crlf_and_missing_or_ambiguous_confidence_lines():
    crlf = ANSWER.replace('\n','\r\n') + '\r\n'
    assert pipeline.rule_confidence(crlf,4,4) == crlf.replace('41%','95%')
    for text in ['Exact Answer: Demo', ANSWER+'\nConfidence: 30%']:
        assert pipeline.rule_confidence(text,4,4) == text


def test_last_verify_does_not_fall_back_to_earlier_complete_review():
    from app.agents.dr.confidence import last_verification
    events = [{'event':'verify','verified':4,'total':4},
              {'event':'verify','verified':1,'total':4}]
    assert last_verification(events) == (1,4)
    events.append({'event':'verify','verified':0,'total':0})
    assert last_verification(events) is None


async def test_actual_runner_output_and_answer_event_use_rule_without_changing_answer(monkeypatch):
    from app import runner
    from app.agents.dr import flow_fixes
    from app.trace import Trace

    async def fake_flow(question, trace, opts):
        trace.emit('verify',verified=2,total=4,verdict='fail')
        return ANSWER

    monkeypatch.setattr(flow_fixes,'run',fake_flow)
    for version, expected in [('v2.2',41),('v2.3',58)]:
        trace = Trace()
        result = await runner.research('Fictional question',version,trace)
        assert result == ANSWER.replace('41%',f'{expected}%')
        assert next(e for e in trace.events if e['event']=='answer')['confidence'] == expected


def test_offline_join_changes_only_derived_confidence_and_preserves_errors():
    from scripts.recalibrate import recalibrate_records
    results = {'demo':{'query_id':'demo','response':ANSWER,'error':None,
                      'events':[{'event':'verify','verified':4,'total':4},
                                {'event':'verify','verified':2,'total':4}]},
               'failed':{'query_id':'failed','response':'','error':'Connection error',
                         'events':[{'event':'verify','verified':4,'total':4}]}}
    judged = {'demo':{'query_id':'demo','response':ANSWER,'error':None,
                     'judge':{'correct':True,'confidence':41,'raw':'Original judge text'}},
              'failed':{'query_id':'failed','response':'','error':'Connection error',
                        'judge':{'correct':False,'confidence':0,'raw':'Error'}}}
    original = deepcopy((results,judged))
    derived,audit = recalibrate_records(results,judged)
    assert derived[0]['judge']['confidence'] == 58
    assert derived[0]['judge']['correct'] is True and derived[0]['response'] == ANSWER
    assert derived[0]['judge']['raw'] == 'Original judge text'
    assert derived[1] == judged['failed'] and audit[1]['reason'] == 'runner_error'
    assert (results,judged) == original


def test_offline_no_verify_keeps_original_and_rejects_stale_judgement():
    from scripts.recalibrate import recalibrate_records
    results = {'demo':{'query_id':'demo','response':ANSWER,'error':None,'events':[]}}
    judged = {'demo':{'query_id':'demo','response':ANSWER,'error':None,
                     'judge':{'correct':False,'confidence':41}}}
    derived,audit = recalibrate_records(results,judged)
    assert derived[0] == judged['demo'] and audit[0]['reason'] == 'no_valid_last_verification'
    judged['demo']['response'] = 'Old response'
    with pytest.raises(ValueError,match='不匹配'):
        recalibrate_records(results,judged)


def test_offline_writes_new_files_only_and_metrics_remain_same_accuracy(tmp_path):
    import json
    import hashlib
    from scripts.recalibrate import recalibrate_run,load_metrics
    result = {'query_id':'demo','response':ANSWER,'error':None,'retrieved_docids':[],
              'events':[{'event':'verify','verified':2,'total':4}]}
    judged = {**result,'judge':{'correct':True,'confidence':41}}
    files={'results.jsonl':json.dumps(result)+'\n','judged.jsonl':json.dumps(judged)+'\n',
           'summary.json':json.dumps({'run':'fictional','dataset':'smoke20'}),
           'config.json':json.dumps({'dataset':'smoke20'})}
    for name,text in files.items():
        (tmp_path/name).write_text(text,encoding='utf-8')
    hashes={name:hashlib.sha256((tmp_path/name).read_bytes()).hexdigest() for name in files}
    before,after = recalibrate_run(tmp_path,{'demo':{'query_id':'demo'}},load_metrics())
    assert before['accuracy'] == after['accuracy'] == 100
    assert before['calibration_error'] == 59 and after['calibration_error'] == 42
    assert after['model_calls'] == 0
    assert all(hashlib.sha256((tmp_path/name).read_bytes()).hexdigest()==h for name,h in hashes.items())
    assert (tmp_path/'summary-rule.json').exists() and (tmp_path/'judged-rule.jsonl').exists()
