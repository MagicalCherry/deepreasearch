"""虚构场景验证v1.6.1保留状态重试、正文缓存、空循环退出及最后稿审核；不调用真实服务。"""

import asyncio
from copy import deepcopy
import json

import pytest

from app.agents import s4_port
from app.agents.dr import flow_fixes
from app.agents.dr.flow_fixes import ResilientScout, retry_stage
from app.llm import LLMError
from app.s4.deep_research_v2.state import ResearchPhase, create_initial_state
from app.trace import Trace
from app.versions import get_version


def test_v161_adds_only_flow_fix_option():
    previous = deepcopy(get_version('v1.6').options)
    assert get_version('v1.6.1').options == {**previous, 'flow_fixes': True}
    assert get_version('v1.6').options == previous


class Search:
    def __init__(self, empty=False):
        self.searches, self.reads = [], []
        self.empty = empty

    async def search(self, query, k=5):
        self.searches.append(query)
        await asyncio.sleep(0)
        return {'results': [] if self.empty else [{'docid': '1', 'title': 'Fictional page',
            'url': 'corpus://1', 'snippet': 'Fictional evidence'}]}

    async def document(self, docid, max_tokens=None):
        self.reads.append(docid)
        return {'docid': docid, 'title': 'Fictional page', 'text': 'Fictional evidence from a page.'}


def scout_state(**changes):
    trace, search = Trace(), Search()
    opts = {**get_version('v1.6.1').options, **changes}
    scout = ResilientScout(None, trace, search, {}, opts)
    state = create_initial_state('Fictional question', 'retry-test')
    state['phase'] = ResearchPhase.PLANNING.value
    state['facts'] = s4_port.FactList(trace, scout.sources)
    state['outline'] = [{'id': 'sec_1', 'title': 'Fictional identity',
                         'status': 'pending', 'search_queries': ['Initial identity clue']}]
    return scout, state, search, opts


async def test_scout_retries_pending_analysis_after_budget_is_spent(monkeypatch):
    scout, state, search, opts = scout_state(max_searches=1)
    calls = []

    async def fake_llm(**kwargs):
        if kwargs['system_prompt'].startswith('You rewrite'):
            return json.dumps({'queries': []})
        calls.append(json.loads(kwargs['user_prompt'].splitlines()[-1]))
        if len(calls) == 1:
            raise ValueError('Fictional malformed response')
        return json.dumps({'done': True, 'new_facts': [{'content': 'Retained evidence', 'docid': '1'}]})

    monkeypatch.setattr(scout, 'call_llm', fake_llm)
    await retry_stage(scout, state, 'scout', '侦探', opts)
    assert search.searches == ['Initial identity clue']
    assert len(calls) == 2 and calls[0]['results'] == calls[1]['results']
    assert state['facts'][0]['content'] == 'Retained evidence'
    assert scout._budget['search_count'] == scout.trace.n_search == 1
    assert any(e.get('kind') == 'stage_error' and e['will_retry'] for e in scout.trace.events)


async def test_read_extraction_retry_uses_cached_text_and_keeps_facts(monkeypatch):
    scout, state, search, opts = scout_state(max_searches=1)
    analysis_calls, read_calls = [], []

    async def fake_llm(**kwargs):
        if kwargs['system_prompt'].startswith('You rewrite'):
            return json.dumps({'queries': []})
        if kwargs['system_prompt'].startswith('Extract evidence'):
            read_calls.append(kwargs)
            if len(read_calls) == 1:
                raise ValueError('Fictional read extraction failure')
            return json.dumps({'extracted_facts': [{'content': 'Full text fact', 'quote': 'Fictional evidence'}]})
        analysis_calls.append(kwargs)
        return json.dumps({'done': True, 'read_docids': ['1'],
                           'new_facts': [{'content': 'Excerpt fact', 'docid': '1'}]})

    monkeypatch.setattr(scout, 'call_llm', fake_llm)
    await retry_stage(scout, state, 'scout', '侦探', opts)
    assert len(analysis_calls) == 1 and len(read_calls) == 2
    assert search.reads == ['1'] and scout.trace.n_read == 1
    assert len(state['facts']) == 2
    assert {f['source_url'] for f in state['facts']} == {'corpus://1'}
    assert scout._budget['reads'] == {'1'}


async def test_empty_results_stop_before_analysis(monkeypatch):
    scout, state, search, _ = scout_state()
    search.empty = True
    calls = []

    async def fake_llm(**kwargs):
        calls.append(kwargs['system_prompt'])
        return json.dumps({'queries': []})

    monkeypatch.setattr(scout, 'call_llm', fake_llm)
    await scout.process(state)
    assert len(calls) == 1 and calls[0].startswith('You rewrite')
    assert len(search.searches) == 1
    assert any(e.get('reason') == 'no_new_results' for e in scout.trace.events)


