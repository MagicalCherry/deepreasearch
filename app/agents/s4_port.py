"""S08唯一角色适配层：保留S4提示词与角色逻辑，接固定语料、异步模型、泳道、事实事件及答案抽取。"""

import asyncio
from contextvars import ContextVar
from copy import deepcopy
import logging
import re
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from app.answer import parse
from app.llm import LLM, LLMError
from app.search import SearchClient
from app.trace import Trace
from app.s4.deep_research_v2.state import ResearchPhase, create_initial_state
from app.s4.deep_research_v2.agents.architect import ChiefArchitect
from app.s4.deep_research_v2.agents.scout import DeepScout
from app.s4.deep_research_v2.agents.writer import LeadWriter
from app.s4.deep_research_v2.agents.critic import CriticMaster


logging.getLogger("Agent").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.WARNING)
CURRENT_AGENT: ContextVar[str] = ContextVar("s4_agent", default="planner")


class Traced:
    """使用共享异步客户端，替代原Web项目的同步模型客户端和消息队列。"""

    def __init__(self, llm: LLM, trace: Trace, **_: Any) -> None:
        # 不创建原基类的同步OpenAI客户端，也不初始化可选Milvus服务。
        self.llm = llm
        self.trace = trace
        self.name = type(self).__name__
        self.logger = logging.getLogger(f"Agent.{self.name}")

    async def call_llm(self, system_prompt: str, user_prompt: str,
                       json_mode: bool = True, temperature: float = 0.3,
                       max_tokens: int = 16000) -> str:
        """保留原调用参数；模型封装统计token、关闭思考，并处理有限截短重试。"""
        truncations = 0

        def truncate(messages: list[dict]) -> list[dict]:
            nonlocal truncations
            truncations += 1
            for message in messages:
                if message["role"] == "user":
                    content = message["content"]
                    message["content"] = (
                        "\n".join(line[:300] for line in content.splitlines())
                        if truncations == 1 else content[:6000]
                    )
            return messages

        response = await self.llm.chat(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": user_prompt}],
            json_mode=json_mode, temperature=temperature,
            max_tokens=max_tokens, truncate=truncate,
        )
        content = response.choices[0].message.content
        if not content or not content.strip():
            raise ValueError("S4模型返回空内容")
        return content

    def add_message(self, state: dict, event_type: str, content: Any) -> None:
        """保留原状态消息；业务事件在明确的搜索、事实、规划和审核位置发出。"""
        state["messages"].append({
            "type": event_type, "agent": CURRENT_AGENT.get(), "content": content,
        })


class CorpusArchitect(Traced, ChiefArchitect):
    """沿用原架构师的规划提示词、解析和状态更新。"""


class CorpusWriter(Traced, LeadWriter):
    """沿用原笔杆的章节写作、整合和修订。"""


class CorpusCritic(Traced, CriticMaster):
    """沿用原评论家的审核和路由条件。"""

    async def _review_content(self, state: dict):
        """保存原审核器实际返回的完整意见，不改变其判断、解析或路由。"""
        result = await super()._review_content(state)
        self.trace.emit("stage_output", agent="critic", kind="review",
                        review=result, iteration=state.get("iteration"))
        return result


class CorpusScout(Traced, DeepScout):
    """只替换搜索后端和Web依赖；沿用摘要提取、去重、追踪及补搜逻辑。"""

    def __init__(self, llm: LLM, trace: Trace, search: SearchClient,
                 sources: dict[str, str]) -> None:
        super().__init__(llm, trace)
        self.search = search
        self.sources = sources
        self.search_cache = {}
        self.fact_fingerprints = {}
        self.milvus_service = None

    async def _fetch_stock_data_if_relevant(self, state: dict) -> None:
        return None

    async def _execute_search(self, query: str, count: int = 10) -> list[dict]:
        """原检索词直接传给BM25；映射原字段，同时记录全部实际返回文档。"""
        data = await self.search.search(query, k=count)
        results = data["results"] if isinstance(data, dict) else data
        self.trace.emit("search", agent=CURRENT_AGENT.get(), query=query, k=count,
                        results=[{"docid": str(r["docid"]),
                                  "title": r.get("title", ""),
                                  "score": r.get("score", 0)} for r in results])
        mapped = []
        for result in results:
            docid = str(result["docid"])
            url = result.get("url") or f"corpus://{docid}"
            self.sources[url] = docid
            snippet = result.get("snippet", "")
            mapped.append({
                "url": url, "title": result.get("title", ""),
                "summary": snippet, "snippet": snippet,
                "site_name": urlparse(url).netloc, "date": result.get("date", ""),
            })
        return mapped

    async def process(self, state: dict) -> dict:
        """失败或取消时先取消并等待并行章节，避免整题重跑后旧任务仍在请求。"""
        self.section_tasks: set[asyncio.Task] = set()
        try:
            return await super().process(state)
        finally:
            for task in self.section_tasks:
                if not task.done():
                    task.cancel()
            if self.section_tasks:
                await asyncio.gather(*self.section_tasks, return_exceptions=True)

    async def _research_section(self, state: dict, section: dict) -> None:
        # gather创建的章节任务登记到本次调用，用于异常清理。
        self.section_tasks.add(asyncio.current_task())
        lane = "scout-" + str(section["id"]).removeprefix("sec_")
        token = CURRENT_AGENT.set(lane)
        self.trace.emit("agent_start", agent=lane, role="侦探", task=section["title"])
        try:
            await self.investigate(state, section)
        finally:
            CURRENT_AGENT.reset(token)

    async def investigate(self, state: dict, section: dict) -> None:
        """可覆盖的章节研究入口；默认完整调用原S4主体，不改变基线行为。"""
        await super()._research_section(state, section)


