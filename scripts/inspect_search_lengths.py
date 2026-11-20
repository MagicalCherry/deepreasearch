"""S15本地检索观察：从指定题的真实查询取默认top5，读取原文统计词数，不调用模型或读取标注。"""

import argparse
import asyncio
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True)
    parser.add_argument('--query-id',required=True,nargs='+')
    parser.add_argument('--search-url',default='http://localhost:8765')
    args=parser.parse_args()
    directory=Path(args.run).resolve()
    if ROOT/'runs' not in directory.parents:
        parser.error('运行目录必须位于Projects/runs')
    records={str(r['query_id']):r for line in (directory/'results.jsonl').read_text(encoding='utf-8-sig').splitlines()
             if line.strip() for r in [json.loads(line)]}
    observations=[]
    async with httpx.AsyncClient(base_url=args.search_url,timeout=120) as client:
        for key in args.query_id:
            if key not in records:
                parser.error('题号不在本次运行内')
            searches=[e for e in records[key].get('events',[]) if e.get('event')=='search' and e.get('query')]
            if not searches:
                parser.error('该题没有真实搜索，不能进行查询回放')
            query=searches[0]['query']
            response=await client.get('/search',params={'q':query,'k':5,'index':'default'})
            response.raise_for_status()
            rows=[]
            for rank,hit in enumerate(response.json()['results'],1):
                response=await client.get('/document/'+str(hit['docid']))
                response.raise_for_status()
                document=response.json()
                text=document.get('text','')
                rows.append({'rank':rank,'docid':str(hit['docid']),'title':hit.get('title',''),
                    'url':document.get('url',''),'whitespace_words':len(text.split()),
                    'characters':len(text),'opening':text[:180]})
            observations.append({'query_id':key,'actual_query':query,'index':'default','top5':rows})
    report={'_purpose':'S15默认索引top5长度观察，真实历史查询，无标注或模型调用。',
            'model_calls':0,'word_count_method':'split on whitespace','observations':observations}
    target=ROOT/'docs/S15默认索引观察.json'
    if target.exists():
        parser.error('观察报告已存在，不覆盖已有记录')
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    asyncio.run(main())
