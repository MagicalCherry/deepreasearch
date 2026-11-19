"""虚构证据验证v1.7逐项审核、补搜优先级和置信度边界；不调用云端模型。"""

import json

import pytest

from app.agents.dr.constraints import answer_context, cap_answer, confidence_cap
from app.agents.dr.flow_fixes import ValidatedCritic
from app.answer import parse
from app.s4.deep_research_v2.state import create_initial_state
from app.trace import Trace
from app.versions import get_version
from scripts.constraint_bands import band, summarize


@pytest.mark.parametrize('verified,total,cap', [(0, 0, 25), (0, 3, 25), (2, 4, 25),
                                               (3, 5, 50), (4, 5, 50), (5, 5, 100)])
def test_confidence_boundaries(verified, total, cap):
    state = {'_constraint_checks': [{'constraint': str(i), 'status': 'verified' if i < verified else 'unverified'}
                                    for i in range(total)]}
    assert confidence_cap(state) == cap
    assert parse(cap_answer('Explanation: Fictional.\nExact Answer: Demo\nConfidence: 99%', state))['confidence'] == min(99, cap)
    assert f'{verified}/{total}' in answer_context(state)
    assert parse(cap_answer('Explanation: Fictional.\nExact Answer: Demo\nConfidence: 10%', state))['confidence'] == 10


def setup_review(monkeypatch, checks, alternative='', issues=None):
    trace = Trace()
    trace.emit('search', results=[{'docid': '1', 'url': 'corpus://1', 'title': 'Fictional'}])
    critic = ValidatedCritic(None, trace, get_version('v1.7').options)
    state = create_initial_state('Fictional question', 'test')
    state.update(_constraints=['fictional birth year', 'fictional marriage'],
                 final_report='Fictional report', facts=[{'content': 'Fictional evidence', 'source_url': 'corpus://1'}])
    result = {'overall_assessment': {'quality_score': 8, 'verdict': 'pass'},
              'constraint_checks': checks, 'alternative_candidate': alternative,
              'issues': [] if issues is None else issues, 'missing_aspects': []}
    async def fake_call(**kwargs):
        assert 'corpus://1' in kwargs['user_prompt']
        assert 'Original constraints' in kwargs['user_prompt']
        return json.dumps(result)
    monkeypatch.setattr(critic, 'call_llm', fake_call)
    return critic, state, trace


def check(index, status='verified', docid='1'):
    return {'constraint_index': index, 'constraint': ['fictional birth year', 'fictional marriage'][index],
            'status': status, 'docid': docid, 'note': 'Fictional source statement'}


async def test_missing_constraint_cannot_pass_and_alternative_is_first(monkeypatch):
    critic, state, trace = setup_review(monkeypatch, [check(0)], alternative='Demo Person', issues=[None, 'bad',
        {'issue_type': 'incomplete', 'severity': 'major', 'requires_new_search': True, 'search_query': 'Other concrete query'}])
    result = await critic._review_content(state)
    assert state['_verified'] == 1
    assert len(state['_constraint_checks']) == 2
    assert result['constraint_checks'][1]['status'] == 'unverified'
    assert result['overall_assessment']['verdict'] == 'needs_revision'
    assert len(result['issues']) == 1
    assert critic._analyze_issues_for_routing(result)['search_queries'][0] == 'Demo Person fictional birth year'
    assert trace.events[-1]['review'] == result


@pytest.mark.parametrize('checks', [[check(0), check(1, docid='999')],
                                   [check(0), check(1, status='refuted')],
                                   [check(0), check(0), check(1)],
                                   [check(1)]])
async def test_invalid_missing_duplicate_and_refuted_checks_cannot_pass(monkeypatch, checks):
    critic, state, _ = setup_review(monkeypatch, checks)
    result = await critic._review_content(state)
    assert result['overall_assessment']['verdict'] == 'needs_revision'
    assert state['_verified'] < 2


async def test_all_verified_can_pass(monkeypatch):
    critic, state, _ = setup_review(monkeypatch, [check(1), check(0)])
    result = await critic._review_content(state)
    assert result['overall_assessment']['verdict'] == 'pass'
    assert state['_verified'] == 2


async def test_missing_check_table_is_rejected(monkeypatch):
    critic, state, _ = setup_review(monkeypatch, [])
    async def invalid(**kwargs):
        return json.dumps({'overall_assessment': {'quality_score': 8, 'verdict': 'pass'}, 'issues': []})
    monkeypatch.setattr(critic, 'call_llm', invalid)
    with pytest.raises(ValueError):
        await critic._review_content(state)


@pytest.mark.parametrize('verified,total,expected', [(0, 0, None), (4, 3, None), (True, 1, None),
    (4, 4, '全部验证'), (3, 4, '至少75%但未全部'), (2, 4, '50%至不足75%'), (1, 4, '不足50%')])
def test_band_boundaries(verified, total, expected):
    assert band(verified, total) == expected


def test_bands_use_last_verification_and_matching_judgement():
    results = {'x': {'response': 'Demo', 'events': [
        {'event': 'verify', 'agent': 'critic', 'verified': 4, 'total': 4},
        {'event': 'verify', 'agent': 'critic', 'verified': 1, 'total': 4}]}}
    judged = {'x': {'response': 'Demo', 'judge': {'correct': True}}}
    report = summarize(results, judged)
    assert report['bands']['不足50%']['correct'] == 1
    assert report['bands']['全部验证']['n'] == 0
    judged['x']['response'] = 'Old answer'
    with pytest.raises(ValueError):
        summarize(results, judged)


async def test_extractor_includes_constraint_context_in_followup(monkeypatch):
    from app.agents import s4_port
    prompts = []
    async def fake_call(self, system_prompt, user_prompt, **kwargs):
        prompts.append(user_prompt)
        return ('Explanation: Demo.\nExact Answer: Unknown\nConfidence: 90%' if len(prompts) == 1 else
                'Explanation: Demo.\nExact Answer: Demo\nConfidence: 90%')
    monkeypatch.setattr(s4_port.Traced, 'call_llm', fake_call)
    state = {'final_report': 'Demo', 'facts': [], '_constraint_checks': [
        {'constraint': 'fictional year', 'status': 'unverified'}]}
    result = await s4_port._extract('Demo question', state, None, Trace(), {}, answer_suffix=answer_context(state))
    assert len(prompts) == 2
    assert all('Confidence MUST NOT exceed 25%' in p for p in prompts)
    assert parse(cap_answer(result, state))['confidence'] == 25
