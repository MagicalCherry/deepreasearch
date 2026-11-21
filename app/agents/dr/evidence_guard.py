"""v2.3.5候选原文校验与独立候选查询隔离；不把字符串命中当语义正确。"""

from copy import deepcopy
import re


EVIDENCE_PROMPT = '''
For each supported/refuted candidate check include quote: a verbatim passage from observed source
text supporting THAT exact condition about THAT candidate, not merely mentioning a related topic.
Distinguish participation from winning, awards from competitions, affiliation from coauthorship,
and independent research from collaboration. A valid document ID alone proves none of these.
If the passage does not entail the condition, mark unresolved. Preserve original question wording.
Never join two alternative candidates as coauthors/collaborators without explicit source evidence.
Only when the quote explicitly establishes a relationship, include related_candidates: [full names].
Otherwise check each candidate independently. Candidate progress remains hypotheses for the Critic.
'''


CRITIC_EVIDENCE_PROMPT = '''
Audit semantic entailment, not document-ID existence: the passage must establish the exact
condition for the correct subject. Explain any mismatch between the passage and the assertion.
Do not substitute an award for sporting participation, topic overlap for a relationship, or
separate candidate identities for two coauthors. Partial candidates are alternatives unless
an observed quote explicitly establishes a relationship. Search each alternative separately.
The appended candidate progress is a fallible investigation log, never independent evidence.
'''


def normalized(value):
    return ' '.join(str(value).casefold().split())


def guard_progress(updates, observed_text):
    """仅验证引文来自已见文本；不通过时降级并记原因，语义仍需Critic审查。"""
    output, audit = deepcopy(updates), []
    for candidate in output:
        if not isinstance(candidate, dict):
            continue
        checks = candidate.get('checked', [])
        for check in checks if isinstance(checks, list) else []:
            if not isinstance(check, dict) or check.get('status') not in {'supported', 'refuted'}:
                continue
            quote = check.get('quote')
            ids = check.get('docids', [])
            matched = [str(d) for d in ids if str(d) in observed_text
                       and isinstance(quote, str) and len(quote.strip()) >= 12
                       and normalized(quote) in normalized(observed_text[str(d)])] if isinstance(ids, list) else []
            if not matched:
                reason = 'missing_quote' if not isinstance(quote, str) or len(quote.strip()) < 12 else 'quote_not_observed'
                audit.append({'name': candidate.get('name'), 'constraint': check.get('constraint'), 'reason': reason})
                check.update(status='unresolved', docids=[], evidence_check=reason)
            else:
                check.update(docids=matched, evidence_check='quote_observed_semantics_pending')
    return output, audit


def mentioned_names(query, candidates):
    value = normalized(query)
    return list(dict.fromkeys(c['name'] for c in candidates if isinstance(c, dict)
                             and isinstance(c.get('name'), str) and c['name'].strip()
                             and re.search(r'(?<!\w)' + re.escape(normalized(c['name'])) + r'(?!\w)', value)))


def validated_relationships(progress):
    """关系声明须附已观察引文，且原文明确包含双方姓名和关系词；仍非语义证明。"""
    output = []
    for candidate in progress:
        for check in candidate.get('checked', []):
            names = check.get('related_candidates')
            quote = check.get('quote', '')
            if (check.get('evidence_check') != 'quote_observed_semantics_pending'
                    or check.get('status') != 'supported' or not isinstance(names, list)
                    or len(names) < 2 or not all(isinstance(n, str) and n.strip() for n in names)):
                continue
            text = normalized(quote)
            if (all(normalized(n) in text for n in names)
                    and re.search(r'co.?author|collaborat|jointly|合作|合著', text)
                    and not re.search(r'\bnot\b|\bnever\b|independen|并未|没有', text)):
                output.append({'names': names, 'quote': quote, 'docids': check.get('docids', [])})
    return output


def isolate_queries(queries, candidates, relationships=()):
    """多候选混搜无已核对关系时拆为各自下一查询；无安全替代则不执行该组合。"""
    output, audit = [], []
    for query in queries:
        if not isinstance(query, str):
            continue
        names = mentioned_names(query, candidates)
        linked = any(set(map(normalized, names)) <= set(map(normalized, r.get('names', [])))
                     for r in relationships) if len(names) > 1 else True
        if linked:
            output.append(query)
            continue
        audit.append({'query': query, 'names': names, 'reason': 'independent_candidates_combined'})
        for candidate in candidates:
            next_query = candidate.get('next_query') if isinstance(candidate, dict) else None
            if (candidate.get('name') in names and isinstance(next_query, str)
                    and mentioned_names(next_query, candidates) == [candidate['name']]):
                output.append(next_query)
    return list(dict.fromkeys(output)), audit
