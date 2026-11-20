"""虚构HTTP响应验证v1.9索引请求、健康快照与运行配置；不访问本地真实检索或模型服务。"""

import json
from types import SimpleNamespace

import httpx
import pytest

from app import runner, search


@pytest.mark.parametrize('index', [None, 'k25b1'])
async def test_search_request_uses_only_selected_index(monkeypatch, index):
    requests = []
    def handle(request):
        requests.append(request)
        if request.url.path == '/search':
            return httpx.Response(200, json={'results': []})
        return httpx.Response(200, json={'docid':'12','text':'Fictional text'})
    original = httpx.AsyncClient
    monkeypatch.setattr(search.httpx, 'AsyncClient', lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(search, 'settings', SimpleNamespace(search_url='http://offline.test'))
    client = search.SearchClient(index=index)
    try:
        await client.search('fictional query', k=5)
        await client.document('12', max_tokens=100)
    finally:
        await client.close()
    assert dict(requests[0].url.params) == {'q':'fictional query','k':'5', **({'index':index} if index else {})}
    assert dict(requests[1].url.params) == {'max_tokens':'100'}


@pytest.mark.parametrize('status', ['ready','building','missing'])
async def test_snapshot_uses_requested_index_without_default_fallback(monkeypatch, status):
    closed = []
    class FakeSearch:
        async def health(self):
            indexes = [{'name':'default','status':'ready','k1':.9,'b':.4,'unit':'doc'}]
            if status != 'missing':
                indexes.append({'name':'k25b1','status':status,'k1':25,'b':1,'unit':'doc'})
            return {'status':'ok','docs':10,'default_index':'default','indexes':indexes}
        async def close(self):
            closed.append(True)
    monkeypatch.setattr(runner, 'SearchClient', FakeSearch)
    if status == 'ready':
        snapshot = await runner.search_config(True, index='k25b1')
        assert snapshot['index'] == 'k25b1'
        assert snapshot['parameters'] == {'k1':25,'b':1,'unit':'doc'}
    else:
        with pytest.raises(ValueError, match='索引未就绪'):
            await runner.search_config(True, index='k25b1')
    assert closed == [True]


@pytest.mark.parametrize('snippet', [None, 'passage'])
async def test_eval_records_selected_index(monkeypatch, tmp_path, snippet):
    requested = []
    options = {'index':'k25b1', **({'snippet':snippet} if snippet else {})}
    async def snapshot(enabled, index=None, snippet=None):
        requested.append((index, snippet))
        return {'enabled':enabled,'index':index,'parameters':{'k1':25,'b':1,'unit':'doc'},
                **({'snippet':snippet} if snippet else {})}
    async def fake_run(question, trace, opts):
        assert opts == options
        return 'Explanation: Demo.\nExact Answer: Demo\nConfidence: 25%'
    monkeypatch.setattr(runner,'search_config',snapshot)
    monkeypatch.setattr(runner,'get_version',lambda _:SimpleNamespace(run=fake_run,options=options))
    monkeypatch.setattr(runner,'RUNS_DIR',tmp_path)
    monkeypatch.setattr(runner,'git_sha',lambda:'fictional-commit')
    monkeypatch.setattr(runner,'load_questions',lambda _:[{'query_id':'1','query':'Fictional question'}])
    status = await runner.run_eval('smoke20','fictional',1,'index-test')
    assert status['status'] == 'completed'
    config = json.loads((tmp_path/'index-test/config.json').read_bytes())
    assert requested == [('k25b1', snippet)]
    assert config['search']['index'] == config['options']['index'] == 'k25b1'
    if snippet:
        assert config['search']['snippet'] == config['options']['snippet'] == snippet
    else:
        assert 'snippet' not in config['search']


@pytest.mark.parametrize('snippet', [None, 'head', 'passage'])
async def test_snippet_changes_search_only_not_document_request(monkeypatch, snippet):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={'results':[], 'docid':'12', 'text':'Fictional text'})
    original = httpx.AsyncClient
    monkeypatch.setattr(search.httpx, 'AsyncClient', lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(search, 'settings', SimpleNamespace(search_url='http://offline.test'))
    client = search.SearchClient(index='k25b1', snippet=snippet)
    try:
        await client.search('fictional query', k=5)
        await client.document('12', max_tokens=100)
    finally:
        await client.close()
    assert dict(requests[0].url.params) == {'q':'fictional query','k':'5','index':'k25b1',
                                          **({'snippet':snippet} if snippet else {})}
    assert dict(requests[1].url.params) == {'max_tokens':'100'}


def test_unknown_snippet_rejected_before_client_creation():
    with pytest.raises(ValueError, match='未知片段模式'):
        search.SearchClient(snippet='invented')


async def test_snapshot_records_snippet_and_preserves_index_parameters(monkeypatch):
    class FakeSearch:
        async def health(self):
            return {'status':'ok','docs':10,'default_index':'default','indexes':[
                {'name':'k25b1','status':'ready','k1':25,'b':1,'unit':'doc'}]}
        async def close(self):
            pass
    monkeypatch.setattr(runner, 'SearchClient', FakeSearch)
    config = await runner.search_config(True, index='k25b1', snippet='passage')
    assert config['snippet'] == 'passage'
    assert config['parameters'] == {'k1':25,'b':1,'unit':'doc'}
