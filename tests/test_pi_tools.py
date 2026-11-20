"""S17虚构语料检查PiTools的深排缓存、可见召回、翻页、分行阅读和计数；不访问网络或模型。"""

import pytest

from app.agents.react import PiTools, doc_lines
from app.trace import Trace


class FakeSearch:
    """只提供40条虚构命中和240词正文，所有数据与验收题集无关。"""

    def __init__(self):
        self.searches = []
        self.reads = []

    async def search(self, query, k=5):
        self.searches.append((query, k))
        return {'results': [
            {'docid': str(i), 'title': f'Fictional title {i}', 'score': 100-i,
             'snippet': f'Fictional excerpt {i} ' + 'x'*1400}
            for i in range(1, 41)]}

    async def document(self, docid, max_tokens=None):
        self.reads.append((docid, max_tokens))
        return {'docid': docid, 'title': f'Fictional title {docid}',
                'text': ' '.join(f'word{i}' for i in range(240))}


def make_tools():
    search, trace = FakeSearch(), Trace()
    return PiTools(search, trace, search_depth=200, page_chars=1200,
                   title_ranks=15, document_tokens=8000), search, trace


async def test_pi_search_shows_five_excerpts_and_fifteen_titles():
    tools, search, trace = make_tools()
    result = await tools.call('search', {'reason':'Find supporting evidence', 'query':'fictional topic'})
    assert result['search_id'] == 's1'
    assert [r['rank'] for r in result['results']] == [1, 2, 3, 4, 5]
    assert all(len(r['excerpt']) <= 1200 for r in result['results'])
    assert len(result['more_titles']) == 15
    assert result['more_titles'][0] == '#6 [6] Fictional title 6'
    assert result['more_titles'][-1] == '#20 [20] Fictional title 20'
    assert search.searches == [('fictional topic', 200)]
    assert trace.n_search == 1 and trace.retrieved == {'1','2','3','4','5'}


async def test_pi_page_is_one_based_cached_and_marks_only_exposed_excerpts():
    tools, search, trace = make_tools()
    await tools.call('search', {'reason':'Find evidence', 'query':'fictional topic'})
    result = await tools.call('read_search_results', {
        'reason':'Inspect the next ranked candidates', 'search_id':'s1', 'offset':6, 'limit':3})
    assert [r['rank'] for r in result['results']] == [6, 7, 8]
    assert all(len(r['excerpt']) <= 1200 for r in result['results'])
    assert len(search.searches) == 1 and trace.n_search == 1
    assert trace.retrieved == {str(i) for i in range(1, 9)}
    pages = [e for e in trace.events if e['event'] == 'search' and e.get('cached')]
    assert len(pages) == 1 and pages[0]['query'] == '翻看 s1 第 6 名起'


async def test_pi_paging_limits_twenty_and_rejects_unknown_search():
    tools, search, trace = make_tools()
    await tools.call('search', {'reason':'Find evidence', 'query':'fictional topic'})
    page = await tools.call('read_search_results', {
        'reason':'Inspect more candidates', 'search_id':'s1', 'offset':6, 'limit':100})
    assert len(page['results']) == 20
    before = trace.n_search
    bad = await tools.call('read_search_results', {
        'reason':'Inspect candidates', 'search_id':'not-real', 'offset':1, 'limit':3})
    assert bad.get('error') and trace.n_search == before
    assert len(search.searches) == 1


def test_pi_doc_lines_packs_short_lines_and_preserves_word_order():
    text = ' '.join(f'word{i}' for i in range(170))
    lines = doc_lines(text)
    assert len(lines) == 3
    assert all(len(line.split()) <= 80 for line in lines)
    assert ' '.join(lines).split() == text.split()
    assert doc_lines('alpha\nbeta\n\ngamma') == ['alpha beta gamma']


async def test_pi_reads_title_only_candidate_by_lines_then_uses_cache():
    tools, search, trace = make_tools()
    await tools.call('search', {'reason':'Find evidence', 'query':'fictional topic'})
    first = await tools.call('read_document', {
        'reason':'Verify a promising title', 'docid':'6', 'offset':1, 'limit':1})
    assert first['offset'] == 1 and first['next_offset'] == 2
    assert 'word0' in first['text'] and 'word79' in first['text']
    assert 'word80' not in first['text']
    second = await tools.call('read_document', {
        'reason':'Continue reading', 'docid':'6', 'offset':2, 'limit':2})
    assert 'word80' in second['text'] and 'word239' in second['text']
    assert second['next_offset'] is None
    assert search.reads == [('6', None)]
    assert trace.n_read == 2 and '6' in trace.retrieved and '7' not in trace.retrieved
    assert all(e.get('span') for e in trace.events if e['event'] == 'read')


