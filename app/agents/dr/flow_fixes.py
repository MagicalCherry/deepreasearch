"""v1.6.1专用流程修复：保留角色工作状态重试、缓存待读证据、停止空循环及保证末稿已审核。"""

import asyncio
from copy import deepcopy
import json
from uuid import uuid4

from app.agents import s4_port
from app.agents.s4_port import FactList, _extract, _step
from app.llm import LLMError
from app.s4.deep_research_v2.state import ResearchPhase, create_initial_state
from .prompts import DOCUMENT_READING, LOOP_INVESTIGATION
from .team import DRArchitect, DRCritic, DRScout, DRWriter, clean_query


def progress(trace, reason, text):
    """继续使用已有plan事件，明确结束或跳过原因，不伪造工具调用。"""
    trace.emit('plan', agent=s4_port.CURRENT_AGENT.get(), reason=reason, items=[text])


async def retry_operation(operation, trace, lane, retries, rollback=None):
    """仅重试当前操作；取消、欠费及内容审核直接传播，预算从不回滚。"""
    for attempt in range(retries + 1):
        try:
            return await operation()
        except Exception as exc:
            if rollback is not None:
                rollback()
            fatal = isinstance(exc, LLMError) and exc.kind in {'arrearage', 'content_filter'}
            known = {'答案备忘录未返回有效content', '循环侦探未返回JSON对象',
                     '正文阅读未返回JSON对象', '审核未返回有效评分、结论和问题列表'}
            message = str(exc) if isinstance(exc, ValueError) and str(exc) in known else '当前阶段执行失败'
            trace.emit('stage_output', agent=lane, kind='stage_error',
                       error_type=type(exc).__name__, error_kind=getattr(exc, 'kind', None),
                       message=message,
                       attempt=attempt + 1, will_retry=not fatal and attempt < retries)
            if fatal or attempt >= retries:
                raise


async def retry_stage(agent, state, lane, role, opts):
    """Writer/Critic失败时回滚半成品；事实、来源、Scout实例和Trace预算一直保留。"""
    durable = {'facts', 'data_points', 'raw_sources', 'messages', 'logs', 'errors'}
    # Scout会把已完成的搜索/分析保存在实例中，不能回滚它的章节进度。
    saved = {k: deepcopy(v) for k, v in state.items() if k not in durable} if lane != 'scout' else None

    def rollback():
        if saved is not None:
            for key in list(state):
                if key not in durable and key not in saved:
                    del state[key]
            state.update(deepcopy(saved))

    return await retry_operation(lambda: _step(agent, state, lane, role), agent.trace,
                                 lane, opts.get('retries', 2), rollback)


