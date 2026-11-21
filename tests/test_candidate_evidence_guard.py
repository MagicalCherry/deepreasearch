"""v2.3.5虚构证据验证逐字引文与独立候选查询隔离，不使用题集答案。"""

from copy import deepcopy

import pytest

from app.agents.dr.evidence_guard import guard_progress, isolate_queries
from app.versions import get_version


def claim(quote=None):
    check = {'constraint': 'Represented a country in a sporting competition',
             'status': 'supported', 'docids': ['12'], 'note': 'An award was mentioned'}
    if quote is not None:
        check['quote'] = quote
    return [{'name': 'Fictional Person', 'checked': [check], 'pending': ['C2']}]


@pytest.mark.parametrize('quote', [None, 'Invented sporting participation sentence.'])
def test_unsupported_quote_cannot_become_supported_progress(quote):
    original = claim(quote)
    output, audit = guard_progress(original, {'12': 'Fictional Person received a chemistry prize.'})
    assert output[0]['checked'][0]['status'] == 'unresolved'
    assert audit[0]['reason'] in {'missing_quote', 'quote_not_observed'}
    assert original == claim(quote)


def test_observed_quote_is_retained_without_claiming_semantic_verification():
    quote = 'Fictional Person competed in a sporting event.'
    output, audit = guard_progress(claim(quote), {'12': quote})
    assert output[0]['checked'][0]['quote'] == quote
    assert output[0]['checked'][0]['evidence_check'] == 'quote_observed_semantics_pending'
    assert audit == []


def test_independent_candidates_are_split_into_single_candidate_queries():
    candidates = [{'name': 'Ada Example', 'next_query': 'Ada Example institution history'},
                  {'name': 'Bert Sample', 'next_query': 'Bert Sample publication abstract'}]
    output, audit = isolate_queries(['Did Ada Example and Bert Sample collaborate?'], candidates)
    assert output == ['Ada Example institution history', 'Bert Sample publication abstract']
    assert audit[0]['reason'] == 'independent_candidates_combined'


def test_explicitly_observed_candidate_relationship_can_be_investigated():
    candidates = [{'name': 'Ada Example'}, {'name': 'Bert Sample'}]
    query = 'Ada Example Bert Sample publication'
    relationships = [{'names': ['Ada Example', 'Bert Sample'],
                      'quote': 'Ada Example and Bert Sample coauthored the fictional study.', 'docids': ['12']}]
    assert isolate_queries([query], candidates, relationships)[0] == [query]


def test_single_candidate_queries_are_unchanged():
    assert isolate_queries(['Ada Example publication'], [{'name': 'Ada Example'}]) == (['Ada Example publication'], [])


def test_v235_adds_only_evidence_guard():
    assert get_version('v2.3.5').options == {**get_version('v2.3.4').options, 'candidate_evidence_guard': True}
