"""S18先用虚构工具与假时钟定义软截止、停止原因及v2.2配置；不调用模型或真实检索。"""

import json
from types import SimpleNamespace

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