class ResilientScout(DRScout):
    """缓存章节中途结果及正文，模型返回错误后继续处理原证据，不从空白重新研究。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._loops = {}
        self._read_texts = {}
        self._read_facts = {}
        self._read_locks = {}

    async def _execute_search(self, query, count=10):
        cleaned = clean_query(query)
        if not cleaned:
            progress(self.trace, 'invalid_query', '跳过无效或带占位符的查询。')
            return []
        async with self._budget['lock']:
            exhausted = self._budget['search_count'] >= self.opts['max_searches']
            duplicate = (cleaned.casefold() in self._budget['originals']
                         or cleaned.casefold() in self._budget['queries'] or self._near_duplicate(cleaned))
        if exhausted:
            self.trace.stop_reason = 'search_budget'
            progress(self.trace, 'search_budget', '跳过查询：搜索预算耗尽。')
            return []
        if duplicate:
            progress(self.trace, 'duplicate_query', '跳过已搜索或高度相似的查询。')
            return []
        return await super()._execute_search(cleaned, count)

    async def investigate(self, state, section):
        try:
            if self.opts.get('scout') == 'react':
                await self.react_section(state, section)
            else:
                await self.loop_section(state, section)
        except BaseException:
            # 父类只调度pending章节；取消的并行章节也需要在有限重试时续上。
            section['status'] = 'pending'
            raise

    async def read_docs(self, docids, query):
        if not self.opts.get('read_docs') or not isinstance(docids, list):
            return []
        output, selected = [], 0
        for value in docids:
            docid = value.get('docid') if isinstance(value, dict) else value
            if not isinstance(docid, (str, int)) or isinstance(docid, bool):
                continue
            docid = str(docid)
            if docid not in self._available_docs or selected >= 2:
                continue
            selected += 1
            lock = self._read_locks.setdefault(docid, asyncio.Lock())
            async with lock:
                if docid in self._read_facts:
                    output.extend(deepcopy(self._read_facts[docid]))
                    continue
                if docid not in self._read_texts:
                    async with self._budget['lock']:
                        if docid in self._budget['reads'] or len(self._budget['reads']) >= self.opts['max_reads']:
                            continue
                        self._budget['reads'].add(docid)
                    document = await self.search.document(docid, max_tokens=self.opts['doc_max_tokens'])
                    self._read_texts[docid] = document
                    self.trace.emit('read', agent=s4_port.CURRENT_AGENT.get(), docid=docid,
                                    title=document.get('title', ''), span=f"前{self.opts['doc_max_tokens']} token以内")
                document = self._read_texts[docid]
                text = document.get('text', '')
                facts = []
                if isinstance(text, str) and text.strip():
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
                                + content + '\n原文片段：' + quote, 'quote': quote, 'docid': docid,
                                'source_url': self._available_docs[docid]['source_url'],
                                'source_name': document.get('title', ''), 'data_points': [], 'credibility_score': 0.5})
                self._read_facts[docid] = facts
                output.extend(deepcopy(facts))
        return output

    async def loop_section(self, state, section):
        key = section['id']
        seeds = section.get('search_queries', [])
        context = self._loops.setdefault(key, {
            'round': 0, 'phase': 'start', 'done': False, 'documents': {},
            'pending': [q for v in seeds if (q := clean_query(v))] if isinstance(seeds, list) else [],
        })
        section['status'] = 'researching'
        while context['round'] < self.opts.get('scout_rounds', 6) and not context['done']:
            if context['phase'] == 'start':
                if self._budget['search_count'] >= self.opts['max_searches']:
                    self.trace.stop_reason = 'search_budget'
                    progress(self.trace, 'search_budget', '搜索预算耗尽，保留已收集证据。')
                    context['done'] = True
                    break
                context['current'], context['pending'] = context['pending'][:2], context['pending'][2:]
                context.update(phase='search', index=0, results=[])
            if context['phase'] == 'search':
                while context['index'] < len(context['current']):
                    query = context['current'][context['index']]
                    results = await self._execute_search(query, count=self.opts.get('k_per_query', 5))
                    context['results'].extend(results)
                    context['index'] += 1
                latest = {}
                for result in context['results']:
                    docid = self.sources.get(result.get('url', ''))
                    if docid is not None:
                        docid = str(docid)
                        latest.setdefault(docid, {'docid': docid, 'title': result.get('title', ''),
                            'source_url': result['url'], 'snippet': str(result.get('summary', ''))[:260]})
                    if len(latest) >= 12:
                        break
                initial_replan = context['round'] == 0 and not context['current']
                new_ids = set(latest) - set(context['documents'])
                if not new_ids and not initial_replan:
                    progress(self.trace, 'no_new_results', '本轮没有新文档，停止空结果分析。')
                    context['round'] += 1
                    context['phase'] = 'start'
                    if not context['pending']:
                        context['done'] = True
                    continue
                context['documents'].update(latest)
                self._available_docs.update(latest)
                known = {str(r.get('docid')) for r in state['raw_sources'] if isinstance(r, dict)}
                state['raw_sources'].extend(deepcopy(d) for docid, d in latest.items() if docid not in known)
                context.update(phase='analysis', latest=list(latest.values()), initial_replan=initial_replan)
            if context['phase'] == 'analysis':
                payload = {'question': state['query'], 'constraints': state.get('_constraints', []),
                    'section': {'title': section.get('title'), 'description': section.get('description')},
                    'round': context['round'] + 1, 'results': context['latest'],
                    'mode': 'repair_initial_queries' if context['initial_replan'] else 'analyze_results',
                    'facts': [{**f, 'docid': self.sources.get(f.get('source_url', ''), f.get('docid', ''))}
                              for f in state['facts'][-25:]],
                    'candidates': list(self.candidates.values()), 'searched_queries': sorted(self._budget['queries'])}
                response = await self.call_llm(
                    system_prompt='Investigate the supplied evidence and plan the next search round. Return JSON only.',
                    user_prompt=LOOP_INVESTIGATION + '\n' + json.dumps(payload, ensure_ascii=False),
                    json_mode=True, temperature=0.2)
                parsed = self.parse_json_response(response)
                if not isinstance(parsed, dict):
                    raise ValueError('循环侦探未返回JSON对象')
                context.update(phase='apply', analysis=parsed)
            parsed = context['analysis']
            self._store_loop_facts(state, section, parsed.get('new_facts', []), context['documents'])
            candidates = parsed.get('candidates', [])
            for candidate in candidates if isinstance(candidates, list) else []:
                if isinstance(candidate, dict) and isinstance(candidate.get('name'), str) and candidate['name'].strip():
                    self.candidates[candidate['name'].strip()] = deepcopy(candidate)
            read_facts = await self.read_docs(parsed.get('read_docids', []), state['query'])
            self._store_loop_facts(state, section, read_facts, self._available_docs)
            values = parsed.get('queries', [])
            pending = context['pending'] + (values[:2] if isinstance(values, list) else [])
            next_queries = []
            async with self._budget['lock']:
                for value in pending:
                    query = clean_query(value)
                    if (query and query.casefold() not in self._budget['originals']
                            and query.casefold() not in self._budget['queries'] and not self._near_duplicate(query)):
                        if query not in next_queries:
                            next_queries.append(query)
            thought = parsed.get('thought', '')
            self.trace.emit('plan', agent=s4_port.CURRENT_AGENT.get(), round=context['round'] + 1,
                            items=([thought] if isinstance(thought, str) and thought else []) + next_queries,
                            candidates=deepcopy(list(self.candidates.values())))
            context['round'] += 1
            context.update(phase='start', pending=next_queries,
                           done=parsed.get('done') is True or not next_queries)
            if not next_queries and parsed.get('done') is not True:
                progress(self.trace, 'no_executable_queries', '没有新的可执行查询，结束当前侦探任务。')

    async def _supplementary_research(self, state):
        queries = state.get('pending_search_queries', [])
        if isinstance(queries, list) and queries:
            section = {'id': f"supplementary_{state['iteration']}",
                'title': '补充核查', 'description': '核查审核发现的证据缺口', 'search_queries': queries[:3]}
            if self.opts.get('scout') == 'react':
                await self.react_section(state, section)
            else:
                await self.loop_section(state, section)
        state['pending_search_queries'] = []
        state['phase'] = ResearchPhase.WRITING.value
        return state


class ValidatedCritic(DRCritic):
    """拒绝无效审核结构，避免空审核在工作流内无限循环或被当作已通过。"""

    async def _review_content(self, state):
        result = await super()._review_content(state)
        assessment = result.get('overall_assessment') if isinstance(result, dict) else None
        score = assessment.get('quality_score') if isinstance(assessment, dict) else None
        verdict = assessment.get('verdict') if isinstance(assessment, dict) else None
        if (not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 10
                or verdict not in {'pass', 'needs_revision', 'major_issues'}
                or not isinstance(result.get('issues'), list)
                or any(not isinstance(issue, dict) for issue in result['issues'])
                or (verdict == 'pass' and score < 7)):
            raise ValueError('审核未返回有效评分、结论和问题列表')
        return result


def evidence_signature(state):
    """忽略随机ID，仅比较Writer可使用的事实和数据；只有来源列表增加不触发重写。"""
    facts = [{k: f.get(k) for k in ('content', 'source_url', 'quote')} for f in state['facts']]
    points = [{k: v for k, v in p.items() if k != 'id'} for p in state['data_points']]
    return json.dumps([facts, points], sort_keys=True, ensure_ascii=False, default=str)


async def run(question, trace, opts):
    """每题仅创建一份工作状态和角色实例，最多指定次数审核，保留最后审核稿结束。"""
    if opts.get('max_iterations', 3) < 1:
        raise ValueError('至少需要一次审核')
    llm = s4_port.LLM(trace=trace)
    search = None
    try:
        search = s4_port.SearchClient(**{key: opts[key] for key in ('index', 'snippet') if key in opts})
        sources = {}
        state = create_initial_state(question, uuid4().hex)
        state['max_iterations'] = opts.get('max_iterations', 3)
        state['facts'] = FactList(trace, sources)
        architect, scout = DRArchitect(llm, trace, opts), ResilientScout(llm, trace, search, sources, opts)
        writer, critic = DRWriter(llm, trace, opts), ValidatedCritic(llm, trace, opts)
        state = await retry_stage(architect, state, 'planner', '规划', opts)
        trace.emit('plan', agent='planner', constraints=state.get('_constraints', []),
                   answer_type=state.get('_answer_type', ''), hypotheses=state.get('hypotheses', []),
                   subquestions=state['outline'], items=[f"{s['title']}: {'; '.join(s['search_queries'])}" for s in state['outline']])
        state = await retry_stage(scout, state, 'scout', '侦探', opts)
        state['phase'] = ResearchPhase.WRITING.value
        state = await retry_stage(writer, state, 'writer', '执笔', opts)
        for review_index in range(state['max_iterations']):
            state = await retry_stage(critic, state, 'critic', '核查', opts)
            passed = state['phase'] == ResearchPhase.COMPLETED.value
            from .constraints import counts
            verified, total = counts(state) if opts.get('critic') == 'constraints' else (0, 0)
            trace.emit('verify', agent='critic', verdict='pass' if passed else 'fail',
                       verified=verified, total=total, note=f"证据审核：quality_score={state['quality_score']}，未解决问题={state['unresolved_issues']}")
            if passed:
                break
            if review_index + 1 >= state['max_iterations']:
                if trace.stop_reason is None:
                    trace.stop_reason = 'review_budget'
                trace.emit('plan', agent='critic', reason='review_budget',
                           items=['审核轮数耗尽，保留最后已审核稿及未解决问题；本稿未通过审核。'])
                break
            if state['phase'] == ResearchPhase.RE_RESEARCHING.value:
                before = evidence_signature(state)
                state = await retry_stage(scout, state, 'scout', '补充检索', opts)
                if evidence_signature(state) == before:
                    if trace.stop_reason is None:
                        trace.stop_reason = 'no_new_evidence'
                    trace.emit('plan', agent='critic', reason='no_new_evidence',
                               items=['补搜未增加可用事实或数据，保留已审核稿；未解决问题仍保留。'])
                    break
                state['draft_sections'], state['final_report'], state['references'] = {}, '', []
                for section in state['outline']:
                    section['status'] = 'researching'
                state['phase'] = ResearchPhase.WRITING.value
                state = await retry_stage(writer, state, 'writer', '执笔', opts)
            elif state['phase'] == ResearchPhase.REVISING.value:
                state = await retry_stage(writer, state, 'writer', '修订', opts)
            else:
                break
        if opts.get('critic') == 'constraints':
            from .constraints import answer_context, cap_answer
            answer = await retry_operation(lambda: _extract(question, state, llm, trace, sources,
                                            answer_suffix=answer_context(state)),
                                           trace, 'answer', opts.get('retries', 2))
            return cap_answer(answer, state)
        return await retry_operation(lambda: _extract(question, state, llm, trace, sources),
                                     trace, 'answer', opts.get('retries', 2))
    finally:
        try:
            if search is not None:
                await search.close()
        finally:
            await llm.close()
