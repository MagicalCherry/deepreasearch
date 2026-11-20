"""迭代版四角色工作流：顺序、回环、重试与v1.0一致，只按opts选择角色行为并展示约束规划。"""

import asyncio
from copy import deepcopy
from typing import Any
from uuid import uuid4

from app.agents import s4_port
from app.agents.s4_port import FactList, _step, _extract
from app.llm import LLMError
from app.trace import Trace
from app.s4.deep_research_v2.state import ResearchPhase, create_initial_state
from .team import DRArchitect, DRScout, DRWriter, DRCritic


async def _run_once(question: str, trace: Trace, opts: dict) -> str:
    llm = s4_port.LLM(trace=trace)
    search = None
    try:
        search = s4_port.SearchClient(**({'index': opts['index']} if 'index' in opts else {}))
        sources: dict[str, str] = {}
        state = create_initial_state(question, uuid4().hex)
        state["max_iterations"] = opts.get("max_iterations", 3)
        state["facts"] = FactList(trace, sources)
        architect = DRArchitect(llm, trace, opts)
        scout = DRScout(llm, trace, search, sources, opts)
        writer = DRWriter(llm, trace, opts)
        critic = DRCritic(llm, trace, opts)
        state = await _step(architect, state, "planner", "规划")
        trace.emit("plan", agent="planner",
                   constraints=state.get("_constraints", []),
                   answer_type=state.get("_answer_type", ""),
                   hypotheses=state.get("hypotheses", []),
                   subquestions=state["outline"], items=[
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
                if opts.get('writer') == 'memo':
                    state['draft_sections'] = {}
                    state['final_report'] = ''
                    for section in state['outline']:
                        section['status'] = 'researching'
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
    if opts.get('flow_fixes'):
        from .flow_fixes import run as resilient_run
        return await resilient_run(question, trace, deepcopy(opts))
    for attempt in range(opts.get("retries", 2) + 1):
        try:
            return await _run_once(question, trace, deepcopy(opts))
        except LLMError as exc:
            if exc.kind in {"arrearage", "content_filter"} or attempt >= opts.get("retries", 2):
                raise
        except Exception:
            if attempt >= opts.get("retries", 2):
                raise
    raise RuntimeError("迭代版整题重试失败")
