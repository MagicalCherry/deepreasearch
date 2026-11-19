// 用途：流程块与历史源码联动；提供完整文件和当前步骤两个只读代码视图，构建时内嵌到HTML。
let codeTab='step', selectedStep=0, selectedPart=0, panelOpen=false, codeTarget=null;
const OLD='app/s4/deep_research_v2/agents/', TEAM='app/agents/dr/team.py', PORT='app/agents/s4_port.py';
let detailView='main';
function coarseDetailGraph(){
 const pipe=v?'app/agents/dr/pipeline.py':PORT;
 const n=(title,sub,path,symbol,extra={})=>({title,sub,path,symbol,...extra});
 const scout=OLD+'scout.py',writer=OLD+'writer.py',critic=OLD+'critic.py',architect=OLD+'architect.py';
 const searchPath=v>=2?TEAM:PORT,searchSymbol=v>=2?'DRScout._execute_search':'CorpusScout._execute_search';
 if(node===0)return [n('进入 Chief','初始规划阶段',architect,'ChiefArchitect.process'),n('记录开始消息','research_step / thought',architect,'ChiefArchitect._initial_planning'),n('LLM 生成规划',v?'按约束拆题':'行业研究模板',v?TEAM:architect,v?'DRArchitect.call_llm':'ChiefArchitect._initial_planning'),n('解析、检查并重试','最多3次；检查outline至少3节',architect,'ChiefArchitect._initial_planning'),n('有可解析的结果？','重试结束后的实际检查',architect,'ChiefArchitect._initial_planning',{decision:true,alt:'记录错误并返回'}),n('更新大纲与假设',v?'同时保留约束和答案类型':'保存研究问题与实体',v?TEAM:architect,v?'DRArchitect._initial_planning':'ChiefArchitect._initial_planning'),n('发送 plan 事件','交给 Scout',pipe,'_run_once')];
 if(node===1){
  if(detailView==='search')return v>=2?[n('清理原检索词','去引号、OR、site等',TEAM,'clean_query'),n('检索词有效？','占位符或过短 → 无效',TEAM,'DRScout._execute_search',{decision:true,alt:'返回空列表'}),...(v>=4?[n('原查询可继续？','预算未满，且没有重复',TEAM,'DRScout._execute_search',{decision:true,alt:'返回空列表'})]:[]),n('LLM 扩写两个角度','原查询 + 最多2条有效扩写',TEAM,'DRScout._execute_search'),n('逐条执行实际搜索',v>=4?'逐条查重、预留预算；满50即停':'本版没有整题搜索上限',TEAM,'DRScout._execute_search'),n('RRF 合并结果','按URL去重，k=60',TEAM,'merge_rrf')]:[n('接收检索词','设置返回条数',PORT,'CorpusScout._execute_search'),n('调用固定语料搜索','返回标题、摘要和docid',PORT,'CorpusScout._execute_search'),n('记录搜索事件','保存URL与docid映射',PORT,'CorpusScout._execute_search'),n('返回结果列表','交回章节研究',PORT,'CorpusScout._execute_search')];
  if(detailView==='read')return v>=4?[n('分析给出 docs_to_read','只接收已检索到的文档',TEAM,'DRScout._hypothesis_analysis'),n('文档可读？','真实docid、未读过、未满8篇',TEAM,'DRScout.read_docs',{decision:true,alt:'跳过此文档'}),n('预留阅读名额','共享锁；每次最多2篇',TEAM,'DRScout.read_docs'),n('读取正文并发 read','每篇最多8000 token',TEAM,'DRScout.read_docs'),n('正文有内容？','空正文不调用阅读模型',TEAM,'DRScout.read_docs',{decision:true,alt:'跳过提取'}),n('LLM 提取证据','事实与直接答案线索',TEAM,'DRScout.read_docs'),n('核对引用片段','quote必须出现在正文中',TEAM,'DRScout.read_docs'),n('返回有效事实','并入extracted_facts；继续剩余文档',TEAM,'DRScout._hypothesis_analysis')]:[n('正文阅读尚未接通','v1.4才调用read_docs',scout,'DeepScout.deep_read_url')];
  if(detailView==='supplement')return [n('读取待查检索词','pending_search_queries',scout,'DeepScout._supplementary_research'),n('有待查查询？','没有查询则直接回写作',scout,'DeepScout._supplementary_research',{decision:true,alt:'回到 Writer'}),n('执行补充搜索','通过当前版本_execute_search',searchPath,searchSymbol),n('分析并记录新事实','仍使用原补搜分析方法',scout,'DeepScout._analyze_supplementary_results'),n('清空待查查询','写回补充研究状态',scout,'DeepScout._supplementary_research'),n(v>=5?'清空旧稿并重置章节':'切回写作阶段',v>=5?'v1.5确保按新事实重新撰写':'旧drafted章节可能被跳过',pipe,'_run_once'),n('Writer → Critic','回到主流程',pipe,'_run_once')];
  return [n('选择待研究章节','最多3个章节并发',scout,'DeepScout.process'),n('逐条搜索章节查询','先汇总所有初始检索结果',scout,'DeepScout._research_section'),n('有搜索结果？','结果为空则直接返回',scout,'DeepScout._research_section',{decision:true,alt:'本章节返回'}),n(v>=3?'分析候选与约束':'LLM 分析摘要',v>=3?'生成事实、候选、验证查询':'生成事实和后续查询',v>=3?TEAM:scout,v>=3?'DRScout._hypothesis_analysis':'DeepScout._analyze_search_results'),...(v>=4?[n('按选择读取正文','docs_to_read → read_docs',TEAM,'DRScout._hypothesis_analysis')]:[]),n('有分析结果？','没有分析则跳过提取与追踪',scout,'DeepScout._research_section',{decision:true,alt:'标记章节后返回'}),n('事实去重并写入状态','事实、数据点、图谱、假设、洞察',scout,'DeepScout._research_section'),n('按条件追踪新线索',v>=3?'source_tracing清空；验证查询优先':'先信源追溯，再follow_up',scout,'DeepScout._research_section'),n('深搜并继续分析','每层最多2条；默认最深2层',scout,'DeepScout._execute_deep_search'),n('章节完成，等待汇合','所有并发任务结束后回Writer',scout,'DeepScout.process')];
 }
 if(node===2)return v>=5?[n('进入写作或修订','修订路径先重置草稿和章节',writer,'LeadWriter.process'),n('遍历需写作的章节','drafted/final章节跳过',writer,'LeadWriter._write_report'),n('是第一个章节？','整题只写一份',TEAM,'DRWriter._write_section',{decision:true,alt:'留空→继续章节循环'}),n('LLM 写答案备忘录','全部事实、数据、约束和反馈',TEAM,'DRWriter._write_section'),n('保存备忘录与引用','引用URL须已存在于事实中',TEAM,'DRWriter._write_section'),n('发送候选答案事件','best_answer → plan',TEAM,'DRWriter._write_section'),n('直接拼接完整备忘录','不再调用整合LLM',TEAM,'DRWriter._synthesize_report'),n('转入审核并发报告事件','phase=reviewing；stage_output',PORT,'_step')]:[n('进入写作或修订','由phase选择方法',writer,'LeadWriter.process'),n('遍历需写作的章节','跳过drafted/final',writer,'LeadWriter._write_report'),n('收集章节相关事实','无关联则回退前10条事实',writer,'LeadWriter._write_section'),n('LLM 逐章写正文','记录章节草稿与引用',writer,'LeadWriter._write_section'),n('LLM 整合完整报告','解析失败则拼接已有章节',writer,'LeadWriter._synthesize_report'),n('转入审核并发报告事件','修订路径则调用_revise_report',PORT,'_step')];
 if(node===3)return [n('当前是审核阶段？','其他phase直接返回',critic,'CriticMaster.process',{decision:true,alt:'不处理并返回'}),n('准备草稿与事实摘要','草稿、事实和数据有截断',critic,'CriticMaster._review_content'),n('LLM 返回审核结果',v>=5?'实际提示词为证据核查':'原报告质量审核',critic,'CriticMaster._review_content'),n('有审核结果？','无结果不更新审核状态',critic,'CriticMaster.process',{decision:true,alt:'保持状态返回'}),n('保存反馈、分数与问题数','critic_feedback等',critic,'CriticMaster.process'),n('审核通过？','verdict == pass',critic,'CriticMaster.process',{decision:true,alt:'继续判断',vertical:'否',side:'是',altTerminal:'完成审核'}),n('已到迭代上限？','iteration >= max_iterations',critic,'CriticMaster.process',{decision:true,alt:'强制完成',vertical:'否',side:'是'}),n('满足补搜路由？','查询存在，搜索类严重问题占比>30%等',critic,'CriticMaster._analyze_issues_for_routing',{decision:true,alt:'Writer修订',vertical:'是',side:'否'}),n('设置补搜查询并增轮数','pending_search_queries；iteration+1',critic,'CriticMaster.process'),n('返回 Scout 补搜','文字修订分支同样iteration+1',pipe,'_run_once')];
 return [n('读取报告与全部事实','映射source_url到docid',PORT,'_extract'),n('LLM 抽取最终答案','Explanation / Exact Answer / Confidence',PORT,'_extract'),n('答案不够具体？','空答案或Unknown等',PORT,'_extract',{decision:true,alt:'直接返回答案',vertical:'是',side:'否'}),n('再请求一次具体候选','要求低置信度表达不确定性',PORT,'_extract'),n('返回最终文字','之后runner解析并保存',PORT,'_extract')];
}
function bindings(){return detailGraph().map(n=>[n.path,n.symbol])}
function esc(t){return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function highlight(line){
 const re=/(#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b(?:async|await|def|class|return|if|elif|else|for|while|in|not|and|or|from|import|with|as|try|except|finally|raise|True|False|None|super|self)\b|\b\d+\b)/g;
 let out='',last=0;
 for(const m of line.matchAll(re)){out+=esc(line.slice(last,m.index));const t=m[0],cl=t[0]==='#'?'comment':t[0]==='"'||t[0]==="'"?'string':/^\d/.test(t)?'number':'keyword';out+='<span class="syn-'+cl+'">'+esc(t)+'</span>';last=m.index+t.length}
 return out+esc(line.slice(last));
}
function renderDetail(){
 const steps=detailGraph();selectedStep=Math.min(selectedStep,steps.length-1);$('steps').hidden=true;
 const views=node===1?[['main','章节研究'],['search','单次检索'],['read','正文阅读'],['supplement','补充研究']]:node===3?[['main','审核入口'],['review','审核调用'],['route','分流规则']]:node===2?[['main','撰写'],['revise','文字修订']]:[];
 const tabs=views.length?'<div class="detail-tabs">'+views.map(([id,t])=>'<button data-view="'+id+'" class="'+(detailView===id?'active':'')+'">'+t+'</button>').join('')+'</div>':'';
 const x=270,w=260,gap=126,top=20,height=steps.length*gap+35;
 let edges='',nodes='';
 steps.forEach((step,i)=>{const y=top+i*gap,cy=y+37,decision=step.decision;
  if(i<steps.length-1){edges+='<path class="detail-wire" d="M'+x+' '+(y+74)+'V'+(y+gap)+'"/>';if(decision)edges+='<text class="edge-word" x="'+(x-18)+'" y="'+(y+105)+'">'+(step.vertical||'是')+'</text>'}
  if(decision){edges+='<path class="detail-wire" d="M'+(x+130)+' '+cy+'H478"/><text class="edge-word" x="439" y="'+(cy-9)+'">'+(step.side||'否')+'</text>';nodes+='<rect class="detail-exit" x="480" y="'+(cy-26)+'" width="146" height="52" rx="25"/><text class="exit-word" x="553" y="'+(cy+5)+'">'+esc(step.altTerminal||step.alt)+'</text>'}
  nodes+='<g tabindex="0" role="button" class="detail-node '+(i===selectedStep?'selected':'')+'" data-step="'+i+'" aria-label="'+esc(step.title)+'">'+(decision?'<path class="detail-diamond" d="M'+x+' '+y+'L'+(x+130)+' '+cy+'L'+x+' '+(y+74)+'L'+(x-130)+' '+cy+'Z"/>':'<rect class="detail-box" x="'+(x-130)+'" y="'+y+'" width="260" height="74" rx="8"/>')+'<text class="detail-title" x="'+x+'" y="'+(y+32)+'">'+esc(step.title)+'</text><text class="detail-sub" x="'+x+'" y="'+(y+55)+'">'+esc(step.sub.length>23?step.sub.slice(0,22)+'…':step.sub)+'</text></g>';
 });
 $('detailDiagram').innerHTML='<div class="density-tabs"><button data-density="compact" class="'+(detailDensity==='compact'?'active':'')+'">简明流程</button><button data-density="fine" class="'+(detailDensity==='fine'?'active':'')+'">展开细节</button></div>'+tabs+'<p class="mini muted">矩形：处理　菱形：判断　点击节点阅读对应函数</p><div class="detail-scroll"><svg class="detail-svg" viewBox="0 0 650 '+height+'" role="group" aria-label="'+labels[node]+'内部程序流程图"><defs><marker id="detailTip" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10Z" fill="#7b8da9"/></marker></defs>'+edges+nodes+'</svg></div><p class="mini muted">节点按执行顺序展开；条件循环中的操作以当前分支为准。点击可看该步代码、作用说明与完整文件。</p>';
 $('detailDiagram').querySelectorAll('[data-density]').forEach(b=>b.onclick=()=>{detailDensity=b.dataset.density;selectedStep=0;selectedPart=0;renderDetail()});
 $('detailDiagram').querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{detailView=b.dataset.view;selectedStep=0;renderDetail()});
 $('detailDiagram').querySelectorAll('[data-step]').forEach(b=>{const action=()=>{selectedStep=Number(b.dataset.step);selectedPart=0;openCode()};b.onclick=action;b.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();action()}}});
 if(panelOpen){showCode();requestAnimationFrame(()=>{const scroll=$('detailDiagram').querySelector('.detail-scroll');if(scroll)scroll.scrollTop=Math.max(0,selectedStep*126-100)})}
}
function openCode(){const wasOpen=panelOpen;panelOpen=true;$('codeDrawer').classList.add('open');$('drawerShade').hidden=false;document.body.classList.add('drawer-open');renderDetail();if(!wasOpen)requestAnimationFrame(()=>{$('detailDiagram').closest('aside').scrollIntoView({block:'start',behavior:'auto'})});$('closeCode').focus({preventScroll:true})}
function closeCode(){panelOpen=false;$('codeDrawer').classList.remove('open');$('drawerShade').hidden=true;document.body.classList.remove('drawer-open')}
function showCode(){
 const group=detailGraph()[selectedStep],parts=group.parts||[group];selectedPart=Math.min(selectedPart,parts.length-1);const step=parts[selectedPart];
 const path=step.path,symbol=step.symbol,snapshot=SOURCE_DATA.snapshots[v],blob=SOURCE_DATA.blobs[snapshot.files[path]];
 $('codePart').replaceChildren(...parts.map((part,i)=>{const option=document.createElement('option');option.value=String(i);option.textContent=(i+1)+'. '+part.title;return option}));$('codePart').value=String(selectedPart);$('codePartRow').hidden=parts.length<2;
 $('readerAgent').value=String(node);$('readerVersion').value=String(v);$('drawerTitle').textContent='v1.'+v+' / '+labels[node];$('codePath').textContent=path;
 $('codeMeta').textContent='只读 · Python · 实验提交 '+snapshot.commit+' · '+symbol;
 $('stepDescription').textContent=group.title+'：'+group.sub;
 const range=blob?.ranges[symbol];
 if(!blob||!range){$('codeLines').textContent='此历史版本未包含该函数。';return}
 const lines=blob.code.split('\n'),norm=t=>t.replace(/[\s'"]/g,'');
 const candidates=step.focus?(blob.statements||[]).filter(b=>b.owner===symbol&&norm(lines.slice(b.start-1,b.end).join('\n')).includes(norm(step.focus))):[];
 candidates.sort((a,b)=>(a.end-a.start)-(b.end-b.start)||a.start-b.start);
 const picked=candidates[0],start=picked?picked.start:range[0],end=picked?picked.end:range[1];
 const first=codeTab==='step'?start:1,last=codeTab==='step'?end:lines.length;
 $('stepWhy').textContent=group.why||'这一节点聚合了相关操作；可结合完整文件查看调用前后关系。';
 $('prevStep').disabled=selectedStep===0;$('nextStep').disabled=selectedStep===detailGraph().length-1;

 $('codeLines').innerHTML=lines.slice(first-1,last).map((line,i)=>{const n=first+i;return '<div class="code-line '+(n>=start&&n<=end?'in-function':'')+'" data-line="'+n+'"><span class="line-no">'+n+'</span><span class="line-code">'+highlight(line)+'</span></div>'}).join('');
 $('codeRange').textContent='步骤 '+(selectedStep+1)+' / '+detailGraph().length+' · L'+start+'–L'+end+' · '+(picked?'当前步骤语句':'本节点关联函数');
 $('fullTab').classList.toggle('active',codeTab==='full');$('stepTab').classList.toggle('active',codeTab==='step');
 $('fullTab').setAttribute('aria-selected',codeTab==='full');$('stepTab').setAttribute('aria-selected',codeTab==='step');
 requestAnimationFrame(()=>{const row=$('codeLines').querySelector('[data-line="'+start+'"]');$('codeViewport').scrollTop=row?Math.max(0,row.offsetTop-80):0});
}
function initCodePanel(){
 const detail=document.createElement('div');detail.id='detailDiagram';$('steps').after(detail);
 const container=document.createElement('div');container.innerHTML='<div id="drawerShade" hidden></div><aside id="codeDrawer" aria-label="只读源码面板"><div class="drawer-head"><div><small>源码阅读器 / READ ONLY</small><h2 id="drawerTitle"></h2></div><button id="closeCode" aria-label="关闭代码面板">关闭 ×</button></div><div class="reader-selectors"><select id="readerVersion" aria-label="源码版本"><option value="0">v1.0</option><option value="1">v1.1</option><option value="2">v1.2</option><option value="3">v1.3</option><option value="4">v1.4</option><option value="5">v1.5</option></select><select id="readerAgent" aria-label="选择Agent"><option value="0">Chief 规划</option><option value="1">Scout 检索</option><option value="2">Writer 撰写</option><option value="3">Critic 审核</option><option value="4">答案抽取</option></select></div><p id="stepDescription"></p><div id="stepWhy"></div><label id="codePartRow">代码位置 <select id="codePart" aria-label="当前动作的代码位置"></select></label><div class="step-navigation"><button id="prevStep">← 上一步</button><button id="nextStep">下一步 →</button></div><div class="code-tabs" role="tablist"><button id="stepTab" role="tab">当前步骤</button><button id="fullTab" role="tab">完整文件</button><button id="jumpCode">定位函数 ↓</button></div><div id="codePath"></div><div id="codeMeta"></div><div id="codeViewport" tabindex="0" aria-label="只读代码内容"><div id="codeLines"></div></div><div id="codeRange"></div><p class="source-note">源码取自所选版本实际实验提交，并非当前工作区最新版。当前步骤按Python语法树定位到对应语句；完整文件高亮同一片段。跨函数调用可沿流程继续阅读。</p></aside>';
 document.body.append(container);$('codePart').onchange=e=>{selectedPart=Number(e.target.value);showCode()};$('prevStep').onclick=()=>{selectedStep=Math.max(0,selectedStep-1);selectedPart=0;renderDetail()};$('nextStep').onclick=()=>{selectedStep=Math.min(detailGraph().length-1,selectedStep+1);selectedPart=0;renderDetail()};$('readerAgent').onchange=e=>selectNode(Number(e.target.value));$('readerVersion').onchange=e=>{v=Number(e.target.value);render()};$('closeCode').onclick=closeCode;$('drawerShade').onclick=closeCode;
 $('stepTab').onclick=()=>{codeTab='step';showCode()};$('fullTab').onclick=()=>{codeTab='full';showCode()};
 $('jumpCode').onclick=()=>{showCode()};document.addEventListener('keydown',e=>{if(e.key==='Escape'&&panelOpen)closeCode()});
}
initCodePanel();
