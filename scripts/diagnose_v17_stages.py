"""只读诊断v1.7规划、检索、阅读、事实、写作及审核交接；标注仅用于离线命中计数，不调用服务。"""

from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.answer import parse
from app.agents.dr.team import clean_query
from app.agents.dr.react_scout import parse_scout_report


def latest(path):
    return {str(r['query_id']): r for line in path.read_text(encoding='utf-8-sig').splitlines()
            if line.strip() for r in [json.loads(line)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='runs/s13-v17-qwen37-dev100-reuse20')
    parser.add_argument('--output', default='docs/v1.7阶段排查.json')
    args = parser.parse_args()
    run, output = Path(args.run).resolve(), Path(args.output).resolve()
    if ROOT / 'runs' not in run.parents or ROOT / 'docs' not in output.parents:
        parser.error('运行必须位于runs、报告必须位于docs')
    paths = [run / name for name in ('results.jsonl', 'judged.jsonl', 'summary.json', 'config.json')]
    digests = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    results, judged = latest(paths[0]), latest(paths[1])
    questions = latest(ROOT.parent / 'MAS实操课程/01-项目任务书/验收题集/dev100.jsonl')
    cases = []
    generic = 'Missing, ambiguous, or unsupported source check.'
    for key, result in results.items():
        assert judged[key]['response'] == result['response']
        events = result['events']
        plans = [e for e in events if e['event'] == 'plan' and e['agent'] == 'planner']
        plan = plans[0] if plans else {}
        sections = plan.get('subquestions', [])
        seeds = [q for s in sections for q in s.get('search_queries', [])]
        searches = [e for e in events if e['event'] == 'search']
        reads = {str(e['docid']) for e in events if e['event'] == 'read'}
        facts = [e for e in events if e['event'] == 'fact']
        fact_ids = {str(e.get('docid')) for e in facts}
        evidence = set(map(str, questions[key].get('evidence_docids', [])))
        got = set(map(str, result.get('retrieved_docids', [])))
        reviews = [e for e in events if e['event'] == 'stage_output' and e.get('kind') == 'review']
        scout_reports = [e for e in events if e['event'] == 'stage_output' and e.get('kind') == 'scout_report']
        parsed_reports = [parse_scout_report(e.get('content','')) for e in scout_reports]
        checks = reviews[-1]['review'].get('constraint_checks', []) if reviews else []
        writer = [str(e['items'][0]) for e in events if e['event'] == 'plan'
                  and e['agent'] == 'writer' and e.get('items')]
        reports = [i for i,e in enumerate(events) if e['event'] == 'stage_output' and e.get('kind') == 'report']
        review_indices = [i for i,e in enumerate(events) if e['event'] == 'stage_output' and e.get('kind') == 'review']
        supplements = []
        for i,e in enumerate(events):
            if e['event'] != 'agent_start' or e['agent'] != 'scout' or e.get('role') != '补充检索':
                continue
            end = next((j for j in range(i+1,len(events)) if events[j]['event']=='agent_start'
                        and events[j]['agent'] in {'writer','critic','answer'}),len(events))
            segment = events[i+1:end]
            supplements.append({k:sum(x['event']==k for x in segment) for k in ('search','read','fact')})
        cases.append({'query_id':key,'correct':judged[key]['judge']['correct'],
            'constraints':len(plan.get('constraints',[])), 'seed_queries':len(seeds),
            'invalid_seed_queries':sum(not clean_query(q) for q in seeds),
            'searches':len(searches), 'chinese_searches':sum(any('\u4e00'<=c<='\u9fff' for c in e['query']) for e in searches),
            'reads':len(reads), 'facts':len(facts), 'evidence_total':len(evidence),
            'evidence_retrieved':len(got & evidence), 'evidence_read':len(reads & evidence),
            'evidence_fact_sources':len(fact_ids & evidence),
            'all_evidence_retrieved':bool(evidence) and evidence <= got,
            'writer_candidates':writer,'report_count':len(reports),'review_count':len(reviews),
            'last_report_reviewed':bool(reports and review_indices and review_indices[-1]>reports[-1]),
            'checks':len(checks),'verified':sum(c['status']=='verified' for c in checks),
            'normalized_generic_checks':sum(c.get('note')==generic for c in checks),
            'review_has_substantive_note':any(c.get('note')!=generic for c in checks),
            'supplements':supplements,'stop_reason':result.get('stop_reason'),
            'planner_restarts':sum(e['event']=='agent_start' and e['agent']=='planner' for e in events)-1,
            'stage_retry_events':sum(e['event']=='stage_output' and e.get('kind')=='stage_error' for e in events)})
        cases[-1].update(scout_reports=len(scout_reports),
            zero_tool_reports=sum(e.get('tool_calls')==0 for e in scout_reports),
            reports_without_cited_findings=sum(not p['facts'] for p in parsed_reports),
            report_facts_with_unseen_docid=sum(f['docid'] not in set(map(str,e.get('observed_docids',[])))
                for e,p in zip(scout_reports,parsed_reports) for f in p['facts']))
    def aggregate(rows):
        return {'n':len(rows),'no_facts':sum(c['facts']==0 for c in rows),
            'no_read':sum(c['reads']==0 for c in rows),'zero_evidence_retrieved':sum(c['evidence_retrieved']==0 for c in rows),
            'retrieved_evidence_but_read_none':sum(c['evidence_retrieved']>0 and c['evidence_read']==0 for c in rows),
            'has_evidence_fact_source':sum(c['evidence_fact_sources']>0 for c in rows),
            'all_evidence_retrieved':sum(c['all_evidence_retrieved'] for c in rows),
            'no_verified_constraints':sum(c['verified']==0 for c in rows),
            'generic_normalized_checks':sum(c['normalized_generic_checks'] for c in rows),
            'total_checks':sum(c['checks'] for c in rows),
            'all_checks_generic':sum(c['checks']>0 and c['normalized_generic_checks']==c['checks'] for c in rows),
            'questions_with_invalid_seed':sum(c['invalid_seed_queries']>0 for c in rows),
            'chinese_searches':sum(c['chinese_searches'] for c in rows),
            'unreviewed_final_report':sum(not c['last_report_reviewed'] for c in rows),
            'planner_restarts':sum(c['planner_restarts'] for c in rows),
            'scout_reports':sum(c['scout_reports'] for c in rows),
            'zero_tool_reports':sum(c['zero_tool_reports'] for c in rows),
            'reports_without_cited_findings':sum(c['reports_without_cited_findings'] for c in rows),
            'report_facts_with_unseen_docid':sum(c['report_facts_with_unseen_docid'] for c in rows),
            'stop_reasons':dict(Counter(c['stop_reason'] for c in rows))}
    report = {'_purpose':'阶段交接离线诊断，只输出证据命中数量，不输出标准答案或金标编号。',
        'run':run.name,'source_sha256':digests,'all':aggregate(cases),
        'wrong':aggregate([c for c in cases if not c['correct']]),
        'correct':aggregate([c for c in cases if c['correct']]),'cases':cases}
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==digests[p.name] for p in paths)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False,indent=2))
    print('Selected cases:',json.dumps([c for c in cases if c['query_id'] in {'93','331','422','934','972','883','356','1177','590'}],ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