async def test_duplicate_queries_do_not_trigger_empty_analysis(monkeypatch):
    scout, state, search, _ = scout_state()
    scout._budget['queries'].add('initial identity clue')
    scout._budget['originals'].add('initial identity clue')

    async def forbidden(**kwargs):
        pytest.fail('重复查询没有新结果，不应调用模型')

    monkeypatch.setattr(scout, 'call_llm', forbidden)
    await scout.process(state)
    assert search.searches == []


async def test_repeated_documents_stop_without_second_analysis(monkeypatch):
    scout, state, search, _ = scout_state()
    analyses = []

    async def fake_llm(**kwargs):
        if kwargs['system_prompt'].startswith('You rewrite'):
            return json.dumps({'queries': []})
        analyses.append(kwargs)
        return json.dumps({'done': False, 'queries': ['Boreal sculpture timeline']})

    monkeypatch.setattr(scout, 'call_llm', fake_llm)
    await scout.process(state)
    assert len(search.searches) == 2 and len(analyses) == 1


async def test_initial_placeholder_repair_is_still_allowed_once(monkeypatch):
    scout, state, search, _ = scout_state()
    state['outline'][0]['search_queries'] = ['[Candidate Name] biography']
    modes = []

    async def fake_llm(**kwargs):
        if kwargs['system_prompt'].startswith('You rewrite'):
            return json.dumps({'queries': []})
        payload = json.loads(kwargs['user_prompt'].splitlines()[-1])
        modes.append(payload['mode'])
        return json.dumps({'queries': ['Concrete identity clue'], 'done': False}
                          if payload['mode'] == 'repair_initial_queries' else {'done': True})

    monkeypatch.setattr(scout, 'call_llm', fake_llm)
    await scout.process(state)
    assert modes == ['repair_initial_queries', 'analyze_results']
    assert search.searches == ['Concrete identity clue']


@pytest.fixture
def fake_pipeline(monkeypatch):
    """隔离网络及角色模型调用，验证调度顺序、失败回滚和最终提交的稿件。"""
    log, seen, clients = [], {}, []
    behavior = {'routing': 'pass', 'fail_writer_once': False}

    class Client:
        def __init__(self, **kwargs):
            clients.append(self)
            self.closed = False

        async def close(self):
            self.closed = True

    async def step(agent, state, lane, role):
        log.append((lane, role))
        seen['state'] = state
        if lane == 'planner':
            state['outline'] = [{'id': 'sec_1', 'title': 'Demo', 'status': 'pending', 'search_queries': ['demo clue']}]
            state['phase'] = ResearchPhase.PLANNING.value
        elif lane == 'scout' and role == '侦探':
            agent.sources['corpus://1'] = '1'
            state['facts'].append({'content': 'Fictional finding', 'source_url': 'corpus://1'})
            agent._budget['search_count'] = agent.trace.n_search = 50
            state['phase'] = ResearchPhase.RESEARCHING.value
        elif lane == 'scout':
            state['phase'] = ResearchPhase.WRITING.value
        elif lane == 'writer':
            count = sum(x[0] == 'writer' for x in log)
            if behavior['fail_writer_once'] and count == 1:
                state['final_report'] = 'Partial broken draft'
                state['references'].append({'url': 'corpus://invalid'})
                state['phase'] = ResearchPhase.REVIEWING.value
                raise ValueError('Fictional invalid writer content')
            assert state['phase'] in (ResearchPhase.WRITING.value, ResearchPhase.REVISING.value)
            assert not state['references']
            state['final_report'] = f'Draft {count}'
            state['phase'] = ResearchPhase.REVIEWING.value
        elif lane == 'critic':
            seen.setdefault('reviewed', []).append(state['final_report'])
            state['quality_score'] = 8 if behavior['routing'] == 'pass' else 3
            state['unresolved_issues'] = 0 if behavior['routing'] == 'pass' else 1
            if behavior['routing'] == 'pass':
                state['phase'] = ResearchPhase.COMPLETED.value
            else:
                state['iteration'] += 1
                state['phase'] = (ResearchPhase.RE_RESEARCHING.value if behavior['routing'] == 'research'
                                  else ResearchPhase.REVISING.value)
                state['pending_search_queries'] = ['Missing fictional fact']
        return state

    async def extract(question, state, llm, trace, sources):
        assert state['final_report'] == seen['reviewed'][-1]
        assert state['facts'][0]['content'] == 'Fictional finding'
        assert sources == {'corpus://1': '1'}
        seen['extracted'] = state['final_report']
        return 'Explanation: Demo.\nExact Answer: Demo\nConfidence: 20%'

    monkeypatch.setattr(s4_port, 'LLM', Client)
    monkeypatch.setattr(s4_port, 'SearchClient', Client)
    monkeypatch.setattr(flow_fixes, '_step', step)
    monkeypatch.setattr(flow_fixes, '_extract', extract)
    return behavior, log, seen, clients


