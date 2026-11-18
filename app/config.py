"""按平台读取独立本地配置，提供模型、检索服务和tokenizer缓存设置，不输出密钥。"""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COURSE_ROOT = PROJECT_ROOT.parent
PROVIDER = os.getenv("LLM_PROVIDER", "dashscope").strip().lower()
if PROVIDER not in {"dashscope", "openrouter"}:
    raise ValueError("LLM_PROVIDER仅支持dashscope或openrouter")
ENV_FILE = PROJECT_ROOT / (".env.openrouter" if PROVIDER == "openrouter" else ".env")

# 模型 tokenizer 文件使用课程提供的本地副本，避免运行时联网下载。
TIKTOKEN_CACHE_DIR = (
    COURSE_ROOT / "MAS实操课程" / "03-检索服务" / "tiktoken"
)
os.environ["TIKTOKEN_CACHE_DIR"] = str(TIKTOKEN_CACHE_DIR)

load_dotenv(ENV_FILE)


@dataclass(frozen=True)
class Settings:
    """保存应用运行所需的模型与检索服务配置。"""

    api_key: str
    base_url: str
    model: str
    max_tokens: int
    search_url: str
    provider: str = "dashscope"


settings = Settings(
    api_key=os.getenv("OPENROUTER_API_KEY" if PROVIDER == "openrouter" else "DASHSCOPE_API_KEY", ""),
    base_url=os.getenv(
        "OPENROUTER_BASE_URL" if PROVIDER == "openrouter" else "DASHSCOPE_BASE_URL",
        "https://openrouter.ai/api/v1" if PROVIDER == "openrouter"
        else "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    model=os.getenv("OPENROUTER_MODEL", "qwen/qwen3.8-flash") if PROVIDER == "openrouter"
        else os.getenv("LLM_MODEL", "qwen3.8-flash"),
    max_tokens=131072,#qwen3.8-flash 最大输出长度
    search_url=os.getenv("SEARCH_URL", "http://localhost:8765").rstrip("/"),
    provider=PROVIDER,
)
