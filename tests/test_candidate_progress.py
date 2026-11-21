"""v2.3.3候选进度保存契约：虚构候选与证据，验证后续补搜读取、合并及来源边界。"""

from copy import deepcopy
import json

from app.agents.dr.candidate_progress import merge_progress, parse_progress
from app.versions import get_version


def entry(name='Fictional Person'):
    return {'name': name, 'checked': [{'constraint': 'C1', 'status': 'supported',
            'docids': ['12'], 'note': 'Fictional excerpt supports C1'}],
            'pending': ['C2'], 'next_query': f'{name} newsletter meeting'}


def test_progress_is_parsed_separately_from_findings_and_candidates():
    report = 'Findings:\n- Fictional claim [12]\n\nCandidates:\n- Fictional Person\n\nCandidate Progress:\n' + json.dumps([entry()])
    assert parse_progress(report) == [entry()]
    assert parse_progress('Findings:\n- None\nCandidates:\n- None') == []
    assert parse_progress('Candidate Progress:\nnot json') == []


def test_progress_merges_by_name_without_losing_previous_checked_conditions():
    state = {}
    merge_progress(state, [entry()], {'12'}, 'sec_1')
    merge_progress(state, [{'name': ' fictional   PERSON ', 'checked': [
        {'constraint': 'C2', 'status': 'unresolved', 'docids': [], 'note': 'Not found yet'}],
        'pending': ['C2', 'C3'], 'next_query': 'Fictional Person research paper'}], set(), 'supplementary_1')
    progress = state['_candidate_progress']
    assert len(progress) == 1
    candidate = progress[0]
    assert {c['constraint'] for c in candidate['checked']} == {'C1', 'C2'}
    assert candidate['pending'] == ['C2', 'C3']
    assert candidate['next_query'] == 'Fictional Person research paper'
    assert len(candidate['history']) == 2
    before = deepcopy(state)
    merge_progress(state, [], set(), 'supplementary_2')
    assert state == before


def test_unseen_source_cannot_become_supported_candidate_evidence():
    state = {}
    merge_progress(state, [entry()], set(), 'sec_1')
    check = state['_candidate_progress'][0]['checked'][0]
    assert check['status'] == 'unresolved'
    assert check['docids'] == []
    assert not state.get('facts')


def test_candidate_progress_rejects_none_and_placeholder_candidates():
    state = {}
    merge_progress(state, [{'name': n} for n in ['None', 'Unknown', '[Candidate Name]', '']], set(), 'sec_1')
    assert state.get('_candidate_progress', []) == []


async def test_supplementary_scout_receives_saved_progress(monkeypatch):
    from app.agents.dr.flow_fixes import ResilientScout
    from app.agents.dr import react_scout
    from app.s4.deep_research_v2.state import create_initial_state
    from app.trace import Trace
    opts = deepcopy(get_version('v2.3.2').options)
    opts.update(candidate_progress=True, scout_citation_repair=False)
    scout = ResilientScout(None, Trace(), None, {}, opts)
    state = create_initial_state('Fictional original question', 'progress-test')
    calls = []

    async def fake_loop(llm, messages, tools, **kwargs):
        calls.append(json.loads(messages[1]['content']))
        if len(calls) == 1:
            return 'Findings:\n- None\nCandidates:\n- Fictional Person\n\nCandidate Progress:\n' + json.dumps([
                {'name': 'Fictional Person', 'checked': [], 'pending': ['C2'],
                 'next_query': 'Fictional Person newsletter meeting'}])
        return 'Findings:\n- None\nCandidates:\n- None'

    monkeypatch.setattr(react_scout, 'react_loop', fake_loop)
    for sid in ['sec_1', 'supplementary_1']:
        await scout.react_section(state, {'id': sid, 'title': 'Fictional investigation',
                                         'description': 'Check evidence', 'search_queries': []})
    assert calls[1]['candidate_progress'][0]['name'] == 'Fictional Person'
    assert calls[1]['candidate_progress'][0]['pending'] == ['C2']
    assert 'Candidate Progress:' not in str(calls[1]['peer_candidates'])
    assert state['_candidate_progress'][0]['name'] == 'Fictional Person'


def test_v233_adds_only_candidate_progress():
    assert get_version('v2.3.3').options == {**get_version('v2.3.2').options,
                                          'candidate_progress': True}
