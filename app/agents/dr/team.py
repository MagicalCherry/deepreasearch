"""按版本选项构造四角色；v1.1仅改变Chief规划，其他角色继承原样适配行为。"""

from copy import deepcopy
import asyncio
import json
import re
from uuid import uuid4

from app.agents import s4_port
from .prompts import (CONSTRAINT_PLANNING, PLANNING_SYSTEM, QUERY_EXPANSION,
                      HYPOTHESIS_ANALYSIS, DOCUMENT_SELECTION, DOCUMENT_READING)


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
        # 一个Scout实例的三个并发章节共享候选；不同题目使用不同实例，互不泄漏。
        self.candidates = {}
        self._constraints = []
        self._question = ''
        self._available_docs = {}
        self._react_sections, self._react_documents, self._react_read_locks = {}, {}, {}
        # 状态挂在整题Trace上，章节并发、补搜及整题重试不会重置预算。
        if self.opts.get('max_searches') is not None:
            if not hasattr(trace, '_dr_budget'):
                trace._dr_budget = {'lock': asyncio.Lock(), 'search_count': trace.n_search,
                                    'queries': set(), 'originals': set(), 'reads': set()}
            self._budget = trace._dr_budget

    async def process(self, state):
        self._constraints = deepcopy(state.get('_constraints', []))
        self._question = state['query']
        return await super().process(state)

    async def investigate(self, state, section):
        """仅v1.6启用逐轮搜索与重新规划；旧版本调用原章节研究流程。"""
        if self.opts.get('scout') == 'react':
            return await self.react_section(state, section)
        if self.opts.get('scout') != 'loop':
            return await super().investigate(state, section)
        await self.loop_section(state, section)

    async def react_section(self, state, section):
        from .react_scout import react_section
        return await react_section(self, state, section)

    def _store_loop_facts(self, state, section, facts, documents):
        """只允许本章节真实搜索返回的文档作为来源，全文事实仍由read_docs校验原文。"""
        if not isinstance(facts, list):
            return
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            value = fact.get('docid')
            if not isinstance(value, (str, int)) or isinstance(value, bool):
                continue
            docid = str(value)
            document = documents.get(docid)
            content = fact.get('content')
            if not document or not isinstance(content, str) or not content.strip():
                continue
            url = document['source_url']
            if any(f.get('content') == content and f.get('source_url') == url for f in state['facts']):
                continue
            if self._is_duplicate_fact(content, url):
                continue
            entry = {**fact, 'id': 'fact_' + uuid4().hex[:8], 'docid': docid,
                     'source_url': url, 'source_name': document.get('title', ''),
                     'related_sections': [section['id']], 'verified': False,
                     'credibility_score': 0.5}
            state['facts'].append(entry)
            points = fact.get('data_points', [])
            for point in points if isinstance(points, list) else []:
                if isinstance(point, dict):
                    state['data_points'].append({**point, 'id': 'dp_' + uuid4().hex[:8],
                        'source': document.get('title', ''), 'docid': docid})

    async def loop_section(self, state, section):
        """每轮最多两个查询，再按当前结果决策；预算和读文限制沿用v1.4。"""
        from .prompts import LOOP_INVESTIGATION
        section['status'] = 'researching'
        seeds = section.get('search_queries', [])
        pending = [q for value in seeds if (q := clean_query(value))] if isinstance(seeds, list) else []
        documents = {}
        for round_index in range(self.opts.get('scout_rounds', 6)):
            if self._budget['search_count'] >= self.opts['max_searches']:
                self.trace.stop_reason = 'search_budget'
                break
            current, pending = pending[:2], pending[2:]
            results = []
            for query in current:
                results.extend(await self._execute_search(query, count=self.opts.get('k_per_query', 5)))
            latest = {}
            for result in results:
                docid = self.sources.get(result.get('url', ''))
                if docid is None:
                    continue
                docid = str(docid)
                if docid in latest:
                    continue
                latest[docid] = {'docid': docid, 'title': result.get('title', ''),
                    'source_url': result['url'], 'snippet': str(result.get('summary', ''))[:260]}
                if len(latest) >= 12:
                    break
            documents.update(latest)
            self._available_docs.update(latest)
            known_raw = {str(r.get('docid')) for r in state['raw_sources'] if isinstance(r, dict)}
            for docid, document in latest.items():
                if docid not in known_raw:
                    state['raw_sources'].append(deepcopy(document))
            payload = {'question': state['query'], 'constraints': state.get('_constraints', []),
                'section': {'title': section.get('title'), 'description': section.get('description')},
                'round': round_index + 1,
                'facts': [{**f, 'docid': self.sources.get(f.get('source_url', ''), f.get('docid', ''))}
                          for f in state['facts'][-25:]],
                'candidates': list(self.candidates.values()), 'results': list(latest.values()),
                'searched_queries': sorted(self._budget['queries'])}
            response = await self.call_llm(
                system_prompt='Investigate the supplied evidence and plan the next search round. Return JSON only.',
                user_prompt=LOOP_INVESTIGATION + '\n' + json.dumps(payload, ensure_ascii=False),
                json_mode=True, temperature=0.2)
            result = self.parse_json_response(response)
            if not isinstance(result, dict):
                raise ValueError('循环侦探未返回JSON对象')
            self._store_loop_facts(state, section, result.get('new_facts', []), documents)
            candidates = result.get('candidates', [])
            for candidate in candidates if isinstance(candidates, list) else []:
                if isinstance(candidate, dict) and isinstance(candidate.get('name'), str) and candidate['name'].strip():
                    self.candidates[candidate['name'].strip()] = deepcopy(candidate)
            read_facts = await self.read_docs(result.get('read_docids', []), state['query'])
            # 读取可由其他侦探已发现的文档，但只接受read_docs实际返回的校验事实。
            read_documents = {f['docid']: self._available_docs[f['docid']] for f in read_facts}
            self._store_loop_facts(state, section, read_facts, read_documents)
            queries = result.get('queries', [])
            queries = [q for value in queries[:2] if (q := clean_query(value))] if isinstance(queries, list) else []
            pending = list(dict.fromkeys(pending + queries))
            thought = result.get('thought', '')
            self.trace.emit('plan', agent=s4_port.CURRENT_AGENT.get(), round=round_index + 1,
                items=([thought] if isinstance(thought, str) and thought else []) + pending,
                candidates=deepcopy(list(self.candidates.values())))
            if result.get('done') is True or not pending:
                break

    async def _supplementary_research(self, state):
        if self.opts.get('scout') != 'loop':
            return await super()._supplementary_research(state)
        pending = state.get('pending_search_queries', [])
        if isinstance(pending, list) and pending:
            section = {'id': 'supplementary', 'title': '补充核查',
                       'description': '核查审核发现的证据缺口', 'search_queries': pending[:3]}
            await self.loop_section(state, section)
        state['pending_search_queries'] = []
        state['phase'] = s4_port.ResearchPhase.WRITING.value
        return state

    def _near_duplicate(self, query):
        """调用者持有预算锁；近似判重只比较实际已执行或已预留的查询。"""
        if not self.opts.get('neardup'):
            return False
        words = set(re.findall(r'\w+', query.casefold()))
        if not words:
            return False
        for previous in self._budget['queries']:
            other = set(re.findall(r'\w+', previous.casefold()))
            if other and len(words & other) / len(words | other) >= 0.7:
                return True
        return False

    async def _hypothesis_analysis(self, question, focus, results, limit):
        documents = [{'title': r.get('title', ''), 'source_url': r.get('url', ''),
                      'snippet': str(r.get('summary', ''))[:300]} for r in results[:limit]
                     if isinstance(r, dict)]
        if self.opts.get('read_docs'):
            for document in documents:
                docid = self.sources.get(document['source_url'])
                if docid:
                    document['docid'] = docid
                    self._available_docs[docid] = document
        prompt = HYPOTHESIS_ANALYSIS.format(
            question=question, constraints=json.dumps(self._constraints, ensure_ascii=False),
            focus=focus, candidates=json.dumps(list(self.candidates.values()), ensure_ascii=False),
            documents=json.dumps(documents, ensure_ascii=False))
        if self.opts.get('read_docs'):
            prompt += DOCUMENT_SELECTION
        response = await self.call_llm(
            system_prompt='You analyze retrieved evidence and propose falsifiable candidate hypotheses. Return JSON only.',
            user_prompt=prompt,
            json_mode=True, temperature=0.2,
        )
        parsed = self.parse_json_response(response)
        if not isinstance(parsed, dict):
            raise ValueError('候选分析未返回JSON对象')
        analysis = self._normalize_hypothesis_analysis(parsed)
        if self.opts.get('read_docs'):
            analysis['extracted_facts'].extend(await self.read_docs(
                analysis.get('docs_to_read', []), question))
        return analysis

    async def read_docs(self, docids, query):
        """只读本次真实检索结果，每次最多两篇；事实需有正文可核对的原文片段。"""
        if not self.opts.get('read_docs') or not isinstance(docids, list):
            return []
        facts, selected = [], 0
        for value in docids:
            if selected >= 2:
                break
            docid = value.get('docid') if isinstance(value, dict) else value
            if not isinstance(docid, (str, int)) or isinstance(docid, bool):
                continue
            docid = str(docid)
            if docid not in self._available_docs:
                continue
            async with self._budget['lock']:
                if docid in self._budget['reads']:
                    continue
                if len(self._budget['reads']) >= self.opts['max_reads']:
                    break
                # 网络请求前预留，确保三个并发侦探不会重复读取或超限。
                self._budget['reads'].add(docid)
                selected += 1
            document = await self.search.document(docid, max_tokens=self.opts['doc_max_tokens'])
            text = document.get('text', '')
            self.trace.emit('read', agent=s4_port.CURRENT_AGENT.get(), docid=docid,
                            title=document.get('title', ''),
                            span=f"前{self.opts['doc_max_tokens']} token以内")
            if not isinstance(text, str) or not text.strip():
                continue
            response = await self.call_llm(
                system_prompt='Extract evidence from the supplied document text. Return JSON only.',
                user_prompt=DOCUMENT_READING.format(query=query,
                    constraints=json.dumps(self._constraints, ensure_ascii=False), docid=docid,
                    title=document.get('title', ''), text=text), json_mode=True, temperature=0.2)
            parsed = self.parse_json_response(response)
            if not isinstance(parsed, dict):
                raise ValueError('正文阅读未返回JSON对象')
            for key in ('extracted_facts', 'answer_clues'):
                values = parsed.get(key, [])
                for fact in values if isinstance(values, list) else []:
                    if not isinstance(fact, dict):
                        continue
                    quote, content = fact.get('quote'), fact.get('content')
                    if not isinstance(quote, str) or not quote.strip() or quote not in text:
                        continue
                    if not isinstance(content, str) or not content.strip():
                        continue
                    facts.append({'content': ('答案线索（待核实）：' if key == 'answer_clues' else '')
                                  + content + '\n原文片段：' + quote,
                                  'source_url': self._available_docs[docid]['source_url'],
                                  'source_name': document.get('title', ''), 'data_points': [],
                                  'credibility_score': 0.5, 'docid': docid, 'quote': quote})
        return facts

    def _normalize_hypothesis_analysis(self, parsed):
        """过滤原角色按dict读取的列表，验证查询置前并复用两层追踪入口。"""
        def objects(value):
            return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []

        result = deepcopy(parsed)
        for key in ('candidates', 'extracted_facts', 'data_points', 'entities_discovered', 'hypothesis_evidence'):
            result[key] = objects(result.get(key))
        for fact in result['extracted_facts']:
            fact['data_points'] = objects(fact.get('data_points'))
        for entity in result['entities_discovered']:
            if 'relations' in entity:
                entity['relations'] = objects(entity['relations'])
        verification = []
        for candidate in result['candidates']:
            name = candidate.get('name')
            if not isinstance(name, str) or not name.strip():
                continue
            name = name.strip()
            for key in ('satisfied_constraints', 'unmet_constraints'):
                values = candidate.get(key, [])
                candidate[key] = [x for x in values if isinstance(x, str)] if isinstance(values, list) else []
            self.candidates[name] = candidate
            query = clean_query(candidate.get('verification_query'))
            if query and name.casefold() in query.casefold():
                verification.append(query)
        for key in ('follow_up_queries', 'further_tracing_queries'):
            original = result.get(key, [])
            original = original if isinstance(original, list) else []
            queries = verification + [clean_query(x) for x in original]
            result[key] = list(dict.fromkeys(x for x in queries if x))
        insights = result.get('key_insights', [])
        result['key_insights'] = [x for x in insights if isinstance(x, str)] if isinstance(insights, list) else []
        result['source_tracing_queries'] = []
        return result

    async def _analyze_search_results(self, query, section, results, hypotheses=None):
        if self.opts.get('analysis') != 'hypothesis':
            return await super()._analyze_search_results(query, section, results, hypotheses)
        if not results:
            return None
        return await self._hypothesis_analysis(query, section.get('description', ''), results, 15)

    async def _analyze_deep_search_results(self, original_query, search_query, results,
                                           search_type, hypotheses):
        if self.opts.get('analysis') != 'hypothesis':
            return await super()._analyze_deep_search_results(
                original_query, search_query, results, search_type, hypotheses)
        if not results:
            return None
        return await self._hypothesis_analysis(original_query, search_query, results, 6)

    async def _execute_search(self, query, count=10):
        if not self.opts.get('expand'):
            return await super()._execute_search(query, count)
        original = clean_query(query)
        if not original:
            return []
        if self.opts.get('max_searches') is not None:
            async with self._budget['lock']:
                if self._budget['search_count'] >= self.opts['max_searches']:
                    self.trace.stop_reason = 'search_budget'
                    return []
                normalized = original.casefold()
                if normalized in self._budget['originals'] or normalized in self._budget['queries'] or self._near_duplicate(original):
                    return []
                self._budget['originals'].add(normalized)
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
            if self.opts.get('max_searches') is not None:
                async with self._budget['lock']:
                    if self._budget['search_count'] >= self.opts['max_searches']:
                        self.trace.stop_reason = 'search_budget'
                        break
                    normalized = rewritten.casefold()
                    if normalized in self._budget['queries'] or self._near_duplicate(rewritten):
                        continue
                    self._budget['queries'].add(normalized)
                    self._budget['search_count'] += 1
            # 每次实际检索均走原适配层计数，不能把三次伪记为一次。
            results.append(await super()._execute_search(rewritten, count))
        if self.opts.get('max_searches') is not None and self._budget['search_count'] >= self.opts['max_searches']:
            self.trace.stop_reason = 'search_budget'
        return merge_rrf(results, count)


