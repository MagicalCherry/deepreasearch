// 用途：流程块与历史源码联动；提供完整文件和当前步骤两个只读代码视图，构建时内嵌到HTML。
let codeTab='step', selectedStep=0, panelOpen=false, codeTarget=null;
const OLD='app/s4/deep_research_v2/agents/', TEAM='app/agents/dr/team.py', PORT='app/agents/s4_port.py';
function bindings(){
 const pipeline=v?'app/agents/dr/pipeline.py':PORT;
 if(node===0)return [[pipeline,'_run_once'],[v?TEAM:OLD+'architect.py',v?'DRArchitect._initial_planning':'ChiefArchitect._initial_planning'],[v?TEAM:OLD+'architect.py',v?'DRArchitect.call_llm':'ChiefArchitect._initial_planning'],[pipeline,'_run_once']];
 if(node===1)return [[OLD+'scout.py','DeepScout.process'],[v>=2?TEAM:PORT,v>=2?'DRScout._execute_search':'CorpusScout._execute_search'],[v>=3?TEAM:OLD+'scout.py',v>=3?'DRScout._hypothesis_analysis':'DeepScout._analyze_search_results'],[v>=4?TEAM:OLD+'scout.py',v>=4?'DRScout.read_docs':'DeepScout.deep_read_url'],[OLD+'scout.py','DeepScout._execute_deep_search']];
 if(node===2)return v>=5?[[TEAM,'DRWriter._write_section'],[TEAM,'DRWriter._write_section'],[TEAM,'DRWriter._write_section'],[TEAM,'DRWriter._synthesize_report'],[TEAM,'DRWriter._revise_report']]:[[OLD+'writer.py','LeadWriter._write_section'],[OLD+'writer.py','LeadWriter._write_section'],[OLD+'writer.py','LeadWriter._synthesize_report'],[PORT,'_step']];
 if(node===3)return [[OLD+'critic.py','CriticMaster._review_content'],[OLD+'critic.py','CriticMaster.process'],[v>=5?TEAM:OLD+'critic.py',v>=5?'DRCritic.__init__':'CriticMaster._analyze_issues_for_routing'],[OLD+'critic.py','CriticMaster._analyze_issues_for_routing'],[PORT,'CorpusCritic._review_content']];
 return Array(4).fill([PORT,'_extract']);
}
function esc(t){return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function highlight(line){
 const re=/(#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b(?:async|await|def|class|return|if|elif|else|for|while|in|not|and|or|from|import|with|as|try|except|finally|raise|True|False|None|super|self)\b|\b\d+\b)/g;
 let out='',last=0;
 for(const m of line.matchAll(re)){out+=esc(line.slice(last,m.index));const t=m[0],cl=t[0]==='#'?'comment':t[0]==='"'||t[0]==="'"?'string':/^\d/.test(t)?'number':'keyword';out+='<span class="syn-'+cl+'">'+esc(t)+'</span>';last=m.index+t.length}
 return out+esc(line.slice(last));
}
function renderDetail(){
 const steps=nodeData(keys[node]).steps;
 $('steps').hidden=true;
 $('detailDiagram').innerHTML=steps.map((text,i)=>'<div class="detail-unit"><button class="detail-block '+(i===selectedStep?'selected':'')+'" data-step="'+i+'"><span class="step-number">'+(i+1)+'</span><span>'+esc(text)+'</span><small>查看代码 ↗</small></button>'+(i<steps.length-1?'<div class="detail-connector" aria-hidden="true">↓</div>':'')+'</div>').join('');
 $('detailDiagram').querySelectorAll('[data-step]').forEach(b=>b.onclick=()=>{selectedStep=Number(b.dataset.step);openCode()});
 if(panelOpen)showCode();
}
function openCode(){panelOpen=true;$('codeDrawer').classList.add('open');$('drawerShade').hidden=false;document.body.classList.add('drawer-open');renderDetail();$('closeCode').focus()}
function closeCode(){panelOpen=false;$('codeDrawer').classList.remove('open');$('drawerShade').hidden=true;document.body.classList.remove('drawer-open')}
function showCode(){
 const entries=bindings();codeTarget=entries[Math.min(selectedStep,entries.length-1)];
 const [path,symbol]=codeTarget,snapshot=SOURCE_DATA.snapshots[v],blob=SOURCE_DATA.blobs[snapshot.files[path]];
 $('readerAgent').value=String(node);$('readerVersion').value=String(v);$('drawerTitle').textContent='v1.'+v+' / '+labels[node];$('codePath').textContent=path;
 $('codeMeta').textContent='只读 · Python · 实验提交 '+snapshot.commit+' · '+symbol;
 $('stepDescription').textContent=nodeData(keys[node]).steps[selectedStep]||'';
 const range=blob?.ranges[symbol];
 if(!blob||!range){$('codeLines').textContent='此历史版本未包含该函数。';return}
 const [start,end]=range,lines=blob.code.split('\n'),first=codeTab==='step'?start:1,last=codeTab==='step'?end:lines.length;
 $('codeLines').innerHTML=lines.slice(first-1,last).map((line,i)=>{const n=first+i;return '<div class="code-line '+(n>=start&&n<=end?'in-function':'')+'" data-line="'+n+'"><span class="line-no">'+n+'</span><span class="line-code">'+highlight(line)+'</span></div>'}).join('');
 $('codeRange').textContent='当前函数 L'+start+'–L'+end+' · '+(codeTab==='step'?'当前步骤所在函数':'完整文件，蓝色区域为当前函数');
 $('fullTab').classList.toggle('active',codeTab==='full');$('stepTab').classList.toggle('active',codeTab==='step');
 $('fullTab').setAttribute('aria-selected',codeTab==='full');$('stepTab').setAttribute('aria-selected',codeTab==='step');
 requestAnimationFrame(()=>{const row=$('codeLines').querySelector('[data-line="'+start+'"]');$('codeViewport').scrollTop=row?Math.max(0,row.offsetTop-80):0});
}
function initCodePanel(){
 const detail=document.createElement('div');detail.id='detailDiagram';$('steps').after(detail);
 const container=document.createElement('div');container.innerHTML='<div id="drawerShade" hidden></div><aside id="codeDrawer" aria-label="只读源码面板"><div class="drawer-head"><div><small>源码阅读器 / READ ONLY</small><h2 id="drawerTitle"></h2></div><button id="closeCode" aria-label="关闭代码面板">关闭 ×</button></div><div class="reader-selectors"><select id="readerVersion" aria-label="源码版本"><option value="0">v1.0</option><option value="1">v1.1</option><option value="2">v1.2</option><option value="3">v1.3</option><option value="4">v1.4</option><option value="5">v1.5</option></select><select id="readerAgent" aria-label="选择Agent"><option value="0">Chief 规划</option><option value="1">Scout 检索</option><option value="2">Writer 撰写</option><option value="3">Critic 审核</option><option value="4">答案抽取</option></select></div><p id="stepDescription"></p><div class="code-tabs" role="tablist"><button id="stepTab" role="tab">当前步骤</button><button id="fullTab" role="tab">完整文件</button><button id="jumpCode">定位函数 ↓</button></div><div id="codePath"></div><div id="codeMeta"></div><div id="codeViewport" tabindex="0" aria-label="只读代码内容"><div id="codeLines"></div></div><div id="codeRange"></div><p class="source-note">源码取自所选版本实际实验提交，并非当前工作区最新版。当前步骤展示其所在函数；一项流程可能包含多个调用，可沿函数名继续在完整文件中阅读。</p></aside>';
 document.body.append(container);$('readerAgent').onchange=e=>selectNode(Number(e.target.value));$('readerVersion').onchange=e=>{v=Number(e.target.value);render()};$('closeCode').onclick=closeCode;$('drawerShade').onclick=closeCode;
 $('stepTab').onclick=()=>{codeTab='step';showCode()};$('fullTab').onclick=()=>{codeTab='full';showCode()};
 $('jumpCode').onclick=()=>{showCode()};document.addEventListener('keydown',e=>{if(e.key==='Escape'&&panelOpen)closeCode()});
}
initCodePanel();