async def test_pi_rejects_invisible_doc_and_missing_reason_without_io():
    tools, search, trace = make_tools()
    bad = await tools.call('search', {'query':'fictional topic'})
    assert bad.get('error') and not search.searches
    await tools.call('search', {'reason':'Find evidence', 'query':'fictional topic'})
    unseen = await tools.call('read_document', {
        'reason':'Read candidate', 'docid':'40', 'offset':1, 'limit':1})
    assert unseen.get('error') and not search.reads
    assert trace.n_read == 0 and '40' not in trace.retrieved


def make_scout():
    from app.agents.dr.flow_fixes import ResilientScout
    from app.s4.deep_research_v2.state import create_initial_state
    from app.versions import get_version
    scout = ResilientScout(None, Trace(), FakeSearch(), {}, get_version('v2.1').options)
    return scout, create_initial_state('Fictional question', 'pi-test')


def test_v21_distinct_english_facts_survive_and_repeated_text_is_deduplicated():
    scout, state = make_scout()
    documents = {str(i): {'docid':str(i), 'source_url':f'corpus://{i}'} for i in range(1, 5)}
    scout._store_loop_facts(state, {'id':'demo'}, [
        {'content':'Fictional claim', 'docid':'1'},
        {'content':'Other fictional claim', 'docid':'2'},
        {'content':'  FICTIONAL   claim  ', 'docid':'3'},
        {'content':'Fictional claim is not supported', 'docid':'4'},
    ], documents)
    assert [fact['docid'] for fact in state['facts']] == ['1','2','4']
    assert scout._compute_fact_fingerprint('Dose 10 mg') != scout._compute_fact_fingerprint('Dose 20 mg')


@pytest.mark.parametrize('version', ['v1.9.1', 'v2.0'])
def test_older_versions_keep_original_fact_fingerprint(version):
    from app.agents.dr.flow_fixes import ResilientScout
    from app.s4.deep_research_v2.agents.scout import DeepScout
    from app.versions import get_version
    scout = ResilientScout(None, Trace(), FakeSearch(), {}, get_version(version).options)
    for text in ('Fictional claim', 'Other fictional claim', '中文事实 123'):
        assert scout._compute_fact_fingerprint(text) == DeepScout._compute_fact_fingerprint(scout, text)


async def test_pi_scout_shared_unique_budget_and_body_cache_preserve_chunk_events():
    import asyncio
    scout, state = make_scout()
    first, second = scout.scout_tools(state, 'scout-1'), scout.scout_tools(state, 'scout-2')
    await first.call('search', {'reason':'Find candidates', 'query':'fictional alpha identity'})
    await second.call('search', {'reason':'Find other evidence', 'query':'different beta history'})
    args = {'reason':'Verify title', 'docid':'6', 'offset':1, 'limit':1}
    outputs = await asyncio.gather(first.call('read_document', args), second.call('read_document', args))
    assert all(o.get('text') for o in outputs)
    assert scout.search.reads == [('6', None)]
    assert scout._budget['reads'] == {'6'} and scout.trace.n_read == 2
    assert all(e['title_only'] for e in scout.trace.events if e['event'] == 'read')
    assert set(first.documents) == {'1','2','3','4','5','6'}
    assert 'word80' not in str(first.read_text)
    assert {str(source['docid']) for source in state['raw_sources']} == {'1','2','3','4','5','6'}
    scout.opts['max_reads'] = 1
    assert (await first.call('read_document', {**args, 'docid':'7'})).get('error')
    assert not (await first.call('read_document', {**args, 'offset':2})).get('error')


