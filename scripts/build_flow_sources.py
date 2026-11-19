"""把v1.0–v1.5实验提交的真实源码和AST行号嵌入流程讲解页；只读取指定代码文件，不读取环境配置。"""

import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / 'docs/visualizations/agent-evolution.html'
COMMITS = ['0fa12d1', '290fcbc', '6938ff9', '7dd9280', '15a889a', 'e6de328']
FILES = ['app/agents/s4_port.py', 'app/agents/dr/team.py', 'app/agents/dr/pipeline.py',
         'app/agents/dr/prompts.py', 'app/versions.py', 'app/s4/deep_research_v2/state.py']
FILES += ['app/s4/deep_research_v2/agents/' + name + '.py'
          for name in ['architect', 'scout', 'writer', 'critic']]


def build():
    blobs, snapshots = {}, []
    for commit in COMMITS:
        files = {}
        for path in FILES:
            result = subprocess.run(['git', 'show', f'{commit}:{path}'], cwd=ROOT,
                                    capture_output=True)
            if result.returncode:
                continue
            code = result.stdout.decode('utf-8-sig')
            key = hashlib.sha256(code.encode()).hexdigest()[:16]
            files[path] = key
            if key in blobs:
                continue
            ranges = {}
            def walk(tree, prefix=''):
                for node in ast.iter_child_nodes(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        name = prefix + node.name
                        ranges[name] = [node.lineno, node.end_lineno]
                        walk(node, name + '.')
            walk(ast.parse(code))
            blobs[key] = {'code': code, 'ranges': ranges}
        snapshots.append({'commit': commit, 'files': files})
    payload = json.dumps({'blobs': blobs, 'snapshots': snapshots}, ensure_ascii=False).replace('<', '\\u003c')
    text = PAGE.read_text(encoding='utf-8')
    start, end = '/* SOURCE_PANEL_START */', '/* SOURCE_PANEL_END */'
    panel = (ROOT / 'docs/visualizations/flow-code-panel.js').read_text(encoding='utf-8')
    content = start + '\nconst SOURCE_DATA = ' + payload + ';\n' + panel + '\n' + end
    if start in text:
        a, b = text.index(start), text.index(end) + len(end)
        text = text[:a] + content + text[b:]
    else:
        text = text.replace('versions.forEach((d,i)=>', content + '\nversions.forEach((d,i)=>', 1)
    PAGE.write_text(text, encoding='utf-8')
    print(f'Embedded {len(blobs)} unique source files across {len(snapshots)} versions.')


if __name__ == '__main__':
    build()