class DRWriter(s4_port.CorpusWriter):
    """按原样写作与修订，保存该版本选项供后续迭代使用。"""

    def __init__(self, llm, trace, opts):
        super().__init__(llm, trace)
        self.opts = deepcopy(opts)

    async def _write_section(self, state, section):
        if self.opts.get('writer') != 'memo':
            return await super()._write_section(state, section)
        if section is not state['outline'][0]:
            state['draft_sections'][section['id']] = ''
            section['status'] = 'drafted'
            return
        from .prompts import MEMO_WRITING
        payload = {
                'question': state['query'], 'constraints': state.get('_constraints', []),
                'facts': state['facts'], 'data_points': state['data_points'],
                'feedback': state['critic_feedback']}
        if self.opts.get('scout') == 'react':
            payload['scout_reports'] = state.get('_scout_reports', {})
            payload['report_usage_rule'] = 'Scout reports are exploratory notes, not independent evidence. Use only source-validated facts for factual claims; candidates remain hypotheses.'
        response = await self.call_llm(
            system_prompt='Write factual answer memos from supplied evidence only. Return JSON.',
            user_prompt=MEMO_WRITING + '\n' + json.dumps(payload, ensure_ascii=False),
            json_mode=True, temperature=0.3, max_tokens=16000)
        result = self.parse_json_response(response)
        if not isinstance(result, dict) or not isinstance(result.get('content'), str) or not result['content'].strip():
            raise ValueError('答案备忘录未返回有效content')
        state['draft_sections'][section['id']] = result['content']
        section['status'] = 'drafted'
        known = {f.get('source_url') for f in state['facts'] if isinstance(f, dict)}
        state['references'] = [c for c in result.get('citations', [])
                               if isinstance(c, dict) and c.get('url') and c['url'] in known]
        self.trace.emit('plan', agent='writer', items=[str(result.get('best_answer', 'Unknown'))])

    async def _synthesize_report(self, state):
        if self.opts.get('writer') != 'memo':
            return await super()._synthesize_report(state)
        state['final_report'] = '\n\n'.join(
            state['draft_sections'].get(s['id'], '') for s in state['outline']
            if state['draft_sections'].get(s['id']))

    async def _revise_report(self, state):
        if self.opts.get('writer') != 'memo':
            return await super()._revise_report(state)
        state['draft_sections'] = {}
        for section in state['outline']:
            section['status'] = 'researching'
        return await self._write_report(state)


class DRCritic(s4_port.CorpusCritic):
    """按原样审核与路由，不在v1.1同时修改准确性审核标准。"""

    def __init__(self, llm, trace, opts):
        super().__init__(llm, trace)
        self.opts = deepcopy(opts)
        if self.opts.get('critic') == 'evidence':
            from .prompts import EVIDENCE_REVIEW
            self.REVIEW_PROMPT = EVIDENCE_REVIEW

    async def _review_content(self, state):
        if self.opts.get('critic') == 'constraints':
            from .constraints import review
            return await review(self, state)
        return await super()._review_content(state)

    def _analyze_issues_for_routing(self, review_result):
        if self.opts.get('critic') != 'constraints':
            return super()._analyze_issues_for_routing(review_result)
        # 保留替代候选优先级，不能沿用父类的set排序。
        queries = list(review_result.get('missing_aspects', []))
        queries.extend(i.get('search_query') for i in review_result.get('issues', [])
                       if i.get('requires_new_search') and i.get('search_query'))
        queries = list(dict.fromkeys(q for value in queries if (q := clean_query(value))))[:5]
        return {'should_research': bool(queries), 'search_queries': queries}
