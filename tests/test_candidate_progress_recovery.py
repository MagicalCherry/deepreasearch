"""v2.3.4虚构数据验证候选格式诊断、部分候选保存和自动翻页上限，不调用模型。"""

from copy import deepcopy
import json

import pytest

from app.agents.dr.candidate_progress import inspect_progress, merge_progress
from app.versions import get_version


@pytest.mark.parametrize('report,status', [
    ('Findings:\n- None\nCandidates:\n- None', 'missing'),
    ('Candidate Progress:\nnot json', 'invalid_json'),
    ('Candidate Progress:\n42', 'invalid_schema'),
    ('Candidate Progress:\n[]', 'empty'),
    ('Candidate Progress:\n[{"name":"Fictional Person"}]', 'valid'),
])
def test_empty_progress_has_explicit_diagnostic_reason(report, status):
    assert inspect_progress(report)['status'] == status


def test_partial_candidates_are_not_discarded_when_no_answer_candidate_exists():
    report = 'Candidate Progress:\n' + json.dumps({
        'partial_candidates': [{'name': 'Fictional Person', 'pending': ['C2']}],
        'answer_candidates': []})
    audit = inspect_progress(report)
    assert audit['status'] == 'valid'
    assert audit['updates'][0]['name'] == 'Fictional Person'
    assert audit['updates'][0]['candidate_kind'] == 'partial'


def test_preserve_supported_checks_when_new_section_cannot_reobserve_old_source():
    state = {}
    merge_progress(state, [{'name': 'Fictional Person', 'checked': [
        {'constraint': 'C1', 'status': 'supported', 'docids': ['12'], 'note': 'Observed evidence'}],
        'pending': ['C2']}], {'12'}, 'sec_1')
    merge_progress(state, [{'name': 'Fictional Person', 'checked': [
        {'constraint': 'C1', 'status': 'supported', 'docids': ['12'], 'note': 'Previous finding'}],
        'pending': []}], set(), 'supplementary_1', preserve_evidence=True)
    candidate = state['_candidate_progress'][0]
    assert candidate['checked'][0]['status'] == 'supported'
    assert candidate['checked'][0]['docids'] == ['12']
    assert 'C2' in candidate['pending']
    assert len(candidate['history']) == 2


async def test_automatic_review_cap_does_not_consume_all_exploration_calls():
    from app.agents.dr.flow_fixes import ResilientScout
    from app.s4.deep_research_v2.state import create_initial_state
    from app.trace import Trace

    class Search:
        async def search(self, query, k=200):
            return {'results': [{'docid': str(i), 'title': 'Fictional title',
                                 'snippet': 'Fictional excerpt', 'score': 1} for i in range(30)]}

    opts = deepcopy(get_version('v2.3.3').options)
    opts['max_auto_reviews'] = 2
    scout = ResilientScout(None, Trace(), Search(), {}, opts)
    state = create_initial_state('Fictional question', 'bounded-review')
    tools = scout.scout_tools(state, 'scout-1')
    queries = ['alpha bravo charlie', 'delta echo foxtrot', 'golf hotel india',
               'juliet kilo lima', 'mike november oscar', 'papa quebec romeo',
               'sierra tango uniform', 'victor whiskey xray', 'yankee zulu april',
               'may june july', 'august september october', 'november winter spring']
    results = [await tools.call('search', {'query': q, 'reason': 'Explore a distinct clue'}) for q in queries]
    assert sum(bool(r.get('redirected_from')) for r in results) == 2
    assert not results[-1].get('redirected_from')
    assert scout.trace.n_search == 10


def test_v234_preserves_model_and_budget_options():
    assert get_version('v2.3.4').options == {**get_version('v2.3.3').options,
        'candidate_progress_v2': True, 'max_auto_reviews': 2}
    assert get_version('v2.3.4').options['time_budget'] == 600
