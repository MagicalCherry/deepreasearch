"""离线验证v1.4并发搜索预算、查询去重、文档选择限制及正文原文片段校验；不调用真实服务。"""

import asyncio
import json

from app.agents.dr.team import DRScout
from app.trace import Trace


def options(**changes):
    return {'expand': 2, 'analysis': 'hypothesis', 'read_docs': True,
            'max_searches': 50, 'max_reads': 8, 'doc_max_tokens': 8000, **changes}


class FakeSearch:
    def __init__(self):
        self.searches = []
        self.reads = []

    async def search(self, query, k=10):
        self.searches.append(query)
        await asyncio.sleep(0)
        return {'results': [{'docid': '1', 'url': 'https://example.test/1',
                             'title': 'Demo', 'snippet': 'Fictional evidence'}]}

    async def document(self, docid, max_tokens=None):
        self.reads.append((docid, max_tokens))
        await asyncio.sleep(0)
        return {'docid': docid, 'title': 'Demo', 'text': 'Fictional evidence copied from document.'}


async def fake_expansion(**kwargs):
    await asyncio.sleep(0)
    return json.dumps({'queries': ['fictional alternate angle', 'fictional different clue']})


async def test_concurrent_searches_share_actual_call_budget(monkeypatch):
    trace, search = Trace(), FakeSearch()
    scout = DRScout(None, trace, search, {}, options(max_searches=4))
    monkeypatch.setattr(scout, 'call_llm', fake_expansion)
    await asyncio.gather(*(scout._execute_search(f'Fictional query {i}') for i in range(12)))
    assert len(search.searches) == trace.n_search == 4
    assert trace.stop_reason == 'search_budget'
    # 同题新建Scout（如整题重试）也不能重新获得预算。
    retry = DRScout(None, trace, search, {}, options(max_searches=4))
    monkeypatch.setattr(retry, 'call_llm', fake_expansion)
    assert await retry._execute_search('another fictional search') == []
    assert len(search.searches) == 4


async def test_normalized_duplicate_queries_do_not_expand_again(monkeypatch):
    trace, search = Trace(), FakeSearch()
    scout = DRScout(None, trace, search, {}, options())
    monkeypatch.setattr(scout, 'call_llm', fake_expansion)
    await scout._execute_search('"Fictional" OR query')
    calls = len(search.searches)
    assert await scout._execute_search('  fictional   query ') == []
    assert len(search.searches) == calls == 3


async def reading_response(**kwargs):
    return json.dumps({'extracted_facts': [
        {'content': 'Supported fictional claim', 'quote': 'Fictional evidence'},
        {'content': 'Unsupported claim', 'quote': 'not present in the text'}],
        'answer_clues': [{'content': 'Fictional answer clue', 'quote': 'copied from document.'}]})


def populate(scout, count=12):
    for i in range(count):
        scout._available_docs[str(i)] = {'source_url': f'https://example.test/{i}'}


async def test_each_read_batch_at_most_two_and_quotes_must_exist(monkeypatch):
    trace, search = Trace(), FakeSearch()
    scout = DRScout(None, trace, search, {}, options())
    populate(scout)
    monkeypatch.setattr(scout, 'call_llm', reading_response)
    facts = await scout.read_docs(['unknown', '0', '1', '2'], 'Fictional question')
    assert search.reads == [('0', 8000), ('1', 8000)]
    assert trace.n_read == 2 and trace.retrieved == {'0', '1'}
    assert len(facts) == 4
    assert all('Unsupported' not in f['content'] and f['quote'] in 'Fictional evidence copied from document.' for f in facts)
    assert await scout.read_docs(['0', '1'], 'Fictional question') == []
    assert len(search.reads) == 2


async def test_concurrent_read_batches_do_not_exceed_eight(monkeypatch):
    trace, search = Trace(), FakeSearch()
    scout = DRScout(None, trace, search, {}, options())
    populate(scout)
    monkeypatch.setattr(scout, 'call_llm', reading_response)
    await asyncio.gather(*(scout.read_docs([str(i), str(i + 1)], 'Fictional question')
                           for i in range(0, 12, 2)))
    assert len(search.reads) == trace.n_read == 8
    assert len({docid for docid, _ in search.reads}) == 8


async def test_analysis_selected_document_facts_join_existing_facts(monkeypatch):
    trace, search, sources = Trace(), FakeSearch(), {'https://example.test/1': '1'}
    scout = DRScout(None, trace, search, sources, options())

    async def fake_llm(**kwargs):
        if 'docs_to_read' in kwargs['user_prompt']:
            return json.dumps({'extracted_facts': [], 'docs_to_read': ['1']})
        return await reading_response(**kwargs)

    monkeypatch.setattr(scout, 'call_llm', fake_llm)
    result = await scout._analyze_search_results('Fictional question', {},
        [{'url': 'https://example.test/1', 'title': 'Demo', 'summary': 'Fictional snippet'}])
    assert trace.n_read == 1
    assert len(result['extracted_facts']) == 2
    assert all(f['source_url'] == 'https://example.test/1' for f in result['extracted_facts'])
