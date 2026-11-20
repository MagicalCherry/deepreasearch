"""虚构场景检查v1.8报告解析、ReAct实际入口、共享预算、异常及Writer报告交接，不访问云端。"""

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.agents import s4_port
from app.agents.dr.flow_fixes import ResilientScout
from app.agents.dr.react_scout import ScoutTools, parse_scout_report, shrink_tool_results
from app.agents.dr.react_scout import citation_issues, CITATION_RULES
from app.agents.dr.team import DRWriter
from app.agents.react import Tools, react_loop
from app.llm import LLMError
from app.s4.deep_research_v2.state import create_initial_state, ResearchPhase
from app.trace import Trace
from app.versions import get_version
from scripts.compare_recall_bands import group_records


def test_parse_scout_report_multiline_and_candidates():
    report = '**Findings:**\n- Fictional supported\n  fact [12]\n- Another fact [13] [14].\n- Unsupported claim\n\n**Candidates:**\n- Demo Person\n- Demo Person\n- Second Person'
    parsed = parse_scout_report(report)
    assert parsed['facts'] == [{'content':'Fictional supported fact','docid':'12'},
                              {'content':'Another fact','docid':'13'}, {'content':'Another fact','docid':'14'}]
    assert parsed['candidates'] == ['Demo Person','Second Person']


@pytest.mark.parametrize('report', ['', 'No evidence.', 'Findings:\nNone\nCandidates:\nNone'])
def test_empty_report_never_invents_facts(report):
    assert parse_scout_report(report) == {'facts':[], 'candidates':[]}


class Search:
    def __init__(self):
        self.queries, self.reads = [], []

    async def search(self, query, k=5):
        self.queries.append(query)
        await asyncio.sleep(0)
        return {'results':[{'docid':'12','title':'Fictional document','score':1,'snippet':'Fictional evidence'}]}

    async def document(self, docid, max_tokens=None):
        self.reads.append(docid)
        await asyncio.sleep(0)
        return {'docid':docid,'title':'Fictional','text':'Fictional evidence'}


def setup_scout(model=None, **changes):
    trace, search = Trace(), Search()
    opts = {**get_version('v1.8').options, **changes}
    scout = ResilientScout(model, trace, search, {}, opts)
    state = create_initial_state('Fictional question', 'react-test')
    state['facts'] = s4_port.FactList(trace, scout.sources)
    state['_constraints'] = ['Fictional constraint']
    section = {'id':'sec_1','title':'Fictional identity','description':'Find the entity',
               'status':'pending','search_queries':['fictional initial clue']}
    state['outline'] = [section]
    return scout, state, section, search


def reply(text=None, name=None, args=None):
    calls = [SimpleNamespace(id='offline-call',function=SimpleNamespace(name=name,arguments=json.dumps(args)))] if name else None
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text,tool_calls=calls))])


