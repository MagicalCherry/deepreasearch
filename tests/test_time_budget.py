"""S18先用虚构工具与假时钟定义软截止、停止原因及v2.2配置；不调用模型或真实检索。"""

import json
import asyncio
from types import SimpleNamespace

import pytest

from app.agents.react import Tools, react_loop
from app.trace import Trace
from app.versions import get_version


def test_trace_deadline_uses_monotonic_clock_and_marks_time_budget(monkeypatch):
    import app.trace as trace_module
    now = [100.0]
    monkeypatch.setattr(trace_module, 'perf_counter', lambda: now[0])
    trace = Trace()
    trace.deadline = 110.0
    assert not trace.past_deadline()
    now[0] = 110.0
    assert trace.past_deadline()
    assert trace.stop_reason == 'time_budget'


async def test_react_second_turn_has_no_tools_after_soft_deadline():
    trace = Trace()
    trace.deadline = float('inf')

    class Search:
        async def search(self, query, k=5):
            # 首次工具完成时模拟已过软截止，不等待真实秒数。
            trace.deadline = -1.0
            return {'results':[{'docid':'12','title':'Fictional evidence',
                                'score':1,'snippet':'Fictional evidence'}]}

    class Model:
        def __init__(self):
            self.requests = []

        async def chat(self, messages, **kwargs):
            self.requests.append(kwargs)
            calls = [SimpleNamespace(id=f'call-{len(self.requests)}', function=SimpleNamespace(
                name='search', arguments=json.dumps({'query':'fictional clue'})))] if kwargs.get('tools') else None
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=None if calls else 'Findings:\n- Fictional evidence [12]\nCandidates:\nNone',
                tool_calls=calls))])

    model = Model()
    result = await react_loop(model, [{'role':'user','content':'Find fictional evidence'}],
                              Tools(Search(), trace), max_tool_calls=4, max_turns=6,
                              raise_on_max_turns=False)
    assert len(model.requests) == 2
    assert model.requests[0].get('tools') and not model.requests[1].get('tools')
    assert trace.n_search == 1
    assert trace.stop_reason == 'time_budget'
    assert 'Findings:' in result


def test_v22_adds_only_time_budget_to_v21():
    from copy import deepcopy
    previous = deepcopy(get_version('v2.1').options)
    assert get_version('v2.2').options == {**previous, 'time_budget':600, 'answer_reserve':60}
    assert get_version('v2.1').options == previous


@pytest.mark.parametrize('seconds,reserve', [(600,60),(300,60)])
def test_budget_boundaries_start_at_trace_creation(seconds, reserve):
    trace = Trace()
    trace.set_time_budget(seconds, reserve)
    assert trace.deadline == trace._started + seconds * .7
    assert trace.research_deadline == trace._started + seconds - reserve
    assert trace.total_deadline == trace._started + seconds


@pytest.mark.parametrize('seconds,reserve', [(60,60),(0,60),(300,0),(float('inf'),60),(True,1)])
def test_invalid_budget_is_rejected(seconds, reserve):
    with pytest.raises(ValueError):
        Trace().set_time_budget(seconds, reserve)


def test_cli_override_is_numeric_and_whitelisted():
    from app.cli import parse_overrides
    assert parse_overrides(['time_budget=300']) == {'time_budget':300}
    for values in [['time_budget=nan'], ['time_budget=0'], ['other=300'],
                   ['time_budget=300','time_budget=600'], ['time_budget=abc']]:
        with pytest.raises(ValueError):
            parse_overrides(values)


def test_smoke_reuse_preserves_explicit_300_budget_without_changing_version():
    from scripts.prepare_smoke_dev100 import reuse_options
    assert reuse_options('v2.2',300)['time_budget'] == 300
    assert reuse_options('v2.2')['time_budget'] == get_version('v2.2').options['time_budget'] == 600
    with pytest.raises(ValueError):
        reuse_options('v2.1',300)


@pytest.fixture
def fake_timed_clients(monkeypatch):
    from app.agents import s4_port
    closed = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def close(self):
            closed.append('closed')

    monkeypatch.setattr(s4_port, 'LLM', Client)
    monkeypatch.setattr(s4_port, 'SearchClient', Client)
    return closed


