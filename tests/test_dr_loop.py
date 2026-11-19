"""用虚构模型与文档验证v1.6逐轮决策、近似去重、来源绑定和补搜；不调用云服务。"""

import asyncio
import json

import pytest

from app.agents import s4_port
from app.agents.dr.team import DRScout
from app.s4.deep_research_v2.state import create_initial_state, ResearchPhase
from app.trace import Trace
from app.versions import get_version


class FakeSearch:
    def __init__(self):
        self.calls = []
        self.reads = []

    async def search(self, query, k=5):
        self.calls.append((query, k))
        await asyncio.sleep(0)
        docid = str(len(self.calls))
        return {'results': [{'docid': docid, 'url': 'corpus://' + docid,
                             'title': 'Fictional page ' + docid, 'snippet': 'Fictional evidence'}]}

    async def document(self, docid, max_tokens=None):
        self.reads.append(docid)
        return {'docid': docid, 'title': 'Fictional page', 'text': 'Fictional evidence from full text.'}


def setup_loop(**changes):
    trace, search = Trace(), FakeSearch()
    scout = DRScout(None, trace, search, {}, {**get_version('v1.6').options, **changes})
    state = create_initial_state('Fictional original question', 'loop-test')
    state['facts'] = s4_port.FactList(trace, scout.sources)
    state['_constraints'] = ['Fictional constraint']
    section = {'id': 'sec_1', 'title': 'Fictional identity', 'search_queries': ['Initial person identity']}
    return scout, state, section, search


def fake_responses(monkeypatch, scout, decisions):
    payloads = []
    iterator = iter(decisions)

    async def fake_llm(**kwargs):
        if kwargs['system_prompt'].startswith('You rewrite'):
            return json.dumps({'queries': []})
        if kwargs['system_prompt'].startswith('Extract evidence'):
            return json.dumps({'extracted_facts': [
                {'content': 'Full text finding', 'quote': 'Fictional evidence'}]})
        payloads.append(json.loads(kwargs['user_prompt'].splitlines()[-1]))
        return json.dumps(next(iterator))

    monkeypatch.setattr(scout, 'call_llm', fake_llm)
    return payloads


async def test_next_round_uses_new_evidence_and_reads_selected_page(monkeypatch):
    scout, state, section, search = setup_loop()
    payloads = fake_responses(monkeypatch, scout, [
        {'thought': 'Verify the candidate', 'new_facts': [
            {'content': 'Supported excerpt finding', 'docid': '1'},
            {'content': 'Invented source finding', 'docid': '999'}],
         'candidates': [{'name': 'Fictional Person'}], 'read_docids': ['1'],
         'queries': ['Fictional Person graduation'], 'done': False},
        {'thought': 'Finished', 'queries': [], 'done': True}])
    await scout.investigate(state, section)
    assert search.calls == [('Initial person identity', 5), ('Fictional Person graduation', 5)]
    assert search.reads == ['1']
    assert len(payloads) == 2 and len(payloads[1]['facts']) == 2
    assert payloads[1]['candidates'][0]['name'] == 'Fictional Person'
    assert 'Initial person identity'.casefold() in payloads[1]['searched_queries']
    assert all(f['docid'] == '1' for f in state['facts'])
    assert any(e['event'] == 'fact' and e['docid'] == '1' for e in scout.trace.events)
    assert [e['round'] for e in scout.trace.events if e['event'] == 'plan'] == [1, 2]


async def test_invalid_seed_queries_can_be_replanned(monkeypatch):
    scout, state, section, search = setup_loop()
    section['search_queries'] = ['[Candidate Name] biography']
    payloads = fake_responses(monkeypatch, scout, [
        {'queries': ['Concrete fictional clue'], 'done': False}, {'queries': [], 'done': True}])
    await scout.investigate(state, section)
    assert payloads[0]['results'] == []
    assert search.calls == [('Concrete fictional clue', 5)]


async def test_at_most_six_rounds(monkeypatch):
    scout, state, section, search = setup_loop()
    payloads = fake_responses(monkeypatch, scout, [
        {'queries': [f'entity{i} clue{i}'], 'done': False} for i in range(7)])
    await scout.investigate(state, section)
    assert len(payloads) == len(search.calls) == 6


