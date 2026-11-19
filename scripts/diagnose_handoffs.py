"""离线检查未作答题的事实交接、整题重试、空搜索轮次和末次审核；不读取标准答案或调用服务。"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.answer import parse
from diagnose import NONANSWER


def inspect(records):
    """以最终记录为准；事件含该次运行内部重试，按planner开始事件切分尝试。"""
    counts = Counter()
    cases = []
    for key, record in records.items():
        exact = parse(record.get('response', ''))['exact_answer']
        if record.get('error') or (exact and not NONANSWER.search(exact)):
            continue
        counts['nonanswers'] += 1
        events = record.get('events', [])
        starts = [i for i, e in enumerate(events)
                  if e['event'] == 'agent_start' and e['agent'] == 'planner']
        final_events = events[starts[-1]:] if starts else events
        facts = [e for e in events if e['event'] == 'fact']
        final_facts = [e for e in final_events if e['event'] == 'fact']
        counts['no_facts_any_attempt'] += not facts
        counts['no_facts_final_attempt'] += not final_facts
        counts['has_facts_final_attempt'] += bool(final_facts)
        counts['restarted'] += len(starts) > 1
        counts['facts_lost_on_retry'] += bool(facts) and not final_facts
        counts['no_read'] += record.get('n_read', 0) == 0
        reports = [e for e in events if e['event'] == 'stage_output' and e.get('kind') == 'report']
        counts['missing_report'] += not reports or not reports[-1].get('content')
        answers = [str(e['items'][0]) for e in events
                   if e['event'] == 'plan' and e['agent'] == 'writer' and e.get('items')]
        counts['first_writer_nonanswer'] += bool(answers) and bool(NONANSWER.search(answers[0]))
        counts['last_writer_nonanswer'] += bool(answers) and bool(NONANSWER.search(answers[-1]))
        counts['writer_had_specific_candidate'] += any(not NONANSWER.search(a) for a in answers)
        search_counts = Counter()
        later_empty = False
        for e in events:
            if e['event'] == 'search':
                search_counts[e['agent']] += 1
            if e['event'] == 'plan' and e['agent'].startswith('scout'):
                counts['scout_rounds'] += 1
                if search_counts[e['agent']] == 0:
                    counts['rounds_without_actual_search'] += 1
                    if e.get('round', 0) > 1:
                        counts['later_rounds_without_actual_search'] += 1
                        later_empty = True
                search_counts[e['agent']] = 0
        counts['questions_with_later_empty_round'] += later_empty
        last_review = max((i for i, e in enumerate(final_events)
                           if e['event'] == 'stage_output' and e.get('kind') == 'review'), default=-1)
        last_report = max((i for i, e in enumerate(final_events)
                           if e['event'] == 'stage_output' and e.get('kind') == 'report'), default=-1)
        counts['last_report_without_subsequent_review'] += last_report > last_review >= 0
        for i, e in enumerate(events):
            if e['event'] != 'agent_start' or e['agent'] != 'scout' or e.get('role') != '补充检索':
                continue
            end = next((j for j in range(i + 1, len(events))
                        if events[j]['event'] == 'agent_start' and events[j]['agent'] == 'writer'), len(events))
            counts['supplementary_calls'] += 1
            counts['supplementary_without_search_read_fact'] += not any(
                x['event'] in ('search', 'read', 'fact') for x in events[i + 1:end])
        attempts = []
        if bool(facts) and not final_facts:
            for n, start in enumerate(starts):
                segment = events[start:starts[n + 1] if n + 1 < len(starts) else len(events)]
                attempts.append({'attempt': n + 1,
                    **{name: sum(e['event'] == name for e in segment) for name in ('search', 'read', 'fact')},
                    'writer_candidates': [str(e['items'][0]) for e in segment
                        if e['event'] == 'plan' and e['agent'] == 'writer' and e.get('items')]})
        cases.append({'query_id': key, 'last_attempt_facts': len(final_facts),
                      'writer_candidates': answers, 'lost_fact_attempts': attempts})
    return dict(counts), cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--md', required=True)
    args = parser.parse_args()
    directory, output = Path(args.run).resolve(), Path(args.md).resolve()
    if (ROOT / 'runs').resolve() not in directory.parents:
        parser.error('运行必须位于本项目runs目录')
    if (ROOT / 'docs').resolve() not in output.parents or output.suffix != '.md':
        parser.error('报告必须位于本项目docs目录且为.md文件')
    if output.exists():
        parser.error('报告已存在，请使用新文件名，避免覆盖人工复盘')
    source = directory / 'results.jsonl'
    raw = source.read_bytes()
    records = {}
    for line in raw.splitlines():
        if line.strip():
            record = json.loads(line)
            records[str(record['query_id'])] = record
    counts, cases = inspect(records)
    digest = hashlib.sha256(raw).hexdigest()
    lines = ['<!-- 用途：未作答题的只读流程诊断；不读取标准答案，不调用模型，不修改原始评测。 -->',
             '# v1.6 未作答流程排查', '', f'运行：`{directory.name}`。',
             f'原始results.jsonl SHA256：`{digest}`。', '',
             '## 统计口径', '',
             '只分析最后记录中的未给具体答案题（NONANSWER规则，与原诊断相同）。',
             '事件包含整题内部重试；最后尝试按最后一个planner开始事件切分。次数统计不代表独立题数。',
             '“无实际搜索轮次”指该侦探上次plan之后没有search事件；后续轮次排除第1轮，避免混淆初始查询修复。',
             '不凭Unknown推断应当猜答案，不把真实来源编号等同于事实正确。', '',
             '## 可复算统计', '', '```json', json.dumps(counts, ensure_ascii=False, indent=2), '```', '',
             '## 已证实的流程问题', '',
             '1. 重试状态不一致：pipeline.py中每次_run_once创建新state/事实库；team.py把预算、已搜查询、已读文档保存在同一个Trace上。旧事实丢失，恢复检索又被旧预算/去重阻止。',
             '2. 空结果反复分析：loop_section每轮初始化results=[]，_execute_search对重复/近似查询返回[]；之后仍调用模型，未携带跳过原因。新查询与旧查询碰撞时，循环继续消耗分析调用。',
             '3. 无新增材料仍补搜/重写：事件可见补搜阶段没有search/read/fact，之后仍重写；当前循环没有以“证据未变化”中止回环。',
             '4. 最后一稿未审核：Critic增加iteration后仍执行Writer；下一次while条件已不满足，直接抽取最后稿。不能把该稿当作Critic已批准。', '',
             '## 重试丢失事实的具体记录', '']
    for case in cases:
        if case['lost_fact_attempts']:
            lines += [f"### 第{case['query_id']}题", '', '```json',
                      json.dumps(case['lost_fact_attempts'], ensure_ascii=False, indent=2), '```', '']
    lines += ['## 判断边界', '',
              '65题第一次Writer就未给具体答案；末次Writer为未作答的有68题。多数Unknown并非最终答案抽取才产生。',
              '35题最后尝试仍有事实，却不足以据此证明事实已覆盖关键约束；需区分相关性不足、候选未核实、缺少直接答案等情况。',
              'Scout原始JSON未完整保存，无法回溯多少new_facts因缺字段/无效docid被过滤；内部重试异常也未逐次保存，不能断言具体是哪次解析错误。',
              '第93题第一尝试的Writer候选为AdenoPlus，第二尝试丢失25条事实后变为Unknown；这是证据丢失的直接案例。', '',
              '## 建议的修复顺序（尚未实施）', '',
              '1. 对可恢复的角色错误在角色内有限重试，保留工作状态；整题重试时一致恢复事实、来源和预算，不能仅清空事实。',
              '2. 给无效/重复/预算耗尽返回明确原因；没有新结果时不反复按有结果进行分析，保留可执行的新方向并设置停滞退出。',
              '3. 只有证据变化才执行补搜后的重写；轮数达到上限时返回最后审核稿和未解决问题，避免产生未审核的新稿。',
              '4. 增加角色异常、字段过滤数量和停止原因记录，再判断模型分析质量；证据不足仍允许Unknown并要求低置信。', '',
              '本轮仅排查，未修改Agent逻辑，未重跑评测。原始运行保持不变。', '',
              '## tutor门槛核实', '',
              'S12提交返回partial，missing为dev100 ≥ 25%。12%的原始结果已经提交，无需反复粘贴。',
              'get_hint对“门槛是否硬验收及获授权改用Qwen3.7”的询问返回matched=false及通用排错提示，未澄清门槛。保持S12未通过，不为挑分重复收费运行。', '']
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise ValueError('读取期间结果文件改变，拒绝生成不一致报告')
    output.write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    print('Saved:', output)
    print('Source results unchanged; no model or search requests.')


if __name__ == '__main__':
    main()
