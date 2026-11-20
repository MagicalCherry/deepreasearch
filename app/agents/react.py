"""定义官方搜索工具接口，执行搜索/阅读并记录事件，按工具预算运行ReAct循环。"""

import json
from collections.abc import Callable
from typing import Any

import tiktoken
import httpx

from app.trace import Trace


# 工具描述来源：texttron/BrowseComp-Plus，searcher/searchers/base.py。
def basic_tools(k: int = 5) -> list[dict[str, Any]]:
    """保留官方两个工具的描述，使用聊天接口的function工具结构。"""
    return [
        {"type": "function", "function": {
            "name": "search",
            "description": f"Perform a search on a knowledge source. Returns top-{k} hits with docid, score, and snippet. The snippet contains the document's contents (may be truncated based on token limits).",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"}}, "required": ["query"], "additionalProperties": False},
        }},
        {"type": "function", "function": {
            "name": "get_document",
            "description": "Retrieve a full document by its docid.",
            "parameters": {"type": "object", "properties": {
                "docid": {"type": "string"}}, "required": ["docid"], "additionalProperties": False},
        }},
    ]


class Tools:
    """把本地检索客户端适配成模型工具，只返回实际服务提供的文档内容。"""

    def __init__(self, search: Any, trace: Trace, k: int = 5,
                 snippet_tokens: int = 512, document_tokens: int = 8000,
                 recover_document_404: bool = False, agent: str = 'agent') -> None:
        self.search = search
        self.trace = trace
        self.k = k
        self.snippet_tokens = snippet_tokens
        self.document_tokens = document_tokens
        self.recover_document_404 = recover_document_404
        self.agent = agent

    @staticmethod
    def truncate(text: str, limit: int) -> str:
        """与课程检索服务一致，使用cl100k_base按token截断。"""
        encoding = tiktoken.get_encoding("cl100k_base")
        return encoding.decode(encoding.encode(text, disallowed_special=())[:limit])

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        """调工具并记录已展示的搜索结果或已读取文档；服务异常向上抛出。"""
        if name == "search":
            query = args.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ValueError("search需要非空query")
            data = await self.search.search(query, k=self.k)
            candidates = data["results"] if isinstance(data, dict) else data
            results = [
                {"docid": str(item["docid"]), "score": item["score"],
                 "title": item.get("title", ""),
                 "snippet": self.truncate(item.get("snippet", ""), self.snippet_tokens)}
                for item in candidates[:self.k]
            ]
            self.trace.emit("search", agent=self.agent, query=query, k=self.k, results=[
                {key: item[key] for key in ("docid", "title", "score")} for item in results
            ])
            return results
        if name == "get_document":
            docid = args.get("docid")
            if not isinstance(docid, str) or not docid.strip():
                raise ValueError("get_document需要非空docid")
            try:
                document = await self.search.document(docid, max_tokens=self.document_tokens)
            except httpx.HTTPStatusError as exc:
                if not self.recover_document_404 or exc.response.status_code != 404:
                    raise
                # 失败不计为成功阅读；工具回复随本轮调用继续占用原有预算。
                return {"error": "document_not_found", "status_code": 404,
                        "docid": docid, "message": (
                            "The document service returned 404. No document was read. "
                            "Use a docid from search results, not a title or URL. "
                            "Search again if necessary."
                        )}
            text = self.truncate(document["text"], self.document_tokens)
            self.trace.emit("read", agent=self.agent, docid=str(document["docid"]),
                            title=document.get("title", ""), span=f"前{self.document_tokens} token以内")
            return {"docid": str(document["docid"]), "url": document.get("url", ""), "text": text}
        raise ValueError(f"未知工具：{name}")


async def react_loop(llm: Any, messages: list[dict], tools: Tools,
                     max_tool_calls: int = 30, max_turns: int = 40,
                     shrink: Callable | None = None, raise_on_max_turns: bool = True) -> str:
    """循环追加工具结果，预算或轮次用尽后再进行一次不带工具的收尾调用。"""
    if max_tool_calls < 0 or max_turns < 1:
        raise ValueError("工具预算不能为负，轮次必须大于0")
    history = list(messages)
    used = 0
    last_text = ''
    options = {'truncate': shrink} if shrink is not None else {}
    for _ in range(max_turns):
        if used >= max_tool_calls:
            break
        response = await llm.chat(history, tools=basic_tools(tools.k), **options)
        message = response.choices[0].message
        if message.content and message.content.strip():
            last_text = message.content
        calls = message.tool_calls or []
        if not calls:
            if not message.content or not message.content.strip():
                if not raise_on_max_turns:
                    return last_text
                raise ValueError("模型未调用工具且返回空答案")
            return message.content
        history.append({
            "role": "assistant", "content": message.content,
            "tool_calls": [{"id": call.id, "type": "function", "function": {
                "name": call.function.name, "arguments": call.function.arguments,
            }} for call in calls],
        })
        for call in calls:
            if used >= max_tool_calls:
                # 同轮多个请求也不能突破预算；仍逐个回复，保持消息协议完整。
                result = {"error": "Tool budget exhausted; no tool was executed."}
            else:
                used += 1
                args = json.loads(call.function.arguments)
                if not isinstance(args, dict):
                    raise ValueError("工具参数必须为JSON对象")
                result = await tools.call(call.function.name, args)
            history.append({"role": "tool", "tool_call_id": call.id,
                            "content": json.dumps(result, ensure_ascii=False)})

    reason = "tool_budget" if used >= max_tool_calls else "max_turns"
    if not raise_on_max_turns:
        tools.trace.emit('plan', agent=tools.agent, reason=reason,
                         items=['侦探达到工具或轮次上限，按已有证据整理发现报告。'])
        history.append({'role': 'user', 'content': 'No more tools. Finish the requested Findings / Candidates report using only collected evidence. Do not invent missing facts.'})
        response = await llm.chat(history, **options)
        message = response.choices[0].message
        return message.content if not message.tool_calls and message.content and message.content.strip() else last_text
    tools.trace.stop_reason = reason
    history.append({"role": "user", "content": (
        "Do not call any more tools. Give your best answer using the information collected. "
        "Use Explanation:, Exact Answer:, and Confidence: (0-100%) fields."
    )})
    response = await llm.chat(history, **options)
    message = response.choices[0].message
    if message.tool_calls or not message.content or not message.content.strip():
        raise ValueError("收回工具后模型未返回有效答案")
    return message.content
