"""离线验证v1.2查询清理、占位符拦截、三次实际检索及RRF去重；所有资料为虚构数据。"""

import json

import pytest

from app.agents import s4_port
from app.agents.dr.team import DRScout, clean_query, merge_rrf
from app.trace import Trace


def test_clean_search_engine_syntax():
    assert clean_query('site:example.test "Fictional" OR alias AND 1920..1940') == 'Fictional alias 1920 1940'


@pytest.mark.parametrize('query', ['[Candidate Name] biography', '<entity> evidence', '示例 query', 'x', 'one'])
def test_skip_invalid_or_placeholder_queries(query):
    assert clean_query(query) == ''


def test_rrf_rewards_documents_found_in_multiple_lists():
    a, b = {'url': 'corpus://a'}, {'url': 'corpus://b'}
    merged = merge_rrf([[a, b, b], [b]], 10)
    assert [r['url'] for r in merged] == ['corpus://b', 'corpus://a']
    assert len(merged) == 2


async def test_expansion_uses_three_real_searches(monkeypatch):
    calls = []

    async def fake_search(self, query, count=10):
        calls.append(query)
        return [{'url': 'corpus://same', 'title': 'Fictional document'}]

    async def fake_llm(**kwargs):
        return json.dumps({'queries': ['fictional alternate angle', 'fictional distinct clue']})

    monkeypatch.setattr(s4_port.CorpusScout, '_execute_search', fake_search)
    scout = DRScout(None, Trace(), None, {}, {'expand': 2})
    monkeypatch.setattr(scout, 'call_llm', fake_llm)
    results = await scout._execute_search('"fictional" OR question')
    assert calls == ['fictional question', 'fictional alternate angle', 'fictional distinct clue']
    assert len(results) == 1
    calls.clear()
    assert await scout._execute_search('[Candidate Name] biography') == []
    assert calls == []


async def test_v11_does_not_expand_or_clean(monkeypatch):
    calls = []

    async def fake_search(self, query, count=10):
        calls.append(query)
        return []

    monkeypatch.setattr(s4_port.CorpusScout, '_execute_search', fake_search)
    scout = DRScout(None, Trace(), None, {}, {'planner': 'constraints'})
    await scout._execute_search('"fictional" OR question')
    assert calls == ['"fictional" OR question']
