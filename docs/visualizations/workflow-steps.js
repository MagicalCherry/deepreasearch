// 用途：把角色执行过程拆成语句级教学节点；focus定位真实源码语句，why解释该步的作用。
function detailedGraph(){
 const pipe=v?'app/agents/dr/pipeline.py':PORT,A=OLD+'architect.py',S=OLD+'scout.py',W=OLD+'writer.py',C=OLD+'critic.py';
 const step=(title,sub,path,symbol,focus,why,extra={})=>({title,sub,path,symbol,focus,why,...extra});
 const a=(title,focus,why,extra={})=>step(title,'规划函数内的具体操作',A,'ChiefArchitect._initial_planning',focus,why,extra);
 const s=(title,focus,why,extra={})=>step(title,'章节研究内的具体操作',S,'DeepScout._research_section',focus,why,extra);
 const q=(title,focus,why,extra={})=>step(title,'单次查询：清理、扩写、搜索',TEAM,'DRScout._execute_search',focus,why,extra);
 const r=(title,focus,why,extra={})=>step(title,'正文阅读内的具体操作',TEAM,'DRScout.read_docs',focus,why,extra);
 const w=(title,focus,why,extra={})=>step(title,'答案备忘录内的具体操作',TEAM,'DRWriter._write_section',focus,why,extra);
 const c=(title,focus,why,extra={})=>step(title,'审核状态处理',C,'CriticMaster.process',focus,why,extra);
 const e=(title,focus,why,extra={})=>step(title,'最终答案抽取',PORT,'_extract',focus,why,extra);
 if(node===0)return [
  step('判断当前阶段','初始任务进入_initial_planning',A,'ChiefArchitect.process','ResearchPhase.INIT','process是角色入口，先看phase，再调用具体方法。'),
  a('记录规划开始','"research_step"','把步骤状态写入state.messages；这不等于所有消息都已成为前端Trace事件。'),
  a('记录思考状态消息','"thought"','这是面向用户的状态文字，不是模型隐含思考内容。'),
  a('将题目填入提示词','prompt = self.PLANNING_PROMPT.format','format只替换题目；v1.1开始，实例的PLANNING_PROMPT已被替换。'),
  a('设置最多3次尝试','max_retries = 2','原始调用一次，加最多两次重试。'),
  a('调用LLM生成规划','response = await self.call_llm','await等待模型返回；json_mode要求JSON格式，但仍需后续解析与检查。'),
  ...(v?[step('替换为约束规划提示','初次与重试均替换',TEAM,'DRArchitect.call_llm','if self._planning_query is not None','v1.1防止父类重试时又退回行业报告提示词。这是在上一调用内部执行的覆盖方法。')]:[]),
  a('解析返回的JSON','result = self.parse_json_response','把文本解析为Python对象；解析失败可能得到空结果。'),
  a('兼容扁平大纲格式','result = self._convert_flat_to_outline','只有返回sec_1_title且缺outline时才转换。'),
  a('检查大纲能否结束重试','len(result.get("outline", [])) >= 3','满足条件break；否则有剩余次数时修改提示词再调用。最后是否继续由后面的if not result判断，不是严格完整schema验证。'),
  a('重试后仍无结果？','if not result:','没有解析结果则记录错误并返回原状态。',{decision:true,vertical:'否',side:'是',alt:'记录错误并返回'}),
  a('保存实体、问题与假设','state["hypotheses"] =','模型结果写入共享state，供Scout研究。'),
  a('补全每章的字段','processed_section =','为id、title、查询等字段补默认值，不会自动证明检索词有效。'),
  ...(v?[step('保存额外约束字段','_constraints / _answer_type',TEAM,'DRArchitect._initial_planning','state["_constraints"]','约束规划的额外信息保存在共享状态，后续Scout和Writer可以使用。')]:[]),
  step('向前端发出计划','trace.emit(plan)',pipe,'_run_once','trace.emit("plan"','流水线在Chief返回之后发送plan，接着调用Scout。')];
 if(node===1&&detailView==='search'&&v>=2)return [
  q('清理原查询','original = clean_query(query)','调用清理函数，去掉BM25不支持的搜索引擎语法。'),
  q('清理后为空？','if not original:','占位符或过短查询会变空；直接返回，不会扩写或搜索。',{decision:true,vertical:'否',side:'是',alt:'返回空列表'}),
  ...(v>=4?[
   q('取得共享预算锁',"async with self._budget['lock']",'锁保护并发章节的计数与去重；同一时间只允许一个任务修改共享预算。'),
   q('预算是否已用完？',"self._budget['search_count'] >= self.opts['max_searches']",'已到50次则记search_budget并返回。',{decision:true,vertical:'否',side:'是',alt:'停止此次检索'}),
   q('统一大小写再查重','normalized = original.casefold()','查询去空白已在clean_query完成；casefold用于大小写无关比较。'),
   q('登记此原始查询',"self._budget['originals'].add(normalized)",'同一原始查询不会反复付费扩写；已在originals或queries中会提前返回。')]:[]),
  q('调用LLM扩写查询','response = await self.call_llm','最多生成两个不同角度，保留原始查询。'),
  q('解析扩写结果','parsed = self.parse_json_response','取得JSON对象；必须有queries列表，否则抛错，不伪装成搜索成功。'),
  q('清理并合并扩写词','queries = [original]','从原始查询开始，最多加入两条有效且不重复的扩写查询。'),
  q('逐条循环执行','for rewritten in queries:','一条原查询可能变成最多三次实际搜索，而不是只计一次。'),
  ...(v>=4?[q('实际请求前预留预算',"self._budget['search_count'] += 1",'在共享锁中，先检查预算与重复查询，再登记并加计数，然后发送请求。')]:[]),
  q('调用固定语料检索','results.append(await super()._execute_search','super调用CorpusScout的真实搜索适配，并记录search事件。'),
  q('合并返回的文档','return merge_rrf(results, count)','按URL去重，以各列表中的排名计算RRF分数，取前count条。')];
 if(node===1&&detailView==='read'&&v>=4)return [
  r('确认已启用阅读',"if not self.opts.get('read_docs')",'未启用阅读或docids不是列表，直接返回空事实。'),
  r('逐篇处理所选docid','for value in docids:','分析模型选择文档；代码不会把所有搜索结果全部读一遍。'),
  r('本次已选满2篇？','if selected >= 2:','达到上限就跳出本次循环。',{decision:true,vertical:'否',side:'是',alt:'结束本次阅读'}),
  r('解析并检查docid',"docid = value.get('docid')",'支持id或含docid的对象；无效类型、非已返回文档会跳过。'),
  r('检查共享阅读名额',"if docid in self._budget['reads']",'锁内跳过已读文档；整题8篇用完则停止。'),
  r('请求前预留名额',"self._budget['reads'].add(docid)",'先占名额防止并发重复读取，失败请求也不会自动退还名额。'),
  r('获取正文','document = await self.search.document','使用docid请求正文，每篇最多8000 token。'),
  r('发送阅读事件',"self.trace.emit('read'",'Trace记录读取的文档、标题和范围，用于前端与统计。'),
  r('正文为空？','if not isinstance(text, str)','空正文跳过，不调用提取模型。',{decision:true,vertical:'否',side:'是',alt:'继续下一文档'}),
  r('调用LLM提取证据','response = await self.call_llm','把题目、约束、正文送入DOCUMENT_READING，要求事实和原文片段。'),
  r('解析阅读返回值','parsed = self.parse_json_response','不是JSON对象就抛错。'),
  r('分别处理两类信息',"for key in ('extracted_facts', 'answer_clues')",'普通事实与直接答案线索分开遍历；答案线索仍标记待核实。'),
  r('逐条核对原文片段','quote not in text','quote须非空且确实出现在正文中，否则舍弃该条；不等于已证明推论正确。'),
  r('保存带来源的事实','facts.append(','绑定实际文档来源、docid和quote，不接受模型随意换来源。'),
  r('返回本次有效事实','return facts','外层_hypothesis_analysis把这些事实并入extracted_facts。')];
 if(node===1&&detailView==='main')return [
  step('读取pending章节', '只处理尚未研究的章节',S,'DeepScout.process','pending_sections =','Scout实例共享，章节任务由asyncio.gather并发。'),
  step('创建最多3个任务','每章调用_research_section',S,'DeepScout.process','pending_sections[:3]','3是代码上限，不是每次必然产生3次有效搜索。'),
  s('取出章节检索词','search_queries =','没有search_queries字段时才回退章节标题；有字段但空列表不自动补查询。'),
  s('逐条执行初始查询','for i, query in enumerate(search_queries):','先收集这一章的所有初始查询结果，之后才统一分析。'),
  step('执行当前版检索','细节见“单次检索”',v>=2?TEAM:PORT,v>=2?'DRScout._execute_search':'CorpusScout._execute_search',v>=2?'original =':'await self.search.search','这是跨函数调用点；可切到单次检索图继续阅读。'),
  s('汇总此次检索结果','all_results.extend(results)','多个查询的结果累积到all_results。'),
  s('全部结果为空？','if not all_results:','空列表直接返回，不会调用分析模型。',{decision:true,vertical:'否',side:'是',alt:'本章节返回'}),
  s('调用结果分析','analysis = await self._analyze_search_results','v1.3起动态进入假设分析覆盖方法；之前调用原摘要分析。'),
  ...(v>=3?[step('组装摘要分析输入','每条摘要最多300字符',TEAM,'DRScout._hypothesis_analysis','documents =','普通分析最多15条，深搜分析最多6条；不是完整网页。'),step('模型返回候选与查询','同时要求事实、候选、后续查询',TEAM,'DRScout._hypothesis_analysis','response = await self.call_llm','JSON只是分析输出格式，不保证候选和事实正确。'),step('归一化候选与查询','验证查询优先',TEAM,'DRScout._normalize_hypothesis_analysis','self.candidates[name] =','候选存实例共享表；候选全名验证词置前；清空source_tracing_queries。')]:[]),
  ...(v>=4?[step('按选择读取正文','细节见“正文阅读”',TEAM,'DRScout._hypothesis_analysis',"analysis['extracted_facts'].extend",'read_docs返回后并入分析事实，随后才交回章节写入共享状态。')]:[]),
  s('遍历分析中的事实','for fact in analysis.get("extracted_facts"','没有analysis则跳过提取和追踪。'),
  s('相同事实已存在？','if self._is_duplicate_fact','重复则continue，跳过该条。',{decision:true,vertical:'否',side:'是',alt:'继续下一事实'}),
  s('写入共享facts','state["facts"].append(fact_entry)','FactList适配层同时发出fact事件；此时verified仍是False。'),
  s('写入事实附带数据点','state["data_points"].append','数据点从事实里的data_points转换而来。'),
  s('更新实体图谱与假设','entities = analysis.get','根据分析结果更新图谱、假设状态和insights，并发送观察消息。'),
  s('按条件启动后续追踪','follow_up = analysis.get','先信源追溯再follow_up；v1.3已清空前者，各取最多2条且需未到迭代上限。'),
  step('深搜、分析并继续追踪','默认最多2层',S,'DeepScout._execute_deep_search','for query in queries:','每次深搜结果立即分析；若有更深线索且depth<2则递归。'),
  step('等待所有章节结束','asyncio.gather',S,'DeepScout.process','await asyncio.gather(*tasks)','并发任务汇合后发送完成消息，流水线再把phase设为writing。')];
 if(node===2&&v>=5&&detailView!=='revise')return [
  step('按phase进入写作','writing → _write_report',W,'LeadWriter.process','ResearchPhase.WRITING','process只是入口分流，修订另有_revise_report路径。'),
  step('循环大纲章节','只写非final/drafted章节',W,'LeadWriter._write_report','for section in state["outline"]','章节已有草稿时会被跳过，所以补搜后必须重置状态。'),
  w('本版是memo模式？',"if self.opts.get('writer') != 'memo'",'不是memo则调用父类旧写作方法。',{decision:true,vertical:'是',side:'否',alt:'父类逐章写作'}),
  w('是大纲第一章节？',"if section is not state['outline'][0]",'不是第一章则写空串并标记drafted，返回章节循环。',{decision:true,vertical:'是',side:'否',alt:'留空→继续循环'}),
  w('取出备忘录提示词','from .prompts import MEMO_WRITING','提示词要求最可能答案、约束核对、未验证项和后续查询。'),
  w('组装模型输入','user_prompt=MEMO_WRITING','把question、constraints、facts、data_points、feedback序列化为JSON。'),
  w('等待LLM返回备忘录','response = await self.call_llm','json_mode=True，温度0.3；模型不直接操作state。'),
  w('把返回文本解析为对象','result = self.parse_json_response','解析之后才能读取content、citations和best_answer。'),
  w('正文是非空字符串？','if not isinstance(result, dict)','不符合要求则ValueError，外层决定是否整题重试。',{decision:true,vertical:'是',side:'否',alt:'抛出异常'}),
  w('保存正文草稿',"state['draft_sections'][section['id']]",'只更新当前第一章节对应的草稿。'),
  w('标记章节已写好',"section['status'] = 'drafted'",'标记控制后续是否再次进入_write_section。'),
  w('建立已知来源集合','known =','只从已收集facts中提取source_url。'),
  w('过滤并保存引用',"state['references'] =",'只保留URL出现在known中的引用，不代表内容已经核实。'),
  w('发送候选答案事件',"self.trace.emit('plan'",'best_answer仅用于展示，并非最终Exact Answer直接返回。'),
  step('直接拼接备忘录', '不再调用整合LLM',TEAM,'DRWriter._synthesize_report',"state['final_report'] =",'拼接所有非空章节，实际通常只有第一章有内容。'),
  step('把阶段设为审核','phase=reviewing',W,'LeadWriter._write_report','ResearchPhase.REVIEWING','Writer返回后，_step再发stage_output完整报告。')];
 if(node===2&&v>=5&&detailView==='revise')return [
  step('清空旧章节草稿','draft_sections = {}',TEAM,'DRWriter._revise_report',"state['draft_sections'] =",'文字修订也使用同一套备忘录写作约束。'),
  step('重置每章状态','status=researching',TEAM,'DRWriter._revise_report',"section['status'] =",'否则父类_write_report会跳过drafted章节。'),
  step('重新写备忘录','调用_write_report',TEAM,'DRWriter._revise_report','return await self._write_report','复用facts与critic_feedback，完成后回审核。')];
 if(node===3&&detailView==='review')return [
  step('按大纲读取章节草稿','遍历draft_sections',C,'CriticMaster._review_content','draft_content =','以大纲顺序拼接草稿。'),
  step('没有草稿则取完整报告','回退到final_report',C,'CriticMaster._review_content','if not draft_content:','保证至少尝试审核final_report，而不是只看空章节。'),
  step('整理事实摘要','最多20条，每条150字符',C,'CriticMaster._review_content','facts_summary =','Critic不是直接重读所有原文；输入有截断。'),
  step('整理数据点与大纲','最多15个数据点',C,'CriticMaster._review_content','data_summary =','把结构化字段转为提示词中的文本。'),
  step('填入审核提示词','草稿最多8000字符',C,'CriticMaster._review_content','prompt = self.REVIEW_PROMPT.format','v1.5实例使用EVIDENCE_REVIEW；父类仍负责填充字段。'),
  step('调用LLM审核','temperature=0.2',C,'CriticMaster._review_content','response = await self.call_llm','模型输出overall_assessment、issues等；这些是待解析的文本。'),
  step('解析后返回审核对象','parse_json_response',C,'CriticMaster._review_content','result = self.parse_json_response','适配层CorpusCritic在返回后把完整对象发stage_output。')];
 if(node===3&&detailView==='route')return [
  step('读取问题与遗漏项','issues / missing_aspects',C,'CriticMaster._analyze_issues_for_routing','issues =','路由读取审核结果，不会再次调用模型。'),
  step('设定搜索类问题类型','missing_source/incomplete/outdated',C,'CriticMaster._analyze_issues_for_routing','research_needed_types =','仅这三类且严重度critical/major才计为搜索类严重问题。'),
  step('逐条检查审核问题','遍历issues',C,'CriticMaster._analyze_issues_for_routing','for issue in issues:','类型和严重度影响计数；不只是看到requires_new_search就补搜。'),
  step('收集可用补搜词','要求标记为真且查询非空',C,'CriticMaster._analyze_issues_for_routing','search_queries.append(issue','只有同时满足字段要求才收集。'),
  step('加入遗漏项前3条','原函数直接当查询',C,'CriticMaster._analyze_issues_for_routing','for aspect in missing_aspects[:3]','v1.5提示词要求missing_aspects为空，缺口写进结构化issues。'),
  step('计算严重问题总数','critical / major',C,'CriticMaster._analyze_issues_for_routing','total_critical_major =','后续用它作为搜索类问题占比的分母。'),
  step('计算是否需要补搜','有查询且满足类型/占比条件',C,'CriticMaster._analyze_issues_for_routing','should_research =','三个条件组合；占比严格大于0.3，不是大于等于。'),
  step('返回路由与最多5条查询','set去重后截断',C,'CriticMaster._analyze_issues_for_routing','return {','process据should_research设re_researching或revising。')];
 if(node===3)return [
  c('阶段不是审核？','if state["phase"] !=','其他阶段直接返回。',{decision:true,vertical:'否',side:'是',alt:'直接返回'}),
  c('记录审核开始消息','self.add_message(state, "thought"','写入state消息，不是判定已经审核通过。'),
  c('等待审核对象','review_result = await self._review_content','可切换“审核调用”图了解提示词与模型调用。'),
  c('有审核结果？','if review_result:','无结果不修改审核状态。',{decision:true,vertical:'是',side:'否',alt:'保持状态返回'}),
  c('逐条登记审核问题','for issue in review_result.get','给问题分配id，resolved=False，追加critic_feedback。'),
  c('更新质量评分','state["quality_score"] =','取overall_assessment的quality_score；缺失时默认0。'),
  c('统计未解决严重问题','state["unresolved_issues"] =','这是当前审核结果中的critical/major数量。'),
  c('记录审核汇总消息','self.add_message(state, "review"','包含verdict、分数、问题数和摘要。'),
  c('取出审核结论','verdict =','缺失默认needs_revision。'),
  c('结论是pass？','if verdict == "pass":','是则phase=completed；这里不再次以代码校验分数。',{decision:true,vertical:'否',side:'是',alt:'审核完成'}),
  c('已达到迭代上限？','elif state["iteration"] >=','是则强制completed并发warning。',{decision:true,vertical:'否',side:'是',alt:'强制结束审核'}),
  c('计算下一步路由','needs_new_search =','可切换“分流规则”看每一项条件。'),
  c('需要补搜？','if needs_new_search["should_research"]','是→re_researching并保存查询；否→revising。',{decision:true,vertical:'是',side:'否',alt:'设为文字修订'}),
  c('保存待查查询','state["pending_search_queries"] =','Scout补充研究从这个字段取查询。'),
  c('迭代次数加1','state["iteration"] += 1','补搜和文字修订分支都加1；随后返回流水线。')];
 if(node===4)return [
  e('发出作答开始事件','trace.emit("agent_start"','前端显示answer泳道开始。'),
  e('把事实映射到docid','facts =','只带事实内容和实际来源编号，不读取题集答案。'),
  e('组装问题与报告输入','messages =','system指定输出格式，user包含题目、final_report和facts。'),
  e('绑定作答事件上下文','token = CURRENT_AGENT.set','保证这一调用阶段的事件归属answer。'),
  e('调用LLM抽取答案','answer = await adapter.call_llm','返回文本，并不直接取Writer的best_answer字段。'),
  e('解析简短答案字段','exact = parse(answer)','读取Exact Answer，供下一步检查。'),
  e('答案为空或Unknown等？','if not exact or re.search','若非具体答案则再请求一次。',{decision:true,vertical:'是',side:'否',alt:'返回第一次答案'}),
  e('再请求一次具体候选','"Your previous answer was non-specific','把上一次答案一起交给模型，并要求不确定时低置信度；这仍可能导致猜测。'),
  e('返回最终回答文本','return answer','无论第二次是否仍Unknown，这里都返回。'),
  e('恢复事件上下文','CURRENT_AGENT.reset(token)','finally即使return或异常也执行。')];
 if(node===2&&v<5){
  const old=(title,focus,why,extra={})=>step(title,'原版章节写作',W,detailView==='revise'?'LeadWriter._revise_report':'LeadWriter._write_section',focus,why,extra);
  if(detailView==='revise')return [old('收集未解决反馈','unresolved =','筛选critic_feedback中尚未resolved的问题。'),old('组织反馈文本','feedback_text =','把严重度、描述与建议加入修订提示词。'),old('取最近5条事实','new_facts =','这里不是所有facts，只取最后5条，每条又截取200字符。'),old('填入修订提示词','prompt = self.REVISION_PROMPT.format','原报告最多6000字符，加上反馈和新信息。'),old('调用LLM修订','response = await self.call_llm','要求revised_content及addressed_issues等字段。'),old('解析修订结果','result = self.parse_json_response','只有有revised_content时才更新报告。'),old('保存修订后报告','state["final_report"] =','直接替换final_report，原draft_sections并未同时重写。'),old('标记已解决的问题','feedback["resolved"] = True','模型返回的issue_id匹配到已有反馈时才标记。'),old('回到审核阶段','state["phase"] =','设reviewing后返回，等待Critic。')];
  return [step('按阶段选择写作入口','writing或revising',W,'LeadWriter.process','ResearchPhase.WRITING','当前图为首次写作；文字修订请切换标签。'),step('遍历未完成章节','跳过final/drafted',W,'LeadWriter._write_report','for section in state["outline"]','对每个需写章节调用_write_section。'),old('查找本章相关事实','related_facts =','通过related_sections关联当前section_id。'),old('无关联时回退前10条','if not related_facts:','有相关事实则直接使用；没有才回退，随后两种情况继续相同写作流程。'),old('将事实转成文本','facts_text =','内容、来源名、可信度会写入提示词。'),old('整理数据点与图表','data_text =','前10个数据点；图表按章节过滤。'),old('填入章节写作提示','prompt = self.SECTION_WRITING_PROMPT.format','包含题目、章节信息、事实、数据和insights等。'),old('调用LLM撰写章节','response = await self.call_llm','此处是行业报告风格，输出JSON。'),old('解析章节输出','result = self.parse_json_response','检查是否有content后才保存。'),old('保存草稿与状态','state["draft_sections"][section_id] =','保存正文，接着标记drafted。'),old('追加引用与章节消息','state["references"].append','遍历citations保存引用；随后记录完整章节消息。'),step('所有章节写完后整合','再调用一次LLM',W,'LeadWriter._synthesize_report','response = await self.call_llm','把章节与来源交给整合提示词；失败则使用已有章节拼接。'),step('写入报告后回审核','phase=reviewing',W,'LeadWriter._write_report','state["phase"] =','流水线_step随后发完整stage_output。')];
 }
 if(node===1&&detailView==='supplement'){
  const sup=(title,focus,why,extra={})=>step(title,'审核后的补充研究',S,'DeepScout._supplementary_research',focus,why,extra);
  return [sup('读取待查查询','pending_queries =','查询来自Critic写入的pending_search_queries。'),sup('没有待查查询？','if not pending_queries:','为空直接把phase设为writing并返回。',{decision:true,vertical:'否',side:'是',alt:'回到写作阶段'}),sup('记录补搜开始消息','"research_step"','在state中记录搜索阶段状态。'),sup('逐条处理最多5个查询','for query in pending_queries[:5]:','不并发处理这个列表；每条依次调用搜索。'),sup('执行当前版搜索','results = await self._execute_search','仍走版本对应的扩写、去重、预算规则。'),sup('有检索结果？','if results:','没有结果就继续下一查询。',{decision:true,vertical:'是',side:'否',alt:'继续下一查询'}),sup('调用补搜分析方法','analysis = await self._analyze_supplementary_results','这里仍是原补搜分析提示词，并非_hypothesis_analysis。'),sup('提取并去重事实','if not self._is_duplicate_fact','只有有analysis且事实不重复时才保存。'),sup('写入带补搜标记的事实','state["facts"].append','is_supplementary=True，related_sections为空列表。'),sup('清空待查查询','state["pending_search_queries"] =','已尝试的列表清空，不保证每条都找到了证据。'),sup('切回写作阶段','state["phase"] =','随后把state返回流水线。'),...(v>=5?[step('清空旧章节草稿','draft_sections = {}',pipe,'_run_once',"state['draft_sections'] =",'v1.5补搜返回后，流水线主动清空旧草稿。'),step('清空旧报告并重置章节','状态恢复researching',pipe,'_run_once',"state['final_report'] =",'防止Writer把已drafted章节跳过；随后逐章重置状态。')]:[]),step('再次调用Writer','按最新facts撰写',pipe,'_run_once','"执笔"','写完回到Critic审核回环。')];
 }
 return coarseDetailGraph();
}

