"""v2.3.2虚构语料验证按需查看第6–10名摘要；不读取金标、不调用模型。"""

from copy import deepcopy

from app.agents.dr.flow_fixes import ResilientScout
from app.s4.deep_research_v2.state import create_initial_state
from app.trace import Trace
from app.versions import get_version


class FakeSearch:
    def __init__(self):
        self.calls = []

    async def search(self, query, k=200):
        self.calls.append(query)
        return {'results': [{'docid': str(i), 'title': f'Fictional newsletter {i}',
                             'snippet': f'Fictional excerpt {i}', 'score': 100-i}
                            for i in range(1, 31)]}

    async def document(self, docid, max_tokens=None):
        return {'docid': docid, 'title': 'Fictional text', 'text': 'Fictional supporting evidence.'}


def make_tools():
    options = deepcopy(get_version('v2.3.1').options)
    options['adaptive_result_review'] = True
    trace, search = Trace(), FakeSearch()
    scout = ResilientScout(None, trace, search, {}, options)
    state = create_initial_state('Fictional question', 'result-review')
    return scout.scout_tools(state, 'scout-1'), search, trace


async def test_after_two_searches_next_search_reviews_existing_six_to_ten():
    tools, search, trace = make_tools()
    first = await tools.call('search', {'query': 'fictional editor kayak', 'reason': 'Find newsletter'})
    second = await tools.call('search', {'query': 'different wildlife migration', 'reason': 'Find research'})
    assert [r['rank'] for r in first['results']] == [1, 2, 3, 4, 5]
    result = await tools.call('search', {'query': 'unrelated award organization', 'reason': 'Find award'})
    assert len(search.calls) == 2 and trace.n_search == 2
    assert result['redirected_from'] == 'search'
    assert result['search_id'] == second['search_id']
    assert [r['rank'] for r in result['results']] == [6, 7, 8, 9, 10]
    assert '10' in tools.documents and '11' not in tools.documents
    assert tools.used == 3
    audit = [e for e in trace.events if e.get('kind') == 'tool_call'][-1]
    assert audit['tool'] == 'search' and audit['executed_tool'] == 'read_search_results'
    assert audit['redirect_reason'] == 'two_searches_without_page_or_read'


async def test_short_result_lists_do_not_block_new_searches():
    tools, search, trace = make_tools()

    async def short_search(query, k=200):
        search.calls.append(query)
        return {'results': [{'docid': '1', 'title': 'Fictional title',
                             'snippet': 'Fictional text', 'score': 1}]}

    search.search = short_search
    for query in ['fictional editor kayak', 'different wildlife migration', 'unrelated award organization']:
        result = await tools.call('search', {'query': query, 'reason': 'Find evidence'})
        assert not result.get('error') and not result.get('redirected_from')
    assert len(search.calls) == 3


async def test_near_duplicate_returns_actionable_page_instead_of_empty_rejection():
    tools, search, trace = make_tools()
    first = await tools.call('search', {
        'query': 'fictional editor kayak newsletter', 'reason': 'Find newsletter'})
    result = await tools.call('search', {
        'query': 'fictional editor kayak newsletter obituary', 'reason': 'Refine query'})
    assert not result.get('error')
    assert result['redirected_from'] == 'search'
    assert result['search_id'] == first['search_id']
    assert [r['rank'] for r in result['results']] == [6, 7, 8, 9, 10]
    assert len(search.calls) == 1


async def test_successful_read_resets_consecutive_search_trigger():
    tools, search, trace = make_tools()
    await tools.call('search', {'query': 'fictional editor kayak', 'reason': 'Find newsletter'})
    await tools.call('search', {'query': 'different wildlife migration', 'reason': 'Find research'})
    await tools.call('read_document', {'docid': '6', 'offset': 1, 'limit': 1, 'reason': 'Check title'})
    result = await tools.call('search', {'query': 'unrelated award organization', 'reason': 'Find award'})
    assert not result.get('redirected_from') and len(search.calls) == 3


async def test_explicit_page_resets_trigger_and_is_not_shown_again():
    tools, search, trace = make_tools()
    first = await tools.call('search', {'query': 'fictional editor kayak', 'reason': 'Find newsletter'})
    await tools.call('read_search_results', {
        'search_id': first['search_id'], 'offset': 6, 'limit': 5, 'reason': 'Inspect more titles'})
    result = await tools.call('search', {'query': 'different wildlife migration', 'reason': 'Find research'})
    assert not result.get('redirected_from') and len(search.calls) == 2


def test_v232_adds_only_adaptive_review_and_keeps_six_hundred_seconds():
    assert get_version('v2.3.2').options == {
        **get_version('v2.3.1').options, 'adaptive_result_review': True}
    assert get_version('v2.3.2').options['time_budget'] == 600
