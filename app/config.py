"""读取本地环境配置，提供百炼模型、检索服务和 tokenizer 缓存设置。"""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COURSE_ROOT = PROJECT_ROOT.parent
ENV_FILE = PROJECT_ROOT / ".env"

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


settings = Settings(
    api_key=os.getenv("DASHSCOPE_API_KEY", ""),
    base_url=os.getenv(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    model=os.getenv("LLM_MODEL", "qwen3.8-flash"),
    max_tokens=131072,#qwen3.8-flash 最大输出长度
    search_url=os.getenv("SEARCH_URL", "http://localhost:8765").rstrip("/"),
)