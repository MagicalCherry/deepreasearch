"""保存官方搜索作答提示词，组装模型、检索工具和ReAct循环形成单Agent基线。"""

from typing import Any

from app.agents.react import Tools, react_loop
from app.llm import LLM
from app.search import SearchClient
from app.trace import Trace


# 来源：https://github.com/texttron/BrowseComp-Plus/blob/main/search_agent/prompts.py
# 使用QUERY_TEMPLATE原文，不附加标准答案或证据标注。
QUERY_TEMPLATE = """
You are a deep research agent. You need to answer the given question by interacting with a search engine, using the search and get_document tools provided. Please perform reasoning and use the tools step by step, in an interleaved manner. You may use the search and get_document tools multiple times.

Question: {Question}

Your response should be in the following format:
Explanation: {{your explanation for your final answer. For this explanation section only, you should cite your evidence documents inline by enclosing their docids in square brackets [] at the end of sentences. For example, [20].}}
Exact Answer: {{your succinct, final answer}}
Confidence: {{your confidence score between 0% and 100% for your answer}}
""".strip()


async def run(question: str, trace: Trace, opts: dict[str, Any]) -> str:
    """只用题面填充提示词，运行工具循环，结束或异常时释放两个客户端。"""
    trace.emit("agent_start", role="搜索与作答", task=question)
    llm = LLM(trace=trace)
    search = None
    try:
        search = SearchClient()
        tools = Tools(
            search=search, trace=trace, k=opts.get("k", 5),
            snippet_tokens=opts.get("snippet_tokens", 512),
            document_tokens=opts.get("document_tokens", 8000),
            recover_document_404=opts.get("recover_document_404", False),
        )
        return await react_loop(
            llm, [{"role": "user", "content": QUERY_TEMPLATE.format(Question=question)}],
            tools, max_tool_calls=opts.get("max_tool_calls", 30),
            max_turns=opts.get("max_turns", 40),
        )
    finally:
        try:
            if search is not None:
                await search.close()
        finally:
            await llm.close()
