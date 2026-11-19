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
            if tools and not any(m["role"] == "tool" for m in messages):
                call = SimpleNamespace(id="fake-call", function=SimpleNamespace(
                    name="search", arguments=json.dumps({"query": "demo"}),
                ))
                return response(None, [call])
            return response(json.dumps(universal_json()) if json_mode else ANSWER)

        async def close(self):
            closed.append("llm")

    class FakeSearch:
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
