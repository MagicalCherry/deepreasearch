"""AC-08：虚构标注穿过真实v2.3批量入口，审计假SDK接收的所有模型请求及工具参数，禁止联网。"""

from collections import defaultdict
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import httpx
import pytest

from app import llm as llm_module, runner
from app.agents import s4_port


@pytest.mark.parametrize('dataset', ['smoke20', 'custom'])
async def test_v23_all_model_requests_and_tools_exclude_dataset_labels(tmp_path, monkeypatch, dataset):
    secret_answer = 'LABEL_ANSWER_6c4c03_never_send'
    secret_gold, secret_evidence = '991827364501', '991827364502'
    record = {'query_id': 'audit-fake', 'query': 'Which fictional archive holds the blue ledger?',
              'answer': secret_answer, 'gold_docids': [secret_gold],
              'evidence_docids': [secret_evidence]}
    datasets = tmp_path / 'datasets'
    datasets.mkdir()
    (datasets / f'{dataset}.jsonl').write_text(json.dumps(record), encoding='utf-8')
    monkeypatch.setenv('DATASET_DIR', str(datasets))
    monkeypatch.setattr(runner, 'RUNS_DIR', tmp_path / 'runs')
    monkeypatch.setattr(runner, 'git_sha', lambda: 'offline-audit')
    requests, tool_requests, calls = [], [], defaultdict(int)
    closed = []

    async def no_network(*args, **kwargs):
        raise AssertionError('离线审计禁止任何HTTP请求')

    monkeypatch.setattr(httpx.AsyncClient, 'send', no_network)
    monkeypatch.setattr(llm_module, 'settings', replace(llm_module.settings, api_key='offline-fake-key'))

    class FakeSDK:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        async def create(self, **request):
            lane = s4_port.CURRENT_AGENT.get()
            requests.append({'lane': lane, 'request': deepcopy(request)})
            calls[lane] += 1
            tool_calls = None
            if lane == 'planner':
                content = json.dumps({'constraints': ['blue ledger archive'], 'answer_type': 'archive',
                    'outline': [{'id': f'sec_{i}', 'title': f'Fictional branch {i}',
                        'description': 'Find fictional evidence', 'section_type': 'mixed',
                        'requires_data': False, 'requires_chart': False,
                        'search_queries': [query]} for i, query in enumerate([
                            'blue ledger archive', 'silver museum catalog', 'copper library registry'], 1)],
                    'research_questions': [], 'hypotheses': [], 'key_entities': []})
            elif lane.startswith('scout-'):
                n = calls[lane]
                if n == 1:
                    # Distinct terms avoid cross-Scout near-duplicate rejection in frozen v2.3.
                    query = {'scout-1': 'blue ledger archive', 'scout-2': 'silver museum catalog',
                             'scout-3': 'copper library registry'}[lane]
                    name, args = 'search', {'query': query, 'reason': 'Find fictional evidence'}
                elif n == 2:
                    name, args = 'read_document', {'docid': '12', 'offset': 1, 'limit': 10,
                                                   'reason': 'Read evidence'}
                else:
                    name = None
                if name:
                    content = None
                    tool_calls = [SimpleNamespace(id=f'{lane}-{n}', type='function',
                        function=SimpleNamespace(name=name, arguments=json.dumps(args)))]
                else:
                    content = 'Findings:\n- The fictional blue ledger is held by Demo Archive [12]\nCandidates:\n- Demo Archive'
            elif lane == 'writer':
                content = json.dumps({'content': 'Demo Archive holds the fictional blue ledger [12].',
                                      'best_answer': 'Demo Archive', 'citations': []})
            elif lane == 'critic':
                content = json.dumps({'overall_assessment': {'quality_score': 9, 'verdict': 'pass'},
                    'constraint_checks': [{'constraint_index': 0, 'constraint': 'blue ledger archive',
                        'status': 'verified', 'docid': '12', 'note': 'Observed fictional evidence'}],
                    'issues': [], 'missing_aspects': [], 'alternative_candidate': ''})
            elif lane == 'answer':
                content = 'Explanation: Fictional retrieved evidence [12].\nExact Answer: Demo Archive\nConfidence: 80%'
            else:
                raise AssertionError(f'未覆盖的模型角色：{lane}')
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=content, tool_calls=tool_calls))], usage=None)

        async def close(self):
            closed.append('model')

    class FakeSearch:
        def __init__(self, **kwargs):
            assert kwargs == {'index': 'k25b1', 'snippet': 'passage'}

        async def search(self, query, k=5):
            tool_requests.append({'query': query, 'k': k})
            return {'results': [{'docid': '12', 'title': 'Fictional archive', 'score': 1,
                                'snippet': 'Demo Archive holds the fictional blue ledger.'}]}

        async def document(self, docid, **kwargs):
            tool_requests.append({'docid': docid, **kwargs})
            return {'docid': docid, 'title': 'Fictional archive',
                    'text': 'Demo Archive holds the fictional blue ledger.'}

        async def close(self):
            closed.append('search')

    async def fake_config(**kwargs):
        return {'enabled': True, 'index': 'k25b1', 'parameters': {'k1': 25, 'b': 1, 'unit': 'doc'}}

    monkeypatch.setattr(llm_module, 'AsyncOpenAI', FakeSDK)
    monkeypatch.setattr(s4_port, 'SearchClient', FakeSearch)
    monkeypatch.setattr(runner, 'search_config', fake_config)
    status = await runner.run_eval(dataset, 'v2.3', 1, 'offline-input-audit')
    assert status['completed'] == 1 and status['errors'] == 0
    assert {'planner', 'scout-1', 'scout-2', 'scout-3', 'writer', 'critic', 'answer'} <= set(calls)
    assert sum('query' in item for item in tool_requests) == 3
    assert any('docid' in item for item in tool_requests)
    assert all(any(message.get('role') == 'tool' for message in item['request']['messages'])
               for item in requests if item['lane'].startswith('scout-') and
               len(item['request']['messages']) > 2)
    payload = json.dumps({'model_requests': requests, 'tool_requests': tool_requests}, ensure_ascii=False)
    for forbidden in [secret_answer, secret_gold, secret_evidence, 'gold_docids', 'evidence_docids']:
        assert forbidden not in payload
    # Retrieved corpus IDs are allowed: reject label injection, not ordinary source citations.
    assert '12' in payload and 'Demo Archive' in payload
    assert sorted(closed) == ['model', 'search']