class FactList(list):
    """事实append时立即发事件；来源编号只从本次真实检索返回的URL映射取得。"""

    def __init__(self, trace: Trace, sources: dict[str, str]) -> None:
        super().__init__()
        self.trace = trace
        self.sources = sources

    def append(self, fact: dict) -> None:
        super().append(fact)
        self.trace.emit("fact", agent=CURRENT_AGENT.get(),
                        text=fact.get("content", ""),
                        docid=self.sources.get(fact.get("source_url", ""), ""))


async def _step(agent: Traced, state: dict, lane: str, role: str) -> dict:
    token = CURRENT_AGENT.set(lane)
    agent.trace.emit("agent_start", agent=lane, role=role, task=state["query"])
    try:
        result = await agent.process(state)
        if lane == "writer":
            agent.trace.emit("stage_output", agent=lane, kind="report",
                             content=result.get("final_report", ""),
                             sections=result.get("draft_sections", {}),
                             iteration=result.get("iteration"))
        return result
    finally:
        CURRENT_AGENT.reset(token)


async def _extract(question: str, state: dict, llm: LLM,
                   trace: Trace, sources: dict[str, str], answer_suffix: str = '') -> str:
    trace.emit("agent_start", agent="answer", role="作答", task=question)
    facts = [{"content": f.get("content"),
              "docid": sources.get(f.get("source_url", ""), ""),
              "source_url": f.get("source_url", "")} for f in state["facts"]]
    messages = [{"role": "system", "content": (
        "Answer the original question from the report and collected facts. "
        "Give one specific best candidate even when uncertain, and state uncertainty honestly. "
        "Cite only provided document IDs in square brackets; do not invent evidence. "
        "Use Explanation:, Exact Answer:, Confidence: (0-100%) fields."
    )}, {"role": "user", "content": (
        f"Question: {question}\nReport:\n{state['final_report']}\nFacts:\n{facts}" + answer_suffix
    )}]
    token = CURRENT_AGENT.set("answer")
    adapter = Traced(llm, trace)
    try:
        answer = await adapter.call_llm(messages[0]["content"], messages[1]["content"], json_mode=False)
        exact = parse(answer)["exact_answer"]
        if not exact or re.search(
            r"无法确定|不能确定|无法回答|unable to|cannot determine|unknown|not enough|insufficient",
            exact, re.IGNORECASE,
        ):
            answer = await adapter.call_llm(
                messages[0]["content"], messages[1]["content"] +
                "\nYour previous answer was non-specific. Give your single best concrete candidate, "
                "with appropriately low confidence if uncertain.\nPrevious answer:\n" + answer,
                json_mode=False,
            )
        return answer
    finally:
        CURRENT_AGENT.reset(token)


async def _run_once(question: str, trace: Trace, opts: dict) -> str:
    llm = LLM(trace=trace)
    search = None
    try:
        search = SearchClient()
        sources: dict[str, str] = {}
        state = create_initial_state(question, uuid4().hex)
        state["max_iterations"] = opts.get("max_iterations", 3)
        state["facts"] = FactList(trace, sources)
        architect = CorpusArchitect(llm, trace)
        scout = CorpusScout(llm, trace, search, sources)
        writer = CorpusWriter(llm, trace)
        critic = CorpusCritic(llm, trace)
        state = await _step(architect, state, "planner", "规划")
        trace.emit("plan", agent="planner", items=[
            f"{s['title']}: {'; '.join(s['search_queries'])}" for s in state["outline"]
        ])
        state = await _step(scout, state, "scout", "侦探")
        # S08教案仅串四角色；脱离Web项目的绘图/代码执行不进入此评测适配。
        state["phase"] = ResearchPhase.WRITING.value
        state = await _step(writer, state, "writer", "执笔")
        while state["iteration"] < state["max_iterations"]:
            state = await _step(critic, state, "critic", "核查")
            passed = state["phase"] == ResearchPhase.COMPLETED.value
            trace.emit("verify", agent="critic", verdict="pass" if passed else "fail",
                        verified=0, total=0,
                        note=f"原报告审核：quality_score={state['quality_score']}，"
                             f"unresolved_issues={state['unresolved_issues']}；非题目约束逐项验证")
            if passed:
                break
            if state["phase"] == ResearchPhase.RE_RESEARCHING.value:
                state = await _step(scout, state, "scout", "补充检索")
                state["phase"] = ResearchPhase.WRITING.value
                state = await _step(writer, state, "writer", "执笔")
            elif state["phase"] == ResearchPhase.REVISING.value:
                state = await _step(writer, state, "writer", "修订")
            else:
                break
        return await _extract(question, state, llm, trace, sources)
    finally:
        try:
            if search is not None:
                await search.close()
        finally:
            await llm.close()


async def run(question: str, trace: Trace, opts: dict[str, Any]) -> str:
    """整题最多重试两次；欠费、内容审核和取消直接向上传播，全部尝试计入用量。"""
    for attempt in range(opts.get("retries", 2) + 1):
        try:
            return await _run_once(question, trace, deepcopy(opts))
        except LLMError as exc:
            if exc.kind in {"arrearage", "content_filter"} or attempt >= opts.get("retries", 2):
                raise
        except Exception:
            if attempt >= opts.get("retries", 2):
                raise
    raise RuntimeError("S4整题重试失败")
