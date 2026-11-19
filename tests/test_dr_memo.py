"""用虚构证据验证v1.5只写一份备忘录、直接拼接及证据缺口路由；不调用模型。"""

import json
import pytest

from app.agents.dr.team import DRWriter, DRCritic
from app.s4.deep_research_v2.state import create_initial_state
from app.trace import Trace


@pytest.mark.asyncio
async def test_memo_writes_once_and_synthesizes_without_llm(monkeypatch):
    writer = DRWriter(None, Trace(), {'writer': 'memo'})
    state = create_initial_state('Fictional question', 'memo-test')
    state['outline'] = [{'id': 'a'}, {'id': 'b'}, {'id': 'c'}]
    state['facts'] = [{'content': 'Fictional quote', 'source_url': 'https://example.test/1'}]
    calls = []

    async def fake_call(**kwargs):
        calls.append(kwargs)
        return json.dumps({'content': 'Evidence memo', 'best_answer': 'Demo', 'citations': [
            {'url': 'https://example.test/1'}, {'url': 'https://invented.test'}]})

    monkeypatch.setattr(writer, 'call_llm', fake_call)
    for section in state['outline']:
        await writer._write_section(state, section)
    await writer._synthesize_report(state)
    assert len(calls) == 1
    assert state['draft_sections'] == {'a': 'Evidence memo', 'b': '', 'c': ''}
    assert state['final_report'] == 'Evidence memo'
    assert state['references'] == [{'url': 'https://example.test/1'}]


def test_evidence_gap_routes_to_research():
    critic = DRCritic(None, Trace(), {'critic': 'evidence'})
    review = {'issues': [{'issue_type': 'incomplete', 'severity': 'major',
                         'requires_new_search': True, 'search_query': 'Fictional person graduation'}],
              'missing_aspects': []}
    route = critic._analyze_issues_for_routing(review)
    assert route['should_research']
    assert route['search_queries'] == ['Fictional person graduation']
    review['issues'][0].update(issue_type='logic_error', requires_new_search=False, search_query='')
    assert not critic._analyze_issues_for_routing(review)['should_research']
