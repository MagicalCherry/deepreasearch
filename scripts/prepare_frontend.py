"""建立课程前端的独立运行副本，隔离Docker项目并把评测代理改为8001，不复制任何凭证文件。"""

from pathlib import Path
import secrets
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.apply_frontend_overrides import apply_overrides
SOURCE = ROOT.parent / "MAS实操课程" / "02-前端成品"
TARGET = ROOT / "frontend_runtime"


def main():
    """首次复制成品并生成仅本地登录所需配置；已有副本拒绝覆盖。"""
    if TARGET.exists():
        raise SystemExit("frontend_runtime已存在，未覆盖；请使用已有运行副本。")
    shutil.copytree(SOURCE, TARGET, ignore=shutil.ignore_patterns(
        ".env", ".env.*", ".git", "node_modules", ".venv", "__pycache__", "*.pyc"))
    apply_overrides(TARGET)
    compose = TARGET / "docker-compose.yml"
    compose.write_text(compose.read_text(encoding="utf-8").replace(
        "name: deepresearch", "name: mas-s06-preview"), encoding="utf-8")
    nginx = TARGET / "frontend" / "nginx.conf"
    nginx.write_text(nginx.read_text(encoding="utf-8").replace(
        "host.docker.internal:8000", "host.docker.internal:8001"), encoding="utf-8")
    vite = TARGET / "frontend" / "vite.config.ts"
    vite.write_text(vite.read_text(encoding="utf-8").replace(
        "http://localhost:8000", "http://localhost:8001"), encoding="utf-8")
    # 不注入任何模型凭证。随机本地JWT只写入被Git忽略的运行目录，不输出。
    (TARGET / ".env").write_text(
        "# 前端演示副本本地登录配置；不含云模型凭证。\n"
        f"JWT_SECRET_KEY={secrets.token_urlsafe(48)}\n"
        "DASHSCOPE_API_KEY=\nWEB_PORT=5183\nBACKEND_PORT=8020\nDEMO_ACCOUNT=on\n",
        encoding="utf-8")
    print("已创建frontend_runtime；Compose项目mas-s06-preview；评测代理8001；未配置模型Key。")


if __name__ == "__main__":
    main()
