"""Scout共享检索补丁契约：虚构语料验证跨侦探复用、并发、可见性与拒绝日志，不调用模型。"""

import asyncio
from copy import deepcopy

import pytest

from app.agents.dr.flow_fixes import ResilientScout
from app.s4.deep_research_v2.state import create_initial_state
from app.trace import Trace
from app.versions import get_version


class FakeSearch:
    def __init__(self):
        self.calls = 0

    async def search(self, query, k=200):
        self.calls += 1
        await asyncio.sleep(0)
        return {'results': [{'docid': str(i), 'title': f'Fictional {i}',
                             'snippet': f'Fictional supporting text {i}', 'score': 100-i}
                            for i in range(1, 31)]}

    async def document(self, docid, max_tokens=None):
        return {'docid': docid, 'title': 'Fictional document', 'text': 'Fictional body evidence.'}


def make_scout(enabled=True):
    opts = deepcopy(get_version('v2.3').options)
    if enabled:
        opts.update(shared_search_cache=True, tool_audit=True)
    search, trace = FakeSearch(), Trace()
    scout = ResilientScout(None, trace, search, {}, opts)
    state = create_initial_state('Fictional research question', 'shared-test')
    return scout, state, search, trace


def test_patch_version_adds_only_cache_and_audit_options():
    assert get_version('v2.3.1').options == {
        **get_version('v2.3').options, 'shared_search_cache': True, 'tool_audit': True}


async def test_shared_cache_is_question_local():
    a, sa, search_a, _ = make_scout()
    b, sb, search_b, _ = make_scout()
    args = {'query': 'fictional editor kayak', 'reason': 'Find evidence'}
    await a.scout_tools(sa, 'scout-1').call('search', args)
    result = await b.scout_tools(sb, 'scout-1').call('search', args)
    assert search_a.calls == search_b.calls == 1
    assert not result.get('cache_reused')


async def test_failed_search_does_not_leave_duplicate_reservation_or_poison_cache():
    scout, state, search, trace = make_scout()
    original = search.search

    async def fail(query, k=200):
        raise RuntimeError('Fictional service failure')

    search.search = fail
    args = {'query': 'fictional editor kayak', 'reason': 'Find evidence'}
    with pytest.raises(RuntimeError):
        await scout.scout_tools(state, 'scout-1').call('search', args)
    search.search = original
    result = await scout.scout_tools(state, 'scout-2').call('search', args)
    assert result.get('results') and search.calls == 1
    assert any(e.get('kind') == 'tool_call' and e.get('status') == 'exception'
               for e in trace.events)


async def test_cancelled_search_releases_waiting_duplicate():
    scout, state, search, trace = make_scout()
    entered, release = asyncio.Event(), asyncio.Event()
    original = search.search

    async def wait(query, k=200):
        entered.set()
        await release.wait()
        return await original(query, k)

    search.search = wait
    args = {'query': 'fictional editor kayak', 'reason': 'Find evidence'}
    first = asyncio.create_task(scout.scout_tools(state, 'scout-1').call('search', args))
    await asyncio.wait_for(entered.wait(), 1)
    second = asyncio.create_task(scout.scout_tools(state, 'scout-2').call('search', args))
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    result = await asyncio.wait_for(second, 1)
    assert result.get('results') and search.calls == 1
    assert any(e.get('status') == 'cancelled' for e in trace.events)


async def test_exact_query_reuses_results_and_supports_local_page_and_read():
    scout, state, search, trace = make_scout()
    first, second = scout.scout_tools(state, 'scout-1'), scout.scout_tools(state, 'scout-2')
    args = {'query': 'fictional editor kayak', 'reason': 'Find an obituary'}
    await first.call('search', args)
    result = await second.call('search', args)
    assert not result.get('error')
    assert result['cache_reused'] is True
    assert result['results'][0]['docid'] == '1'
    assert search.calls == 1 and trace.n_search == 1
    assert scout._budget['search_count'] == 1
    page = await second.call('read_search_results', {
        'search_id': result['search_id'], 'offset': 21, 'limit': 1, 'reason': 'Inspect deeper result'})
    assert page['results'][0]['docid'] == '21'
    body = await second.call('read_document', {
        'docid': '6', 'offset': 1, 'limit': 1, 'reason': 'Read visible title'})
    assert 'Fictional body' in body['text']
    assert '30' not in second.documents and '30' not in trace.retrieved


async def test_concurrent_identical_queries_execute_only_once():
    scout, state, search, trace = make_scout()
    tools = [scout.scout_tools(state, f'scout-{i}') for i in range(3)]
    results = await asyncio.gather(*(t.call('search', {
        'query': 'fictional editor kayak', 'reason': 'Find evidence'}) for t in tools))
    assert all(r.get('results') for r in results)
    assert search.calls == 1 and trace.n_search == 1
    assert sum(bool(r.get('cache_reused')) for r in results) == 2


async def test_same_query_cache_is_available_after_unique_search_budget_exhausted():
    scout, state, search, trace = make_scout()
    scout.opts['max_searches'] = 1
    first, second = scout.scout_tools(state, 'scout-1'), scout.scout_tools(state, 'scout-2')
    args = {'query': 'fictional editor kayak', 'reason': 'Find evidence'}
    await first.call('search', args)
    assert (await second.call('search', args)).get('cache_reused') is True
    assert search.calls == 1


async def test_tool_audit_records_invalid_parameters_and_success_without_counting_as_search():
    scout, state, search, trace = make_scout()
    tools = scout.scout_tools(state, 'scout-1')
    await tools.call('search', {'query': 'fictional editor kayak'})
    await tools.call('search', {'query': 'fictional editor kayak', 'reason': 'Find evidence'})
    audits = [e for e in trace.events if e.get('kind') == 'tool_call']
    assert len(audits) == 2
    assert audits[0]['status'] == 'rejected'
    assert audits[0]['arguments'] == {'query': 'fictional editor kayak'}
    assert audits[0]['error']
    assert audits[1]['status'] == 'success' and audits[1]['result_count'] == 5
    assert tools.used == 2 and trace.n_search == 1


async def test_near_duplicate_policy_is_unchanged_and_rejection_is_audited():
    scout, state, search, trace = make_scout()
    first, second = scout.scout_tools(state, 'scout-1'), scout.scout_tools(state, 'scout-2')
    await first.call('search', {'query': 'fictional editor kayak newsletter', 'reason': 'Find evidence'})
    result = await second.call('search', {
        'query': 'fictional editor kayak newsletter obituary', 'reason': 'Try another angle'})
    assert result.get('error') and search.calls == 1
    assert any(e.get('kind') == 'tool_call' and e.get('status') == 'rejected'
               and e.get('agent') == 'scout-2' for e in trace.events)


async def test_legacy_v23_still_rejects_duplicates_without_new_audit_events():
    scout, state, search, trace = make_scout(enabled=False)
    first, second = scout.scout_tools(state, 'scout-1'), scout.scout_tools(state, 'scout-2')
    args = {'query': 'fictional editor kayak', 'reason': 'Find evidence'}
    await first.call('search', args)
    assert (await second.call('search', args)).get('error')
    assert search.calls == 1
    assert not any(e.get('kind') == 'tool_call' for e in trace.events)
