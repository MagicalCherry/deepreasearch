"""S14离线对照：按两版各自证据召回分档统计正确率，不读取答案给Agent或调用模型。"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def latest(path):
    return {str(row['query_id']):row for line in path.read_text(encoding='utf-8-sig').splitlines()
            if line.strip() for row in [json.loads(line)]}


def group_records(results, judged, questions):
    """每版按自己的召回分档；只接受整份题集当前结果对应的布尔判分。"""
    if set(results) != set(questions):
        raise ValueError('运行结果与题集编号不完整匹配')
    bands = {label:{'n':0,'correct':0} for label in ('0','0<recall<50%','recall>=50%')}
    for key, question in questions.items():
        record, verdict = results[key], judged.get(key,{})
        correct = verdict.get('judge',{}).get('correct')
        if (type(correct) is not bool or verdict.get('response')!=record.get('response')
                or bool(verdict.get('error'))!=bool(record.get('error'))):
            raise ValueError('存在缺失或过期判分')
        evidence = set(map(str,question.get('evidence_docids') or []))
        recalled = set(map(str,record.get('retrieved_docids') or []))
        ratio = len(evidence & recalled)/len(evidence) if evidence else 0
        label = '0' if ratio==0 else '0<recall<50%' if ratio<.5 else 'recall>=50%'
        bands[label]['n']+=1
        bands[label]['correct']+=int(correct)
    for group in bands.values():
        group['accuracy']=round(100*group['correct']/group['n'],2) if group['n'] else None
    return bands


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--left',required=True)
    parser.add_argument('--right',required=True)
    parser.add_argument('--dataset',choices=('smoke20','dev100'),required=True)
    args=parser.parse_args()
    questions=latest(ROOT.parent/'MAS实操课程/01-项目任务书/验收题集'/f'{args.dataset}.jsonl')
    report={}
    for name in (args.left,args.right):
        directory=Path(name).resolve()
        if ROOT/'runs' not in directory.parents:
            parser.error('运行目录必须位于Projects/runs')
        config=json.loads((directory/'config.json').read_bytes())
        if config.get('dataset')!=args.dataset:
            parser.error('题集与运行配置不一致')
        report[directory.name]=group_records(latest(directory/'results.jsonl'),latest(directory/'judged.jsonl'),questions)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
