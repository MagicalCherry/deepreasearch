"""定义 Agent 版本及注册表，保存版本说明、运行入口和默认选项。"""

from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.agents.closedbook import run as closedbook_run
from app.agents.single import run as single_run
from app.trace import Trace


@dataclass(frozen=True)
class Version:
    """一个可重跑的 Agent 版本；运行器负责合并并复制选项。"""

    id: str
    label: str
    description: str
    run: Callable[[str, Trace, dict[str, Any]], Awaitable[str]]
    options: dict[str, Any] = field(default_factory=dict)


_VERSIONS: dict[str, Version] = {}


def register(version: Version) -> None:
    """登记版本，拒绝覆盖同名版本以保留对照入口。"""
    if version.id in _VERSIONS:
        raise ValueError(f"版本已存在：{version.id}")
    _VERSIONS[version.id] = version


def get_version(version_id: str) -> Version:
    """根据稳定编号查找版本，未知编号给出明确错误。"""
    try:
        return _VERSIONS[version_id]
    except KeyError:
        raise ValueError(f"未知版本：{version_id}") from None


def list_versions() -> list[dict[str, str]]:
    """返回可供命令行和页面展示的版本说明。"""
    return [
        {"id": version.id, "label": version.label, "description": version.description}
        for version in _VERSIONS.values()
    ]


register(Version(
    id="v0-closedbook",
    label="闭卷",
    description="仅凭模型记忆作答，不提供搜索或阅读工具。",
    run=closedbook_run,
    options={"temperature": 0},
))

register(Version(
    id="v0-single",
    label="单 Agent",
    description="官方提示词的ReAct搜索基线，最多30次工具调用；文档404反馈给模型纠正，其余服务错误上抛。",
    run=single_run,
    options={"k": 5, "snippet_tokens": 512, "document_tokens": 8000,
             "max_tool_calls": 30, "max_turns": 40, "recover_document_404": True},
))


async def s4_run(question: str, trace: Trace, opts: dict[str, Any]) -> str:
    """延迟导入接手系统，旧版本命令不因S4可选依赖缺失而无法启动。"""
    from app.agents.s4_port import run
    return await run(question, trace, opts)


register(Version(
    id="v1.0",
    label="S4 原样多 Agent",
    description="原始行业报告提示词与四角色流程，固定语料适配，最多三轮审核。",
    run=s4_run,
    options={"max_iterations": 3, "retries": 2,
             "timeout_seconds": None, "max_search_calls": None},
))


async def dr_run(question: str, trace: Trace, opts: dict[str, Any]) -> str:
    """延迟加载迭代版流水线，不替换原样v1.0入口。"""
    from app.agents.dr.pipeline import run
    return await run(question, trace, opts)


def dr_version(vid: str, label: str, description: str, *, base: str | None = None, **changes) -> None:
    """新版本选项由上一迭代版深拷贝后只覆盖指定键，避免污染旧版本。"""
    previous = get_version(base) if base is not None else next(reversed(_VERSIONS.values()))
    options = deepcopy(previous.options)
    options.update(deepcopy(changes))
    register(Version(vid, label, description, dr_run, options))


dr_version('v1.1', '约束规划', '按问题全部约束拆成三个子问题，生成英文检索式；其余角色保持原样。',
           planner='constraints')
dr_version('v1.2', '检索式扩写', '继承约束规划，清理检索语法并扩写两个角度，用RRF合并结果。',
           expand=2)
dr_version('v1.3', '假设驱动检索', '继承约束规划与检索扩写，提出候选并优先验证其未满足约束。',
           analysis='hypothesis')
dr_version('v1.4', '正文阅读与搜索预算', '模型选择正文读取，每题最多50次实际搜索、8篇文档，每篇最多8000 token。',
           read_docs=True, max_searches=50, max_reads=8, doc_max_tokens=8000)

dr_version('v1.5', '答案备忘录与证据核查', '整题生成答案备忘录，按证据链审核，补搜后重新撰写。',
           writer='memo', critic='evidence')

dr_version('v1.6', '循环侦探', '每轮搜索后重新规划，最多六轮，近似去重，补搜复用循环。',
           scout='loop', scout_rounds=6, k_per_query=5, neardup=True)

dr_version('v1.6.1', '循环侦探流程修复', '保留状态重试，停止无新结果的循环，最后报告经过审核。',
           flow_fixes=True)

dr_version('v1.7', '约束核对与置信度封顶', '逐条核对约束与来源，优先补搜替代候选，按验证比例限制置信度。',
           critic='constraints')

dr_version('v1.8', 'ReAct侦探', '每个子问题用搜索和正文工具交替取证，最多12次工具调用，发现报告交给Writer。',
           scout='react', scout_tool_calls=12)

dr_version('v1.9', 'BM25索引调参', '继承ReAct侦探，仅切换k25b1索引（k1=25、b=1）。',
           index='k25b1')

dr_version('v1.9.1', 'Scout引用交接修复', '使用实际文档编号，错误引用最多纠正一次并记录校验结果；保留v1.9其余配置。',
           scout_citation_repair=True)

dr_version('v2.0', '查询相关片段实验', '以v1.9为基线，仅把开头摘要替换为查询相关片段；不混入v1.9.1引用修复。',
           base='v1.9', snippet='passage')
