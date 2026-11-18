"""S09离线评测诊断：读取已有判分与题集标注，分类错题、统计证据命中并生成Markdown人工复盘卡；不调用模型。"""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.answer import parse

CATEGORIES = ('运行出错', '格式', '零召回', '召回到没推对')
NONANSWER = re.compile(
    r'无法确定|不能确定|无法回答|无法计算|无法提供|不能识别|无法识别|'
    r'\bunknown\b|\bnot found\b|\bunable to\b|\bcannot (?:be |definitively )?'
    r'(?:determine|identify|calculate|provide)|\bno matching\b|\binsufficient\b',
    re.IGNORECASE,
)


def read_latest(path):
    """只读JSONL，同题多次尝试使用最后记录，不修复或修改源文件。"""
    records = {}
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            key = str(item['query_id'])
        except (ValueError, KeyError) as exc:
            raise ValueError(f'{path.name} 第{number}行无效') from exc
        records[key] = item
    return records


def cell(value):
    """转义表格分隔符、换行和HTML，保留完整答案文字。"""
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('|', '&#124;').replace('\r', '').replace('\n', '<br>')


def diagnose(run, dataset, output):
    """标注只用于离线集合交集，不把标准答案或证据编号写入Agent输入。"""
    directory = Path(run).resolve()
    if ROOT / 'runs' not in directory.parents:
        raise ValueError('运行目录必须位于Projects/runs内')
    if dataset not in ('smoke20', 'dev100'):
        raise ValueError('本阶段只支持内置smoke20或dev100')
    target = Path(output).resolve()
    if ROOT / 'docs' not in target.parents or target.suffix.lower() != '.md':
        raise ValueError('诊断文档必须位于Projects/docs下且为.md文件')
    if target.exists():
        raise ValueError('文档已存在，为保护人工复盘内容，请使用新的--md文件名')
    config = json.loads((directory / 'config.json').read_bytes())
    if config['dataset'] != dataset:
        raise ValueError('题集与运行配置不一致')
    data_path = ROOT.parent / 'MAS实操课程' / '01-项目任务书' / '验收题集' / f'{dataset}.jsonl'
    questions = read_latest(data_path)
    results = read_latest(directory / 'results.jsonl')
    judged = read_latest(directory / 'judged.jsonl')
    if set(results) - set(questions):
        raise ValueError('结果中包含题集以外的编号')
    cards = []
    correct = 0
    for key, result in results.items():
        question = questions[key]
        answer = parse(result.get('response') or '')['exact_answer']
        if result.get('error'):
            category = '运行出错'
        else:
            verdict = judged.get(key, {})
            if (verdict.get('response') != result.get('response') or verdict.get('error')
                    or not isinstance(verdict.get('judge', {}).get('correct'), bool)):
                raise ValueError(f'题号{key}缺少与当前答案一致的有效判分，请先完成判分')
            if verdict['judge']['correct']:
                correct += 1
                continue
            category = '格式' if not answer or NONANSWER.search(answer) else None
        retrieved = set(map(str, result.get('retrieved_docids', [])))
        evidence = set(map(str, question.get('evidence_docids') or []))
        gold = set(map(str, question.get('gold_docids') or []))
        if not category:
            category = '零召回' if not retrieved.intersection(evidence) else '召回到没推对'
        cards.append({'id': key, 'category': category, 'answer': answer,
                      'evidence': f'{len(retrieved & evidence)}/{len(evidence)}',
                      'gold': f'{len(retrieved & gold)}/{len(gold)}',
                      'search': result.get('n_search', 0), 'read': result.get('n_read', 0)})
    counts = Counter(card['category'] for card in cards)
    total = (f'总数：题集{len(questions)}题，已有结果{len(results)}题，正确{correct}题，'
             f'错误或运行出错{len(cards)}题，缺失{len(questions)-len(results)}题；'
             + '，'.join(f'{name}{counts[name]}题' for name in CATEGORIES) + '。')
    lines = ['<!-- 用途：S09离线错题分类、证据命中统计与学员人工复盘；仅供评测分析。 -->',
             total, '', '# v1.0失败诊断', '', f'运行：`{directory.name}`；题集：`{dataset}`。',
             '', '分类优先级：运行出错 → 格式/未给具体答案 → 零召回 → 召回到没推对。',
             '“格式”按教案包含无法确定类回答，不仅指字段语法错误；证据命中只表示检索返回过，不代表阅读全文或验证完成。',
             '本次为smoke20探索诊断，不代替dev100正式验收。未输出标准答案或金标编号。', '']
    for name in CATEGORIES:
        lines += [f'## {name}（{counts[name]}题）', '',
                  '| 题号 | 给出的答案 | 证据命中 | 金标命中 | 搜索次数 | 阅读次数 |',
                  '|---|---|---|---|---|---|']
        for c in cards:
            if c['category'] == name:
                lines.append('| ' + ' | '.join(cell(c[k]) for k in ('id', 'answer', 'evidence', 'gold', 'search', 'read')) + ' |')
        lines.append('')
    lines += ['## 学员人工复盘（待完成）', '', '每类选2题，在前端历史运行中查看已有过程；不要重新开始研究。', '']
    for name in ('格式', '零召回', '召回到没推对'):
        chosen = [c for c in cards if c['category'] == name][:2]
        lines += [f'### {name}', '']
        for c in chosen:
            lines.append(f'- 题号 {c["id"]}：卡在哪一步：**待学员填写**。过程依据：**待填写**。')
        if len(chosen) < 2:
            lines.append(f'- 本类只有{len(chosen)}题，不补造案例；需向tutor如实说明样本不足。')
        lines.append('')
    target.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(total)
    print(f'已保存：{target}')
    print('仅离线读取已有结果；未调用模型，未修改原始运行。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--md', required=True)
    args = parser.parse_args()
    diagnose(args.run, args.dataset, args.md)
