"""在临时副本中验证前端覆盖交付的校验、幂等和未知修改保护，不启动浏览器或Docker。"""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.apply_frontend_overrides import OVERRIDES, apply_overrides, digest


def package_fixture(tmp_path):
    package, target = tmp_path / 'package', tmp_path / 'target'
    records = []
    for name in ['A.tsx', 'B.tsx']:
        relative = Path('frontend/src') / name
        for directory, text in [(package, 'new'), (target, 'old')]:
            file = directory / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(text, encoding='utf-8')
        records.append({'path': relative.as_posix(),
                        'base_sha256': hashlib.sha256(b'old').hexdigest(),
                        'sha256': hashlib.sha256(b'new').hexdigest()})
    (package / 'manifest.json').write_text(json.dumps({'files': records}), encoding='utf-8')
    return package, target


def test_apply_and_reapply_are_idempotent(tmp_path):
    package, target = package_fixture(tmp_path)
    assert apply_overrides(target, package) == 2
    assert apply_overrides(target, package) == 0
    assert (target / 'frontend/src/A.tsx').read_text() == 'new'


def test_unknown_edit_fails_before_any_write(tmp_path):
    package, target = package_fixture(tmp_path)
    (target / 'frontend/src/B.tsx').write_text('local-edit')
    with pytest.raises(ValueError, match='未知修改'):
        apply_overrides(target, package)
    assert (target / 'frontend/src/A.tsx').read_text() == 'old'


def test_corrupt_package_fails_before_any_write(tmp_path):
    package, target = package_fixture(tmp_path)
    (package / 'frontend/src/B.tsx').write_text('corrupt')
    with pytest.raises(ValueError, match='归档文件校验失败'):
        apply_overrides(target, package)
    assert (target / 'frontend/src/A.tsx').read_text() == 'old'


def test_path_escape_is_rejected(tmp_path):
    package, target = package_fixture(tmp_path)
    manifest = json.loads((package / 'manifest.json').read_text())
    manifest['files'][0]['path'] = '../outside'
    (package / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='路径无效'):
        apply_overrides(target, package)


def test_archived_files_match_manifest():
    manifest = json.loads((OVERRIDES / 'manifest.json').read_text(encoding='utf-8'))
    assert len(manifest['files']) == 2
    for item in manifest['files']:
        assert digest(OVERRIDES / item['path']) == item['sha256']


def test_text_hash_ignores_only_windows_line_endings(tmp_path):
    unix, windows = tmp_path / 'unix', tmp_path / 'windows'
    unix.write_bytes(b'first\nsecond\n')
    windows.write_bytes(b'first\r\nsecond\r\n')
    assert digest(unix) == digest(windows)
    windows.write_bytes(b'changed\r\nsecond\r\n')
    assert digest(unix) != digest(windows)


def test_real_archive_applies_to_course_copy(tmp_path):
    import shutil
    root = Path(__file__).resolve().parents[1]
    source = root.parent / 'MAS实操课程/02-前端成品'
    manifest = json.loads((OVERRIDES / 'manifest.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        destination = tmp_path / item['path']
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / item['path'], destination)
    assert apply_overrides(tmp_path) == 2
    assert apply_overrides(tmp_path) == 0