async def test_writer_retry_retains_facts_sources_and_budget(fake_pipeline):
    behavior, log, seen, clients = fake_pipeline
    behavior['fail_writer_once'] = True
    trace = Trace()
    await flow_fixes.run('Fictional question', trace, get_version('v1.6.1').options)
    assert sum(lane == 'planner' for lane, _ in log) == 1
    assert sum(lane == 'scout' for lane, _ in log) == 1
    assert sum(lane == 'writer' for lane, _ in log) == 2
    assert trace._dr_budget['search_count'] == trace.n_search == 50
    assert seen['extracted'] == 'Draft 2' and not seen['state']['references']
    assert len(clients) == 2 and all(c.closed for c in clients)


@pytest.mark.parametrize('limit', [1, 3])
async def test_final_draft_is_reviewed_even_at_iteration_limit(fake_pipeline, limit):
    behavior, log, seen, _ = fake_pipeline
    behavior['routing'] = 'revise'
    trace = Trace()
    await flow_fixes.run('Fictional question', trace, {**get_version('v1.6.1').options, 'max_iterations': limit})
    assert sum(lane == 'writer' for lane, _ in log) == limit
    assert len(seen['reviewed']) == limit
    assert seen['extracted'] == f'Draft {limit}'
    assert trace.stop_reason == 'review_budget'
    assert all(e['verdict'] == 'fail' for e in trace.events if e['event'] == 'verify')


async def test_supplement_without_new_evidence_does_not_rewrite(fake_pipeline):
    behavior, log, seen, _ = fake_pipeline
    behavior['routing'] = 'research'
    trace = Trace()
    await flow_fixes.run('Fictional question', trace, get_version('v1.6.1').options)
    assert sum(lane == 'writer' for lane, _ in log) == 1
    assert sum(role == '补充检索' for _, role in log) == 1
    assert trace.stop_reason == 'no_new_evidence'
    assert seen['extracted'] == 'Draft 1'


@pytest.mark.parametrize('error', [LLMError('arrearage', 'offline'), asyncio.CancelledError()])
async def test_fatal_and_cancelled_operations_are_not_retried(error):
    calls = []

    async def fail():
        calls.append(1)
        raise error

    with pytest.raises(type(error)):
        await flow_fixes.retry_operation(fail, Trace(), 'writer', 2)
    assert len(calls) == 1


async def test_invalid_critic_result_raises_instead_of_spinning(monkeypatch):
    critic = flow_fixes.ValidatedCritic(None, Trace(), get_version('v1.6.1').options)

    async def invalid(self, state):
        return {'overall_assessment': {'verdict': 'pass', 'quality_score': 1}, 'issues': []}

    monkeypatch.setattr(flow_fixes.DRCritic, '_review_content', invalid)
    with pytest.raises(ValueError, match='审核未返回有效'):
        await critic._review_content(create_initial_state('Fictional question', 'invalid-review'))


async def test_failed_critic_rolls_back_partial_feedback_before_retry(monkeypatch):
    critic = flow_fixes.ValidatedCritic(None, Trace(), get_version('v1.6.1').options)
    state = create_initial_state('Fictional question', 'critic-retry')
    state['phase'] = ResearchPhase.REVIEWING.value
    state['final_report'] = 'Retained draft'
    state['facts'] = [{'content': 'Retained evidence'}]
    calls = []

    async def step(agent, actual, lane, role):
        calls.append(1)
        assert actual['iteration'] == 0 and actual['critic_feedback'] == []
        if len(calls) == 1:
            actual['iteration'] = 1
            actual['critic_feedback'].append({'description': 'Partial review'})
            raise ValueError('Fictional review error')
        actual['phase'] = ResearchPhase.COMPLETED.value
        return actual

    monkeypatch.setattr(flow_fixes, '_step', step)
    await retry_stage(critic, state, 'critic', '核查', get_version('v1.6.1').options)
    assert len(calls) == 2 and state['final_report'] == 'Retained draft'
    assert state['facts'] == [{'content': 'Retained evidence'}]


async def test_repeated_stage_failure_is_bounded():
    calls, trace = [], Trace()

    async def fail():
        calls.append(1)
        raise ValueError('Fictional persistent error')

    with pytest.raises(ValueError):
        await flow_fixes.retry_operation(fail, trace, 'writer', 2)
    assert len(calls) == 3
    assert [e['will_retry'] for e in trace.events] == [True, True, False]