// 默认按业务动作合并连续语句；条件判断独立保留，执行顺序不改变。
let detailDensity='compact';
function detailGraph(){
 const raw=detailedGraph();if(detailDensity==='fine')return raw;
 const groups=[];let pending=[];
 const flush=()=>{if(!pending.length)return;const first=pending[0],last=pending[pending.length-1];
  const names={'进入 Chief':'进入规划并记录开始','将题目填入提示词':'准备并调用规划模型','解析返回的JSON':'解析并检查规划结果','保存实体、问题与假设':'保存规划状态','读取pending章节':'准备并发章节研究','取出章节检索词':'执行章节检索','清理原查询':'清理并校验查询','取得共享预算锁':'检查预算与查询重复','调用LLM扩写查询':'扩写并解析查询','清理并合并扩写词':'执行扩写后的检索','确认已启用阅读':'准备文档阅读','解析并检查docid':'检查文档与阅读名额','请求前预留名额':'读取正文并记录事件','调用LLM提取证据':'提取并解析正文证据','分别处理两类信息':'核对并保存正文事实','按phase进入写作':'进入写作并选择章节','取出备忘录提示词':'组装输入并生成备忘录','等待LLM返回备忘录':'生成并解析备忘录','保存正文草稿':'保存草稿与来源引用','建立已知来源集合':'过滤引用并记录候选','直接拼接备忘录':'完成报告并进入审核','记录审核开始消息':'调用审核模型','逐条登记审核问题':'保存审核反馈与评分','统计未解决严重问题':'统计问题并记录审核结果','计算下一步路由':'分析审核问题并分流','保存待查查询':'保存查询并推进迭代','发出作答开始事件':'准备最终作答输入','绑定作答事件上下文':'调用模型并解析答案','再请求一次具体候选':'补充请求并返回答案','读取待查查询':'读取补搜任务','记录补搜开始消息':'准备并执行补充搜索','调用补搜分析方法':'分析并保存补搜事实','清空待查查询':'完成补搜并回写状态'};
  groups.push({...first,title:names[first.title]||first.title,sub:pending.length>1?'包含'+pending.length+'项相关操作':first.sub,parts:pending.slice(),why:pending.map((p,i)=>(i+1)+'. '+p.title+'：'+p.why).join('\n\n')});pending=[]};
 for(const item of raw){if(item.decision){flush();groups.push({...item,parts:[item]});continue}pending.push(item);if(pending.length===3)flush()}
 flush();return groups;
}