class Model:
    def __init__(self, outcomes):
        self.outcomes, self.requests = list(outcomes), []

    async def chat(self, messages, **kwargs):
        self.requests.append({'messages':deepcopy(messages), **kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


async def test_resilient_entry_uses_react_and_stores_only_real_sources():
    model = Model([reply(name='search',args={'query':'fictional evidence identity'}),
                   reply(name='get_document',args={'docid':'12'}),
                   reply('Findings:\n- Supported finding [12]\n- Invented source [999]\nCandidates:\n- Demo')])
    scout, state, section, search = setup_scout(model)
    token = s4_port.CURRENT_AGENT.set('scout-1')
    try:
        await scout.investigate(state, section)
    finally:
        s4_port.CURRENT_AGENT.reset(token)
    assert len(search.queries)==1 and search.reads==['12']
    assert [f['docid'] for f in state['facts']]==['12']
    assert 'sec_1' in state['_scout_reports']
    assert state['_scout_reports']['sec_1']['tool_calls']==2
    assert scout.candidates['Demo']['status']=='hypothesis'
    assert all(e['agent']=='scout-1' for e in scout.trace.events)
    assert model.requests[0]['truncate'] is shrink_tool_results
    assert 'Fictional constraint' in model.requests[0]['messages'][1]['content']


async def test_parallel_searches_share_last_question_slot():
    scout, state, _, search = setup_scout()
    scout._budget['search_count']=49
    tools = [ScoutTools(scout,state,'scout-1'),ScoutTools(scout,state,'scout-2')]
    results = await asyncio.gather(tools[0].call('search',{'query':'fictional alpha identity'}),
                                   tools[1].call('search',{'query':'different beta history'}))
    assert len(search.queries)==1 and scout._budget['search_count']==50
    assert sum(isinstance(r,dict) and 'error' in r for r in results)==1


async def test_read_requires_observed_id_and_shared_cache():
    scout, state, _, search = setup_scout()
    first, second = ScoutTools(scout,state,'scout-1'), ScoutTools(scout,state,'scout-2')
    assert (await first.call('get_document',{'docid':'999'}))['error']
    await first.call('search',{'query':'fictional alpha evidence'})
    await second.call('search',{'query':'different beta history'})
    documents = await asyncio.gather(first.call('get_document',{'docid':'12'}),second.call('get_document',{'docid':'12'}))
    assert search.reads==['12'] and scout.trace.n_read==1
    assert all(d['text']=='Fictional evidence' for d in documents)


async def test_read_limit_and_repeated_query_return_actionable_errors():
    scout, state, _, search = setup_scout(max_reads=0)
    tools = ScoutTools(scout,state,'scout-1')
    await tools.call('search',{'query':'fictional initial evidence'})
    assert 'error' in await tools.call('search',{'query':'fictional initial evidence'})
    assert 'error' in await tools.call('get_document',{'docid':'12'})
    assert search.reads==[] and len(search.queries)==1


async def test_fifty_searches_prevent_new_scout_model_call():
    model = Model([])
    scout, state, section, _ = setup_scout(model)
    scout._budget['search_count']=50
    await scout.investigate(state, section)
    assert not model.requests
    assert scout.trace.events[-1]['reason']=='search_budget'


async def test_near_exhausted_budget_limits_section_to_two_tools():
    model=Model([reply(name='search',args={'query':'fictional identity evidence'}),
                 reply(name='get_document',args={'docid':'12'}),
                 reply('Findings:\n- Demo finding [12]\nCandidates:\n- Demo')])
    scout,state,section,_=setup_scout(model)
    scout._budget['search_count']=49
    await scout.investigate(state, section)
    assert scout._react_sections['sec_1']['budget']==2
    assert not model.requests[-1].get('tools')
    assert 'Findings' in model.requests[-1]['messages'][-1]['content']
    assert scout.trace.stop_reason is None


async def test_content_filter_abandons_only_current_section():
    model=Model([LLMError('content_filter','Fictional blocked content')])
    scout,state,section,_=setup_scout(model)
    await scout.investigate(state,section)
    assert not state['facts']
    assert scout.trace.events[-1]['reason']=='content_filter'


@pytest.mark.parametrize('error',[LLMError('arrearage','offline'),asyncio.CancelledError()])
async def test_arrearage_and_cancellation_are_not_swallowed(error):
    scout,state,section,_=setup_scout(Model([error]))
    with pytest.raises(type(error)):
        await scout.investigate(state,section)
    assert section['status']=='pending'


async def test_supplementary_research_also_uses_react():
    scout,state,_,_=setup_scout(Model([reply('Findings:\nNone\nCandidates:\nNone')]))
    state.update(iteration=1,pending_search_queries=['fictional extra evidence'])
    await scout._supplementary_research(state)
    assert 'supplementary_1' in state['_scout_reports']
    assert state['phase']==ResearchPhase.WRITING.value


def test_shrink_preserves_protocol_and_original_messages():
    messages=[{'role':'user','content':'Question'}, {'role':'tool','tool_call_id':'id','content':'abcdefgh'}]
    shortened=shrink_tool_results(messages)
    assert shortened[0]==messages[0] and shortened[1]['tool_call_id']=='id'
    assert shortened[1]['content']=='abcd' and messages[1]['content']=='abcdefgh'


async def test_max_turns_returns_last_text_when_closing_response_is_empty():
    model=Model([reply('Partial findings',name='search',args={'query':'fictional query'}),reply('')])
    trace=Trace()
    tools=Tools(Search(),trace,agent='scout-1')
    text=await react_loop(model,[{'role':'user','content':'Findings please'}],tools,max_turns=1,
                          raise_on_max_turns=False,shrink=shrink_tool_results)
    assert text=='Partial findings'
    assert trace.stop_reason is None
    assert trace.events[-1]['reason']=='max_turns'


async def test_writer_receives_reports_only_in_react_version(monkeypatch):
    scout,state,section,_=setup_scout()
    state['_scout_reports']={'sec_1':{'report':'Findings:\nDemo [12]'}}
    captured=[]
    for version in ('v1.7','v1.8'):
        writer=DRWriter(None,scout.trace,get_version(version).options)
        async def fake_call(**kwargs):
            captured.append(kwargs['user_prompt'])
            return json.dumps({'content':'Fictional memo','citations':[],'best_answer':'Demo'})
        monkeypatch.setattr(writer,'call_llm',fake_call)
        await writer._write_section(state,section)
    assert 'scout_reports' not in captured[0] and 'scout_reports' in captured[1]


async def test_retry_keeps_spent_tools_and_observed_results():
    model=Model([reply(name='search',args={'query':'fictional identity evidence'}),
                 LLMError('other','offline temporary failure'),
                 reply('Findings:\n- Recovered finding [12]\nCandidates:\n- Demo')])
    scout,state,section,search=setup_scout(model)
    with pytest.raises(LLMError):
        await scout.investigate(state,section)
    assert scout._react_sections['sec_1']['tools'].used==1
    await scout.investigate(state,section)
    assert len(search.queries)==1
    assert state['facts'][0]['docid']=='12'
    assert 'previously_observed_results' in model.requests[-1]['messages'][1]['content']


def test_recall_bands_boundaries_and_stale_judgement():
    questions={str(i):{'evidence_docids':['1','2']} for i in range(3)}
    results={str(i):{'response':'Demo','retrieved_docids':ids} for i,ids in enumerate(([],['1'],['1','2']))}
    judged={key:{**value,'judge':{'correct':True}} for key,value in results.items()}
    bands=group_records(results,judged,questions)
    assert bands['0']['n']==1
    assert bands['0<recall<50%']['n']==0
    assert bands['recall>=50%']['n']==2
    judged['0']['response']='Old'
    with pytest.raises(ValueError):
        group_records(results,judged,questions)


@pytest.mark.parametrize('report,invalid,uncited', [
    ('Findings:\n- Demo [12]\nCandidates:\n- Demo', [], 0),
    ('Findings:\n- Demo [1]\nCandidates:\n- Demo', ['1'], 0),
    ('Findings:\n- Demo without source\nCandidates:\n- Demo', [], 1),
    ('Findings:\n- Earlier [1], final [12]\nCandidates:\n- Demo', ['1'], 0),
    ('Findings:\nNone\nCandidates:\n- Candidate [99]', [], 0),
    ('**Findings:**\n- Multiline\n  finding [12].\n\n**Candidates:**\n- Demo', [], 0),
])
def test_citation_validation_checks_actual_findings_only(report, invalid, uncited):
    assert citation_issues(report, {'12': {}}) == {
        'invalid_docids': invalid, 'uncited_findings': uncited}


async def test_v191_repairs_reference_number_using_read_evidence_and_stores_fact():
    from app.agents.dr.flow_fixes import evidence_signature
    model = Model([
        reply(name='search', args={'query':'fictional cultivar evidence'}),
        reply(name='get_document', args={'docid':'12'}),
        reply('Findings:\n- Fictional evidence [1]\nCandidates:\n- Demo cultivar'),
        reply('Findings:\n- Fictional evidence [12]\nCandidates:\n- Demo cultivar'),
    ])
    scout, state, section, search = setup_scout(model, scout_citation_repair=True)
    before = evidence_signature(state)
    await scout.investigate(state, section)
    assert evidence_signature(state) != before
    assert [f['docid'] for f in state['facts']] == ['12']
    assert len(search.queries) == 1 and search.reads == ['12']
    assert scout._react_sections['sec_1']['tools'].used == 2
    assert CITATION_RULES in model.requests[0]['messages'][0]['content']
    repair = model.requests[-1]
    assert 'tools' not in repair and repair['max_tokens'] == 4096
    payload = json.loads(repair['messages'][1]['content'])
    assert payload['read_documents']['12']['text'] == 'Fictional evidence'
    assert payload['errors']['invalid_docids'] == ['1']
    assert '[12]' in state['_scout_reports']['sec_1']['report']
    assert any(e.get('kind') == 'scout_report_before_citation_repair' and '[1]' in e['content']
               for e in scout.trace.events)
    validations = [e for e in scout.trace.events if e.get('kind') == 'citation_validation']
    assert validations[-1]['valid'] and validations[-1]['repair_attempted']


async def test_v191_valid_report_needs_no_extra_model_call():
    model = Model([reply(name='search', args={'query':'fictional identity evidence'}),
                   reply('Findings:\n- Supported [12]\nCandidates:\n- Demo')])
    scout, state, section, _ = setup_scout(model, scout_citation_repair=True)
    await scout.investigate(state, section)
    assert len(model.requests) == 2 and len(state['facts']) == 1
    assert not scout._react_sections['sec_1'].get('citation_repair_used')


async def test_v191_never_guesses_id_and_limits_repair_across_retries():
    invalid = 'Findings:\n- Unsupported mapping [1]\nCandidates:\n- Demo'
    model = Model([reply(name='search', args={'query':'fictional identity evidence'}),
                   reply(invalid), reply(invalid), reply(invalid)])
    scout, state, section, _ = setup_scout(model, scout_citation_repair=True)
    await scout.investigate(state, section)
    await scout.investigate(state, section)
    assert len(model.requests) == 4
    assert not state['facts']
    assert sum(e.get('repair_attempted') is True for e in scout.trace.events) == 1
    assert scout.trace.events[-2]['kind'] == 'scout_report'


async def test_v191_no_observed_source_cannot_be_repaired():
    model = Model([reply('Findings:\n- Invented [1]\nCandidates:\n- Demo')])
    scout, state, section, _ = setup_scout(model, scout_citation_repair=True)
    await scout.investigate(state, section)
    assert len(model.requests) == 1 and not state['facts']


@pytest.mark.parametrize('error', [LLMError('arrearage','offline'), asyncio.CancelledError()])
async def test_v191_repair_propagates_arrearage_and_cancellation(error):
    model = Model([reply(name='search', args={'query':'fictional identity evidence'}),
                   reply('Findings:\n- Demo [1]\nCandidates:\n- Demo'), error])
    scout, state, section, _ = setup_scout(model, scout_citation_repair=True)
    with pytest.raises(type(error)):
        await scout.investigate(state, section)
    assert scout._react_sections['sec_1']['citation_repair_used']


async def test_v191_repair_filter_failure_keeps_valid_original_findings():
    model = Model([reply(name='search', args={'query':'fictional identity evidence'}),
                   reply('Findings:\n- Supported [12]\n- Bad [1]\nCandidates:\n- Demo'),
                   LLMError('content_filter', 'offline')])
    scout, state, section, _ = setup_scout(model, scout_citation_repair=True)
    await scout.investigate(state, section)
    assert [f['docid'] for f in state['facts']] == ['12']
    assert any(e.get('reason') == 'citation_repair_failed' for e in scout.trace.events)
