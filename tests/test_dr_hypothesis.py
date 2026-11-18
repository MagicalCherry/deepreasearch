"""离线验证v1.3候选共享、验证查询优先、对象列表清理与新旧分析分支，不读取真实题集。"""

import json

import pytest

from app.agents import s4_port
from app.agents.dr.team import DRScout
from app.trace import Trace


def make_scout():
    return DRScout(None, Trace(), None, {}, {'analysis': 'hypothesis'})


def test_candidate_queries_first_and_object_lists_cleaned():
    scout = make_scout()
    data = scout._normalize_hypothesis_analysis({
        'candidates': ['invalid', {'name': 'Demo Person', 'satisfied_constraints': ['born in fictional town'],
                                 'unmet_constraints': ['marriage year'],
                                 'verification_query': 'Demo Person marriage year'}],
        'extracted_facts': ['invalid', {'content': 'Fictional fact', 'data_points': ['bad', {'name': 'metric'}]}],
        'entities_discovered': ['bad', {'name': 'Demo Person', 'relations': ['bad', {'target': 'Demo Town'}]}],
        'data_points': ['bad'], 'hypothesis_evidence': ['bad'],
        'follow_up_queries': ['generic followup search', 123],
        'further_tracing_queries': ['other concrete clue'], 'source_tracing_queries': ['source detour'],
    })
    assert data['follow_up_queries'][0] == 'Demo Person marriage year'
    assert data['further_tracing_queries'][0] == 'Demo Person marriage year'
    assert data['source_tracing_queries'] == []
    assert len(data['extracted_facts']) == 1
    assert len(data['extracted_facts'][0]['data_points']) == 1
    assert len(data['entities_discovered'][0]['relations']) == 1
    assert data['data_points'] == data['hypothesis_evidence'] == []
    assert 'Demo Person' in scout.candidates
    assert make_scout().candidates == {}


async def test_initial_and_deep_analysis_use_shared_candidates(monkeypatch):
    scout = make_scout()
    prompts = []

    async def fake_llm(**kwargs):
        prompts.append(kwargs['user_prompt'])
        return json.dumps({'candidates': [{'name': 'Demo Person', 'verification_query': 'Demo Person birth year'}]})

    monkeypatch.setattr(scout, 'call_llm', fake_llm)
    results = [{'title': 'Demo', 'url': 'https://example.test/fiction', 'summary': 'Fictional snippet'}]
    first = await scout._analyze_search_results('Fictional question', {'description': 'Fictional clue'}, results)
    deep = await scout._analyze_deep_search_results('Fictional question', 'Demo Person clue', results, 'follow_up', [])
    assert first['follow_up_queries'][0] == deep['further_tracing_queries'][0] == 'Demo Person birth year'
    assert 'Demo Person' in prompts[1]
    assert 'https://example.test/fiction' in prompts[0]


async def test_v12_preserves_original_analysis(monkeypatch):
    sentinel = {'unchanged': True}

    async def old_analysis(self, *args):
        return sentinel

    monkeypatch.setattr(s4_port.CorpusScout, '_analyze_search_results', old_analysis)
    scout = DRScout(None, Trace(), None, {}, {'expand': 2})
    assert await scout._analyze_search_results('query', {}, []) is sentinel
