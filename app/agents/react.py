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

    def definitions(self):
        """返回当前工具集的模型接口，旧版仍使用两个工具。"""
        return basic_tools(self.k)

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


def doc_lines(text: str, words_per_line: int = 80) -> list[str]:
    """打包短行并折叠长段，保留词序，提供稳定的一起始行号。"""
    words = text.split()
    return [' '.join(words[i:i + words_per_line]) for i in range(0, len(words), words_per_line)]


class PiTools(Tools):
    """深排缓存、按名次翻页与按行读文；缓存和标题不提前算作证据召回。"""

    def __init__(self, search, trace, *, search_depth=200, page_chars=1200,
                 title_ranks=15, **kwargs):
        super().__init__(search, trace, **kwargs)
        self.search_depth, self.page_chars, self.title_ranks = search_depth, page_chars, title_ranks
        self.searches, self.visible, self.exposed, self.bodies = {}, {}, set(), {}

    def definitions(self):
        specs = [
            ('search', 'Search short keywords; show five excerpts and the next fifteen titles.',
             {'query': {'type': 'string'}}),
            ('read_search_results', 'Page cached search results, with excerpts; offset is a one-based rank, limit at most 20.',
             {'search_id': {'type': 'string'}, 'offset': {'type': 'integer', 'minimum': 1},
              'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20}}),
            ('read_document', 'Read a visible document by one-based line numbers. Start at line 1; continue using next_offset.',
             {'docid': {'type': 'string'}, 'offset': {'type': 'integer', 'minimum': 1},
              'limit': {'type': 'integer', 'minimum': 1}}),
        ]
        return [{'type': 'function', 'function': {'name': name, 'description': desc,
                 'parameters': {'type': 'object', 'properties': {'reason': {'type': 'string'}, **props},
                                'required': ['reason', *props], 'additionalProperties': False}}}
                for name, desc, props in specs]

    @staticmethod
    def valid_args(name, args):
        if not isinstance(args.get('reason'), str) or not args['reason'].strip():
            return False
        if name == 'search':
            return isinstance(args.get('query'), str) and bool(args['query'].strip())
        key = 'search_id' if name == 'read_search_results' else 'docid'
        return (name in {'read_search_results', 'read_document'}
                and isinstance(args.get(key), str) and bool(args[key].strip())
                and all(type(args.get(k)) is int and args[k] >= 1 for k in ('offset', 'limit')))

    def _excerpts(self, rows, start, limit):
        results = []
        for rank, item in enumerate(rows[start - 1:start - 1 + limit], start):
            docid = str(item['docid'])
            result = {'rank': rank, 'docid': docid, 'title': item.get('title', ''),
                      'score': item.get('score', 0), 'excerpt': item.get('snippet', '')[:self.page_chars]}
            self.visible[docid] = result
            self.exposed.add(docid)
            results.append(result)
        return results

    async def call(self, name, args):
        if not self.valid_args(name, args):
            return {'error': 'Use a supported tool with a nonempty reason and valid parameters.'}
        reason = args['reason']
        if name == 'search':
            data = await self.search.search(args['query'], k=self.search_depth)
            rows = (data['results'] if isinstance(data, dict) else data)[:self.search_depth]
            sid = f's{len(self.searches) + 1}'
            self.searches[sid] = rows
            results = self._excerpts(rows, 1, 5)
            titles = []
            for rank, item in enumerate(rows[5:5 + self.title_ranks], 6):
                docid = str(item['docid'])
                self.visible.setdefault(docid, {'docid': docid, 'title': item.get('title', '')})
                titles.append(f"#{rank} [{docid}] {item.get('title', '')}")
            self.trace.emit('search', agent=self.agent, query=args['query'], k=5,
                            search_id=sid, reason=reason, results=results, more_titles=titles)
            return {'search_id': sid, 'results': results, 'more_titles': titles,
                    'hint': 'Scan titles, read a promising document from line 1, or page this search before rewriting.'}
        if name == 'read_search_results':
            sid, offset = args['search_id'], args['offset']
            if sid not in self.searches:
                return {'error': 'Unknown search_id; use an ID returned by search.'}
            results = self._excerpts(self.searches[sid], offset, min(20, args['limit']))
            end = offset + len(results)
            self.trace.emit('search', agent=self.agent, query=f'翻看 {sid} 第 {offset} 名起',
                            k=len(results), cached=True, search_id=sid, reason=reason, results=results)
            return {'search_id': sid, 'results': results,
                    'next_offset': end if end <= len(self.searches[sid]) else None}
        docid, offset = args['docid'], args['offset']
        if docid not in self.visible:
            return {'error': 'Read only a docid visible in your search excerpts or title lists.'}
        if docid not in self.bodies:
            try:
                self.bodies[docid] = await self.search.document(docid, max_tokens=None)
            except httpx.HTTPStatusError as exc:
                if not self.recover_document_404 or exc.response.status_code != 404:
                    raise
                return {'error': 'document_not_found', 'docid': docid, 'status_code': 404}
        document = self.bodies[docid]
        lines = doc_lines(document['text'])
        if offset > len(lines):
            return {'error': 'Offset past end of document.', 'total_lines': len(lines), 'next_offset': None}
        encoding = tiktoken.get_encoding('cl100k_base')
        selected, token_count = [], 0
        for line in lines[offset - 1:offset - 1 + min(args['limit'], 100)]:
            size = len(encoding.encode(line, disallowed_special=()))
            if token_count + size + 1 > self.document_tokens:
                break
            selected.append(line)
            token_count += size + 1
        if not selected:
            return {'error': 'One line exceeds the reading token cap; no text was read.'}
        end = offset + len(selected)
        title_only = docid not in self.exposed
        self.exposed.add(docid)
        self.trace.emit('read', agent=self.agent, docid=docid, title=document.get('title', ''),
                        reason=reason, span=f'第{offset}–{end - 1}行', offset=offset,
                        lines=len(selected), title_only=title_only, tool='read_document')
        return {'docid': docid, 'url': document.get('url', ''), 'offset': offset,
                'text': '\n'.join(selected), 'total_lines': len(lines),
                'next_offset': end if end <= len(lines) else None}


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
        if tools.trace.past_deadline():
            break
        if used >= max_tool_calls:
            break
        response = await llm.chat(history, tools=tools.definitions(), **options)
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
            if tools.trace.past_deadline():
                result = {"error": "Time budget reached; no tool was executed. Finish with collected evidence."}
            elif used >= max_tool_calls:
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

    reason = ('time_budget' if tools.trace.past_deadline() else
              "tool_budget" if used >= max_tool_calls else "max_turns")
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