async def test_hard_deadline_cancels_research_and_answers_from_retained_state(monkeypatch, fake_timed_clients):
    from app.agents.dr import flow_fixes
    trace = Trace()
    cancelled = []

    async def stage(agent, state, lane, role, opts):
        state['facts'].append({'content':'Fictional retained evidence','docid':'12'})
        try:
            await asyncio.Future()
        finally:
            cancelled.append(True)

    async def extract(question, state, *args, **kwargs):
        assert cancelled and state['facts'][0]['content'] == 'Fictional retained evidence'
        return 'Explanation: Fictional retained evidence.\nExact Answer: Demo\nConfidence: 10%'

    monkeypatch.setattr(flow_fixes, 'retry_stage', stage)
    monkeypatch.setattr(flow_fixes, '_extract', extract)
    opts = {**get_version('v2.2').options, 'time_budget':.15, 'answer_reserve':.1}
    result = await flow_fixes.run('Fictional question', trace, opts)
    assert 'Exact Answer: Demo' in result
    assert trace.stop_reason == 'time_budget'
    assert cancelled == [True] and len(fake_timed_clients) == 2
    assert not any(e['event'] == 'verify' for e in trace.events)


async def test_answer_deadline_returns_explicit_unknown_and_cancels_call(monkeypatch, fake_timed_clients):
    from app.agents.dr import flow_fixes
    trace = Trace()
    cancelled = []

    async def stage(agent, state, lane, role, opts):
        await asyncio.Future()

    async def extract(*args, **kwargs):
        try:
            await asyncio.Future()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(flow_fixes, 'retry_stage', stage)
    monkeypatch.setattr(flow_fixes, '_extract', extract)
    result = await flow_fixes.run('Fictional question', trace,
        {**get_version('v2.2').options,'time_budget':.1,'answer_reserve':.07})
    assert 'Exact Answer: Unknown' in result and 'Confidence: 0%' in result
    assert cancelled == [True] and trace.stop_reason == 'time_budget'


async def test_user_cancellation_is_not_converted_to_budget_answer(monkeypatch, fake_timed_clients):
    from app.agents.dr import flow_fixes
    started = asyncio.Event()

    async def stage(*args):
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(flow_fixes, 'retry_stage', stage)
    task = asyncio.create_task(flow_fixes.run('Fictional question', Trace(), get_version('v2.2').options))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(fake_timed_clients) == 2


async def test_soft_deadline_skips_critic_after_writer(monkeypatch, fake_timed_clients):
    from app.agents.dr import flow_fixes
    trace, lanes = Trace(), []

    async def stage(agent, state, lane, role, opts):
        lanes.append(lane)
        if lane == 'writer':
            trace.deadline = -1
        return state

    async def extract(*args, **kwargs):
        return 'Explanation: Fictional.\nExact Answer: Demo\nConfidence: 10%'

    monkeypatch.setattr(flow_fixes, 'retry_stage', stage)
    monkeypatch.setattr(flow_fixes, '_extract', extract)
    await flow_fixes.run('Fictional question', trace, get_version('v2.2').options)
    assert lanes == ['planner','scout','writer'] and trace.stop_reason == 'time_budget'


async def test_search_entry_skips_io_after_soft_deadline():
    from app.agents.dr.flow_fixes import ResilientScout
    trace = Trace()
    trace.deadline = -1
    scout = ResilientScout(None, trace, None, {}, get_version('v2.2').options)
    assert await scout._execute_search('Fictional keyword clue') == []
    assert scout._budget['search_count'] == 0 and trace.n_search == 0


async def test_batch_override_is_saved_used_and_mismatch_rejected(tmp_path, monkeypatch):
    from app import runner
    calls = []

    async def snapshot(enabled, **kwargs):
        return {'enabled':enabled,'index':'fictional'}

    async def research(question, version, trace, opts=None):
        calls.append(opts)
        return 'Explanation: Fictional.\nExact Answer: Demo\nConfidence: 10%'

    monkeypatch.setattr(runner,'RUNS_DIR',tmp_path)
    monkeypatch.setattr(runner,'git_sha',lambda:'fake-code')
    monkeypatch.setattr(runner,'search_config',snapshot)
    monkeypatch.setattr(runner,'load_questions',lambda _: [{'query_id':'demo','query':'Fictional question'}])
    monkeypatch.setattr(runner,'research',research)
    await runner.run_eval('smoke20','v2.2',1,'fake-300',{'time_budget':300})
    config = json.loads((tmp_path/'fake-300/config.json').read_text(encoding='utf-8'))
    assert config['options']['time_budget'] == config['budget']['seconds'] == 300
    assert calls == [{'time_budget':300}]
    with pytest.raises(ValueError, match='续跑配置'):
        await runner.run_eval('smoke20','v2.2',1,'fake-300',{'time_budget':600})
