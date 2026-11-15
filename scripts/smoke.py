"""验证百炼模型、BM25 检索、文档读取与 token 用量统计是否连通。"""

import asyncio
import sys
from pathlib import Path

import tiktoken

# 直接运行 scripts/smoke.py 时，将 Projects 根目录加入模块搜索路径。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.llm import LLM
from app.search import SearchClient


async def main() -> None:
    """依次检查模型调用、检索健康状态、搜索结果和文档读取。"""
    llm = LLM()
    search = SearchClient()

    try:
        response = await llm.chat(
            [{"role": "user", "content": "请只回复：连接成功"}]
        )
        print(f"模型回复：{response.choices[0].message.content}")
        print(
            "Token 用量："
            f"prompt={llm.prompt_tokens}, "
            f"completion={llm.completion_tokens}"
        )

        health = await search.health()
        print(f"检索服务健康状态：{health}")

        result = await search.search(
            "volleyball naturalized Olympics block",
            k=3,
        )
        print("搜索结果：")
        for item in result.get("results", []):
            print(
                f"- docid={item['docid']}, "
                f"score={item['score']}, "
                f"title={item['title']}, "
                f"url={item['url']}"
            )
            print(f"  snippet={item['snippet'][:160]!r}")

        first = result["results"][0]
        document = await search.document(first["docid"])
        encoding = tiktoken.get_encoding("cl100k_base")
        first_60_tokens = encoding.decode(
            encoding.encode(document["text"])[:60]
        )
        print(
            f"文档原文前 60 个 token "
            f"(docid={document['docid']}, title={document['title']})："
        )
        print(first_60_tokens)
    finally:
        await llm.close()
        await search.close()


if __name__ == "__main__":
    asyncio.run(main())