"""记录一次研究的事件、耗时、检索计数及模型用量，并向监听队列广播事件。"""

import asyncio
from copy import deepcopy
from time import perf_counter
from typing import Any


EVENT_TYPES = frozenset({
    "agent_start", "plan", "search", "read", "fact", "verify",
    "answer", "done", "error",
})


class Trace:
    """每次研究单独创建；多个 Agent 可共享同一次研究的记录。"""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.n_search = 0
        self.n_read = 0
        self.retrieved: set[str] = set()
        self.stop_reason: str | None = None
        self._started = perf_counter()
        self._listeners: set[asyncio.Queue] = set()

    @property
    def seconds(self) -> float:
        """使用单调时钟计算已用秒数，避免系统校时影响。"""
        return perf_counter() - self._started

    def subscribe(self) -> asyncio.Queue:
        """订阅后续事件；命令行和后续 SSE 页面各自消费自己的队列。"""
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """消费者结束后移除队列，避免继续积累事件。"""
        self._listeners.discard(queue)

    def emit(self, event: str, agent: str = "agent", **fields: Any) -> dict[str, Any]:
        """保存并广播九种规定事件；搜索、阅读事件同步更新统计。"""
        if event not in EVENT_TYPES:
            raise ValueError(f"未知事件类型：{event}")
        if "t" in fields:
            raise ValueError("事件时间 t 由 Trace 自动生成")
        item = deepcopy(fields)
        item.update(event=event, t=self.seconds, agent=agent)
        if event == "search":
            self.n_search += 1
            self.retrieved.update(str(result["docid"]) for result in item.get("results", []))
        elif event == "read":
            self.n_read += 1
            self.retrieved.add(str(item["docid"]))
        self.events.append(item)
        for queue in self._listeners:
            queue.put_nowait(deepcopy(item))
        return deepcopy(item)
