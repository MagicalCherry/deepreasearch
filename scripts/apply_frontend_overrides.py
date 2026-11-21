"""把已归档的评测页面覆盖到独立前端副本；先校验所有文件，拒绝覆盖未知修改。"""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / 'assets' / 'frontend-overrides'


def digest(path):
    """页面文本哈希统一换行，兼容Git在Windows检出时的CRLF转换。"""
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def apply_overrides(target, package=OVERRIDES):
    """只允许manifest中的frontend/src文件；全部预检通过后写入，已应用时幂等。"""
    target, package = Path(target).resolve(), Path(package).resolve()
    manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8'))
    pending = []
    seen = set()
    for item in manifest['files']:
        relative = Path(item['path'])
        if (relative.is_absolute() or '..' in relative.parts
                or relative.parts[:2] != ('frontend', 'src') or relative in seen):
            raise ValueError('前端覆盖路径无效或重复')
        seen.add(relative)
        source, destination = (package / relative).resolve(), (target / relative).resolve()
        if not source.is_relative_to(package) or not destination.is_relative_to(target):
            raise ValueError('前端覆盖路径超出目录')
        if digest(source) != item['sha256']:
            raise ValueError(f'归档文件校验失败：{relative}')
        actual = digest(destination)
        if actual not in {item['base_sha256'], item['sha256']}:
            raise ValueError(f'目标有未知修改，未写入任何文件：{relative}')
        if actual != item['sha256']:
            pending.append((source, destination))
    for source, destination in pending:
        destination.write_bytes(source.read_bytes())
    return len(pending)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=ROOT / 'frontend_runtime')
    args = parser.parse_args()
    print(f'已应用{apply_overrides(args.target)}个前端页面文件；已匹配文件保持不变。')


if __name__ == '__main__':
    main()
