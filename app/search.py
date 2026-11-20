"""封装本地 BM25 检索服务的搜索、文档读取和健康检查请求。"""

from typing import Any

import httpx

from app.config import settings


class SearchClient:
    """异步访问课程提供的 BM25 检索服务。"""

    def __init__(self, index: str | None = None, snippet: str | None = None) -> None:
        if snippet not in (None, 'head', 'passage'):
            raise ValueError('未知片段模式')
        self.base_url = settings.search_url.rstrip("/")
        self.index = index
        self.snippet = snippet
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)

    async def search(self, q: str, k: int = 5) -> dict[str, Any]:
        """搜索语料，返回查询信息和带标题、片段的结果。"""
        params = {"q": q, "k": k}
        if self.index is not None:
            params['index'] = self.index
        if self.snippet is not None:
            params['snippet'] = self.snippet
        response = await self.client.get("/search", params=params)
        response.raise_for_status()
        return response.json()

    async def document(
        self,
        docid: str,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """按编号读取原文；可选限制返回的 token 数。"""
        params = {}
        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        response = await self.client.get(
            f"/document/{docid}",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    async def health(self) -> dict[str, Any]:
        """查询检索服务和默认索引状态。"""
        response = await self.client.get("/health")
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        """关闭异步 HTTP 客户端。"""
        await self.client.aclose()
