"""按版本选项构造四角色；v1.1仅改变Chief规划，其他角色继承原样适配行为。"""

from copy import deepcopy
import re

from app.agents import s4_port
from .prompts import CONSTRAINT_PLANNING, PLANNING_SYSTEM, QUERY_EXPANSION


def clean_query(query):
    """清除BM25不支持的引擎语法，拒绝未消解占位符或过短查询。"""
    if not isinstance(query, str) or re.search(r'<|>|示例|\[[^\]]+\]|\{[^}]+\}', query):
        return ''
    query = re.sub(r'\bsite\s*:\s*\S+', ' ', query, flags=re.IGNORECASE)
    query = re.sub(r'\b(?:OR|AND)\b', ' ', query)
    query = re.sub(r'["“”‘’\x27]|\.{2,}', ' ', query)
    query = ' '.join(query.split())
    return query if len(query) >= 6 and len(query.split()) >= 2 else ''


def merge_rrf(lists, count, k=60):
    """按URL去重，每个检索列表每篇只贡献一次倒数排名分；同分保留先出现顺序。"""
    scores, documents = {}, {}
    for results in lists:
        seen = set()
        for rank, item in enumerate(results, 1):
            url = item.get('url')
            if not url or url in seen:
                continue
            seen.add(url)
            documents.setdefault(url, item)
            scores[url] = scores.get(url, 0.0) + 1.0 / (k + rank)
    return [{**documents[url], 'rrf_score': scores[url]}
            for url in sorted(scores, key=scores.get, reverse=True)[:count]]


class DRArchitect(s4_port.CorpusArchitect):
    """保留原规划解析与状态转换，覆盖规划提示词并保留额外的约束字段。"""

    def __init__(self, llm, trace, opts):
        super().__init__(llm, trace)
        self.opts = deepcopy(opts)
        self._planning_query = None
        self._plan_fields = {}
        if self.opts.get('planner') == 'constraints':
            self.PLANNING_PROMPT = CONSTRAINT_PLANNING

    async def _initial_planning(self, state):
        self._planning_query = state['query']
        self._plan_fields = {}
        try:
            result = await super()._initial_planning(state)
            result['_constraints'] = deepcopy(self._plan_fields.get('constraints', []))
            result['_answer_type'] = self._plan_fields.get('answer_type', '')
            return result
        finally:
            self._planning_query = None

    async def call_llm(self, system_prompt, user_prompt, json_mode=True,
                       temperature=0.3, max_tokens=16000):
        if self.opts.get('planner') == 'constraints' and self._planning_query is not None:
            # 原父类失败重试会换回行业模板；所有规划重试均保持本版约束提示词。
            system_prompt = PLANNING_SYSTEM
            user_prompt = self.PLANNING_PROMPT.format(query=self._planning_query)
        response = await super().call_llm(system_prompt, user_prompt, json_mode,
                                         temperature, max_tokens)
        if self._planning_query is not None:
            parsed = self.parse_json_response(response)
            if isinstance(parsed, dict):
                self._plan_fields = parsed
        return response


class DRScout(s4_port.CorpusScout):
    """v1.1沿用检索；v1.2清理并扩写查询，复用原接口搜索并合并排名。"""

    def __init__(self, llm, trace, search, sources, opts):
        super().__init__(llm, trace, search, sources)
        self.opts = deepcopy(opts)

    async def _execute_search(self, query, count=10):
        if not self.opts.get('expand'):
            return await super()._execute_search(query, count)
        original = clean_query(query)
        if not original:
            return []
        response = await self.call_llm(
            system_prompt='You rewrite factual search queries for an English BM25 corpus. Return JSON only.',
            user_prompt=QUERY_EXPANSION.format(query=original), json_mode=True,
        )
        parsed = self.parse_json_response(response)
        alternatives = parsed.get('queries') if isinstance(parsed, dict) else None
        if not isinstance(alternatives, list):
            raise ValueError('检索扩写未返回queries列表')
        queries = [original]
        for candidate in alternatives[:self.opts['expand']]:
            cleaned = clean_query(candidate)
            if cleaned and cleaned not in queries:
                queries.append(cleaned)
        results = []
        for rewritten in queries:
            # 每次实际检索均走原适配层计数，不能把三次伪记为一次。
            results.append(await super()._execute_search(rewritten, count))
        return merge_rrf(results, count)


class DRWriter(s4_port.CorpusWriter):
    """按原样写作与修订，保存该版本选项供后续迭代使用。"""

    def __init__(self, llm, trace, opts):
        super().__init__(llm, trace)
        self.opts = deepcopy(opts)


class DRCritic(s4_port.CorpusCritic):
    """按原样审核与路由，不在v1.1同时修改准确性审核标准。"""

    def __init__(self, llm, trace, opts):
        super().__init__(llm, trace)
        self.opts = deepcopy(opts)