@pytest.mark.parametrize('decision', [{'done': True, 'queries': ['unused new query']},
                                      {'done': False, 'queries': []}])
async def test_done_or_no_next_query_stops(monkeypatch, decision):
    scout, state, section, search = setup_loop()
    payloads = fake_responses(monkeypatch, scout, [decision])
    await scout.investigate(state, section)
    assert len(payloads) == len(search.calls) == 1


async def test_result_dedup_context_and_query_limits(monkeypatch):
    scout, state, section, _ = setup_loop()
    section['search_queries'] = ['first concrete clue', 'second concrete clue', 'unused third clue']
    for i in range(30):
        state['facts'].append({'content': f'Known fact {i}', 'source_url': f'corpus://old{i}'})
    calls = []

    async def search(query, count=10):
        calls.append((query, count))
        offset = 0 if len(calls) == 1 else 6
        rows = []
        for i in range(offset, offset + 8):
            url = f'corpus://{i}'
            scout.sources[url] = str(i)
            rows.append({'url': url, 'title': str(i), 'summary': 'x' * 500})
        return rows

    monkeypatch.setattr(scout, '_execute_search', search)
    payloads = fake_responses(monkeypatch, scout, [{'done': True}])
    await scout.investigate(state, section)
    assert len(calls) == 2 and all(count == 5 for _, count in calls)
    assert len(payloads[0]['results']) == 12
    assert len({r['docid'] for r in payloads[0]['results']}) == 12
    assert all(len(r['snippet']) == 260 for r in payloads[0]['results'])
    assert len(payloads[0]['facts']) == 25
    assert len(state['raw_sources']) == 12


async def test_near_duplicate_queries_and_expansions_are_skipped(monkeypatch):
    scout, _, _, search = setup_loop()
    expansions = []

    async def expand(**kwargs):
        expansions.append(kwargs)
        return json.dumps({'queries': ['fictional person river birthplace details', 'Unrelated monument opening']})

    monkeypatch.setattr(scout, 'call_llm', expand)
    await scout._execute_search('fictional person river birthplace')
    assert len(search.calls) == 2  # 4/5的词集重合，跳过第一条扩写。
    assert await scout._execute_search('birthplace river person fictional extra') == []
    assert len(expansions) == 1
    assert await scout._execute_search('Unrelated monument opening') == []


async def test_concurrent_queries_keep_shared_budget(monkeypatch):
    scout, _, _, search = setup_loop(max_searches=2)

    async def expand(**kwargs):
        await asyncio.sleep(0)
        return json.dumps({'queries': []})

    monkeypatch.setattr(scout, 'call_llm', expand)
    await asyncio.gather(*(scout._execute_search(f'entity{i} clue{i}') for i in range(10)))
    assert len(search.calls) == scout.trace.n_search == 2
    assert scout.trace.stop_reason == 'search_budget'


async def test_supplementary_research_reuses_loop_and_returns_to_writer(monkeypatch):
    scout, state, _, _ = setup_loop()
    state['phase'] = ResearchPhase.RE_RESEARCHING.value
    state['pending_search_queries'] = [f'evidence query {i}' for i in range(5)]
    seen = []

    async def loop(actual_state, section):
        assert actual_state is state
        seen.append(section)

    monkeypatch.setattr(scout, 'loop_section', loop)
    await scout.process(state)
    assert len(seen) == 1 and seen[0]['title'] == '补充核查'
    assert seen[0]['search_queries'] == [f'evidence query {i}' for i in range(3)]
    assert state['pending_search_queries'] == []
    assert state['phase'] == ResearchPhase.WRITING.value


async def test_older_versions_keep_original_section_research(monkeypatch):
    scout, state, section, _ = setup_loop(scout='original')
    seen = []

    async def original(self, actual_state, actual_section):
        seen.append((actual_state, actual_section))

    monkeypatch.setattr(s4_port.DeepScout, '_research_section', original)
    await scout.investigate(state, section)
    assert seen == [(state, section)]
