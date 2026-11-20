"""同研究代码续跑原批次：验证研究代码/依赖未变，记录文档提交差异，保留原配置身份与成功结果。"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run_id):
        parser.error('运行编号格式无效')
    directory = ROOT/'runs'/args.run_id
    config = json.loads((directory/'config.json').read_text(encoding='utf-8'))
    source_sha = config['git_sha']
    tracked = ['app', 'pyproject.toml', 'uv.lock']
    changed = subprocess.check_output(['git','diff','--name-only',source_sha,'--',*tracked],
                                      cwd=ROOT,text=True).strip()
    untracked = subprocess.check_output(['git','ls-files','--others','--exclude-standard','--',*tracked],
                                        cwd=ROOT,text=True).strip()
    if changed or untracked:
        parser.error('研究代码或依赖存在差异，禁止沿用原提交身份：'+changed+' '+untracked)
    head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()

    from app import runner
    from app.history import process_alive
    from app.versions import get_version
    status = json.loads((directory/'status.json').read_text(encoding='utf-8'))
    if status.get('status') == 'running' and process_alive(status.get('pid')):
        parser.error('原批次仍在运行，不启动第二个进程')
    defaults = get_version(config['version']).options
    overrides = {k:v for k,v in config['options'].items() if defaults.get(k) != v}
    if set(overrides) - {'time_budget'} or set(defaults) - set(config['options']):
        parser.error('原版本配置发生变化，禁止续跑')
    # 只调整快照身份；上方已核对实际研究代码，run_eval仍核对模型/索引/并发等完整配置。
    runner.git_sha = lambda: source_sha
    audit = {'purpose':'保留原运行身份的同研究代码续跑核对', 'source_git_sha':source_sha,
             'current_git_sha':head, 'research_diff':[], 'concurrency':config['concurrency'],
             'checked_at':datetime.now(timezone.utc).isoformat(),
             'note':'未修改原config或结果；仅研究代码及依赖一致时沿用原快照身份，实际当前提交单独记录。'}
    with (directory/'resume_code_checks.jsonl').open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(audit,ensure_ascii=False)+'\n')
    print(json.dumps({'run_id':args.run_id,'source_git_sha':source_sha,
                      'current_git_sha':head,'research_code_unchanged':True,
                      'concurrency':config['concurrency']},ensure_ascii=False),flush=True)
    result = asyncio.run(runner.run_eval(config['dataset'],config['version'],config['concurrency'],
                                         args.run_id,overrides or None))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit('运行已中断，可使用相同命令续跑。')