async def test_pi_scout_search_budget_does_not_block_cached_page_or_bad_reason_reserve():
    scout, state = make_scout()
    tool = scout.scout_tools(state, 'scout-1')
    assert (await tool.call('search', {'query':'fictional alpha identity'})).get('error')
    assert scout._budget['search_count'] == 0
    await tool.call('search', {'reason':'Find candidates', 'query':'fictional alpha identity'})
    scout._budget['search_count'] = 50
    assert (await tool.call('search', {'reason':'Other angle', 'query':'different beta history'})).get('error')
    page = await tool.call('read_search_results', {'reason':'Inspect cached evidence',
                          'search_id':'s1', 'offset':21, 'limit':2})
    assert len(page['results']) == 2 and scout.trace.n_search == 1
    assert '21' in tool.documents and '23' not in tool.documents
    assert {'search','read_search_results','read_document'} == {s['function']['name'] for s in tool.definitions()}


async def test_pi_read_cap_advances_only_complete_returned_lines():
    tools, search, trace = make_tools()
    tools.document_tokens = 170
    await tools.call('search', {'reason':'Find candidates', 'query':'fictional topic'})
    chunk = await tools.call('read_document', {'reason':'Read evidence', 'docid':'6', 'offset':1, 'limit':3})
    assert chunk['next_offset'] == 2
    import tiktoken
    assert len(tiktoken.get_encoding('cl100k_base').encode(chunk['text'])) <= 170
    bad = await tools.call('read_document', {'reason':'Read evidence', 'docid':'6', 'offset':99, 'limit':1})
    assert bad.get('error') and trace.n_read == 1


async def test_pi_react_initial_and_supplement_use_three_schemas_and_citation_repair():
    import json
    from copy import deepcopy
    from types import SimpleNamespace
    from app.agents import s4_port

    def reply(content=None, name=None, args=None):
        calls = [SimpleNamespace(id='fake', function=SimpleNamespace(
            name=name, arguments=json.dumps(args)))] if name else None
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls))])

    class Model:
        def __init__(self):
            self.requests = []
            self.outcomes = [
                reply(name='search', args={'reason':'Locate fictional clues', 'query':'fictional alpha identity'}),
                reply(name='read_document', args={'reason':'Verify title clue', 'docid':'6', 'offset':1, 'limit':1}),
                reply('Findings:\n- Fictional claim [999]\nCandidates:\nNone'),
                reply('Findings:\n- Fictional claim [6]\nCandidates:\nNone'),
                reply(name='search', args={'reason':'Resolve another clue', 'query':'different beta history'}),
                reply(name='read_search_results', args={'reason':'Inspect deeper ranks', 'search_id':'s1', 'offset':21, 'limit':2}),
                reply('Findings:\n- Other fictional claim [21]\nCandidates:\nNone'),
            ]

        async def chat(self, messages, **kwargs):
            self.requests.append((deepcopy(messages), kwargs))
            return self.outcomes.pop(0)

    scout, state = make_scout()
    state['facts'] = s4_port.FactList(scout.trace, scout.sources)
    scout.llm = Model()
    token = s4_port.CURRENT_AGENT.set('scout-1')
    try:
        for sid in ('sec_1', 'supplementary_1'):
            await scout.investigate(state, {'id':sid, 'title':'Fictional clue',
                'description':'Verify a clue', 'search_queries':[], 'status':'pending'})
    finally:
        s4_port.CURRENT_AGENT.reset(token)
    assert [f['docid'] for f in state['facts']] == ['6','21']
    assert scout.trace.n_search == 2 and scout.trace.n_read == 1
    assert scout._budget['search_count'] == 2
    assert any(e.get('cached') for e in scout.trace.events)
    for messages, kwargs in scout.llm.requests:
        if kwargs.get('tools'):
            assert {t['function']['name'] for t in kwargs['tools']} == {'search','read_search_results','read_document'}
            assert 'starting at offset=1' in messages[0]['content']
    repair_payload = json.loads(scout.llm.requests[3][0][1]['content'])
    assert repair_payload['read_documents']['6'][0]['offset'] == 1
    assert 'word80' not in json.dumps(repair_payload)


async def test_pi_cancellation_propagates_without_inventing_read_event():
    import asyncio
    tools, search, trace = make_tools()
    await tools.call('search', {'reason':'Find candidates', 'query':'fictional topic'})

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    search.document = cancelled
    with pytest.raises(asyncio.CancelledError):
        await tools.call('read_document', {'reason':'Read title', 'docid':'6', 'offset':1, 'limit':1})
    assert trace.n_read == 0 and not tools.bodies
