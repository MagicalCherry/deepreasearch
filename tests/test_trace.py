"""验证事件记录的计数、广播、数据隔离和非法事件拒绝；不调用云端服务。"""

import pytest

from app.trace import Trace


def test_search_and_read_statistics():
    trace = Trace()
    trace.emit("search", query="示例", k=2, results=[
        {"docid": "12", "title": "示例一", "score": 1.0},
        {"docid": "34", "title": "示例二", "score": 0.5},
    ])
    trace.emit("read", docid="12", title="示例一")

    assert trace.n_search == 1
    assert trace.n_read == 1
    assert trace.retrieved == {"12", "34"}
    assert [item["event"] for item in trace.events] == ["search", "read"]
    assert all(item["agent"] == "agent" for item in trace.events)
    assert 0 <= trace.events[0]["t"] <= trace.events[1]["t"]


def test_broadcast_and_unsubscribe():
    trace = Trace()
    first = trace.subscribe()
    second = trace.subscribe()
    source = ["步骤一"]
    trace.emit("plan", "planner", items=source)
    source.append("不应进入记录")

    first_event = first.get_nowait()
    second_event = second.get_nowait()
    first_event["items"].append("不应影响其他消费者")
    assert second_event["items"] == ["步骤一"]
    assert trace.events[0]["items"] == ["步骤一"]
    trace.unsubscribe(first)
    trace.emit("fact", text="示例事实", docid="12")
    assert first.empty()
    assert second.get_nowait()["event"] == "fact"


def test_unknown_event_is_rejected():
    trace = Trace()
    with pytest.raises(ValueError, match="未知事件"):
        trace.emit("unknown")
    assert trace.events == []
