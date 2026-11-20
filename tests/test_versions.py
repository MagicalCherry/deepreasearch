"""用假模型及假检索完整运行每个已注册版本，验证S4泳道、事实、用量和正常结束；不调用云服务。"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app import runner
from app.agents import closedbook, single
from app.trace import Trace
from app.versions import get_version, list_versions


ANSWER = "Explanation: Fictional evidence [1].\nExact Answer: Demo\nConfidence: 50%"


def response(content, calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=content, tool_calls=calls,
    ))])


def universal_json():
    """只使用虚构资料；涵盖原角色必需字段，不包含任何真实评测标注。"""
    return {
        "outline": [{"id": f"sec_{i}", "title": f"Section {i}",
                     "description": "Fictional section", "section_type": "mixed",
                     "requires_data": False, "requires_chart": False,
                     "search_queries": [f"demo query {i}", f"demo alternate {i}"]} for i in range(1, 4)],
        "answer_type": "fictional name", "constraints": ["fictional constraint"],
        "queries": ["fictional alternate angle", "fictional distinct clue"],
        "thought": "Fictional evidence supports this section", "done": True,
        "new_facts": [{"content": "Fictional evidence", "docid": "1"}],
        "read_docids": ["1"], "candidates": [],
        "docs_to_read": ["1"], "answer_clues": [],
        "research_questions": ["Fictional question"], "key_entities": [],
        "mind_map": {}, "hypotheses": [],
        "extracted_facts": [{"content": "Fictional evidence",
                             "quote": "Fictional evidence",
                             "source_url": "https://example.test/1", "source_name": "Demo",
                             "credibility_score": 0.8, "data_points": []}],
        "entities_discovered": [], "hypothesis_evidence": [], "key_insights": [],
        "source_tracing_queries": [], "follow_up_queries": [],
        "further_tracing_queries": [], "data_points": [],
        "content": "Fictional chapter", "key_points": ["Demo"],
        "citations": [{"source": "Demo", "url": "https://example.test/1"}],
        "full_report": "Fictional report", "executive_summary": "Demo", "conclusions": [],
        "references": [], "overall_assessment": {"quality_score": 8, "verdict": "pass"},
        "issues": [], "missing_aspects": [], "fact_check_results": [],
        "constraint_checks": [{"constraint_index": 0, "constraint": "fictional constraint",
                               "status": "verified", "docid": "1", "note": "Fictional evidence"}],
        "alternative_candidate": "",
        "revised_content": "Revised fictional report", "addressed_issues": [],
    }


@pytest.fixture
def offline_clients(monkeypatch):
    from app.agents import s4_port
    closed = []

    class FakeLLM:
        def __init__(self, trace=None):
            self.trace = trace

        async def chat(self, messages, tools=None, json_mode=False, **kwargs):
            await asyncio.sleep(0)
            self.trace.prompt_tokens += 10
            self.trace.completion_tokens += 5
            is_scout = any('You are a research scout in a team.' in m.get('content', '')
                           for m in messages if m['role'] == 'system')
            if tools and not any(m["role"] == "tool" for m in messages):
                query = ('fictional evidence ' + json.loads(messages[1]['content'])['subquestion']['title']) if is_scout else 'demo'
                call = SimpleNamespace(id="fake-call", function=SimpleNamespace(
                    name="search", arguments=json.dumps({"query": query, **(
                        {'reason': 'Find fictional evidence'} if any(
                            t['function']['name'] == 'read_document' for t in tools) else {})}),
                ))
                return response(None, [call])
            if is_scout:
                previous = [m for m in messages if m['role'] == 'tool']
                if tools and previous and any(t['function']['name'] == 'read_document' for t in tools):
                    last = json.loads(previous[-1]['content'])
                    if isinstance(last, dict) and last.get('search_id'):
                        return response(None, [SimpleNamespace(id='fake-pi-read', function=SimpleNamespace(
                            name='read_document', arguments=json.dumps({'reason': 'Verify evidence',
                                'docid': '1', 'offset': 1, 'limit': 10})))])
                if tools and previous and isinstance(json.loads(previous[-1]['content']), list):
                    call = SimpleNamespace(id='fake-read', function=SimpleNamespace(
                        name='get_document', arguments=json.dumps({'docid':'1'})))
                    return response(None, [call])
                return response('Findings:\n- Fictional evidence [1]\nCandidates:\n- Demo')
            return response(json.dumps(universal_json()) if json_mode else ANSWER)

        async def close(self):
            closed.append("llm")

    class FakeSearch:
        def __init__(self, index=None, snippet=None):
            if index is not None:
                closed.append('search_index:' + index)
            if snippet is not None:
                closed.append('search_snippet:' + snippet)

        async def document(self, docid, max_tokens=None):
            return {"docid": docid, "title": "Demo", "text": "Fictional evidence"}

        async def search(self, q, k=5):
            await asyncio.sleep(0)
            return {"results": [{"docid": "1", "title": "Demo", "score": 1.0,
                                 "url": "https://example.test/1", "snippet": "Fictional evidence"}]}

        async def close(self):
            closed.append("search")

    for module in (closedbook, single, s4_port):
        monkeypatch.setattr(module, "LLM", FakeLLM)
    for module in (single, s4_port):
        monkeypatch.setattr(module, "SearchClient", FakeSearch)
    return closed


def test_s4_version_is_registered():
    """保留学员已观察过的注册失败检查，并核对原样基线配置。"""
    version = get_version("v1.0")
    assert version.options["max_iterations"] == 3
    assert version.options["retries"] == 2
    assert version.options["timeout_seconds"] is None
    assert version.options["max_search_calls"] is None


@pytest.mark.parametrize("version", [v["id"] for v in list_versions()])
async def test_every_registered_version_completes(version, offline_clients):
    trace = Trace()
    result = await runner.research("Fictional question", version, trace)
    assert "Exact Answer: Demo" in result
    assert trace.events[-1]["event"] == "done"
    assert not any(e["event"] == "error" for e in trace.events)
    # 闭卷定义为不提供检索，不能为了满足计数而给它增加搜索。
    assert trace.n_search == 0 if version == "v0-closedbook" else trace.n_search >= 1
    assert trace.prompt_tokens > 0 and trace.completion_tokens > 0
    assert "llm" in offline_clients
    if version != "v0-closedbook":
        assert "search" in offline_clients
    if version == "v1.0":
        lanes = {e["agent"] for e in trace.events if e["event"] == "search"}
        assert lanes == {"scout-1", "scout-2", "scout-3"}
        assert trace.retrieved == {"1"}
        assert any(e["event"] == "fact" and e["docid"] == "1" for e in trace.events)
        assert {"plan", "verify"} <= {e["event"] for e in trace.events}
    if version == 'v1.1':
        plan = next(e for e in trace.events if e['event'] == 'plan')
        assert plan['constraints'] == ['fictional constraint']
        assert plan['answer_type'] == 'fictional name'
        assert len(plan['subquestions']) == 3
        assert all(len(s['search_queries']) == 2 for s in plan['subquestions'])
    if version == 'v1.4':
        assert 1 <= trace.n_read <= 8
        assert trace.n_search <= 50
    if version == 'v1.6':
        assert 1 <= trace.n_read <= 8
        assert trace.n_search <= 50
        assert any(e['event'] == 'plan' and e.get('round') == 1 for e in trace.events)
    if version == 'v1.7':
        verification = [e for e in trace.events if e['event'] == 'verify'][-1]
        assert (verification['verified'], verification['total']) == (1, 1)
    if version == 'v1.8':
        assert any(e['event']=='stage_output' and e.get('kind')=='scout_report' for e in trace.events)
        assert any(e['event']=='fact' and e['docid']=='1' for e in trace.events)
        assert 1 <= trace.n_read <= 8
        assert trace.n_search <= 50
        assert all(e['agent'].startswith('scout') for e in trace.events if e['event'] in {'read','search'})
    if version == 'v1.9':
        assert 'search_index:k25b1' in offline_clients
        assert any(e['event']=='stage_output' and e.get('kind')=='scout_report' for e in trace.events)
    if version == 'v2.0':
        assert 'search_index:k25b1' in offline_clients
        assert 'search_snippet:passage' in offline_clients
        assert not any(e.get('kind') == 'citation_validation' for e in trace.events)
    if version == 'v2.1':
        assert 'search_snippet:passage' in offline_clients
        assert any(e.get('kind') == 'citation_validation' for e in trace.events)
        assert any(e.get('tool') == 'read_document' for e in trace.events)
        assert any(e['event'] == 'fact' for e in trace.events)


async def test_v17_pipeline_caps_confidence_with_unverified_evidence(monkeypatch, offline_clients):
    """从实际流水线到最终answer事件验证封顶，防止只改提示词而漏改保存结果。"""
    original = universal_json
    def unsupported_json():
        payload = original()
        payload['constraint_checks'][0]['docid'] = '999'
        return payload
    monkeypatch.setitem(globals(), 'universal_json', unsupported_json)
    trace = Trace()
    answer = await runner.research('Fictional question', 'v1.7', trace, {'max_iterations': 1})
    assert 'Confidence: 25%' in answer
    verify = [e for e in trace.events if e['event'] == 'verify'][-1]
    assert (verify['verified'], verify['total'], verify['verdict']) == (0, 1, 'fail')
    assert next(e for e in trace.events if e['event'] == 'answer')['confidence'] == 25
