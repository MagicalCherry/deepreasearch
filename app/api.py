"""提供评测后端的健康检查、版本列表与研究 SSE；负责事件推送和断开时取消研究任务。"""

import asyncio
import json
import logging
from time import monotonic

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.llm import LLM
from app.runner import research
from app.search import SearchClient
from app.trace import Trace
from app.versions import get_version, list_versions


logger = logging.getLogger("uvicorn.error")
app = FastAPI(title="MAS 评测后端")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5183", "http://127.0.0.1:5183"],
    allow_methods=["*"], allow_headers=["*"],
)
_llm_health: tuple[float, bool] | None = None
_llm_health_lock = asyncio.Lock()


class ResearchRequest(BaseModel):
    """研究只接收题面、版本和可选编号，不接收标准答案或证据标签。"""

    question: str = Field(min_length=1)
    version: str
    query_id: str | None = None


async def check_search() -> bool:
    """实际探测检索服务，连不上或索引未就绪均报告不可用。"""
    client = SearchClient()
    try:
        async with asyncio.timeout(5):
            result = await client.health()
        return result.get("status") == "ok"
    except Exception:
        return False
    finally:
        await client.close()


async def check_llm() -> bool:
    """用最多一个输出 token 探测当前平台；成功与失败都缓存 60 秒。"""
    global _llm_health
    async with _llm_health_lock:
        if _llm_health is not None and monotonic() - _llm_health[0] < 60:
            return _llm_health[1]
        client = None
        try:
            async with asyncio.timeout(10):
                client = LLM()
                await client.chat([{"role": "user", "content": "Reply OK"}], max_tokens=1)
            ok = True
        except Exception:
            ok = False
        finally:
            if client is not None:
                await client.close()
        _llm_health = (monotonic(), ok)
        return ok


@app.get("/api/health")
async def health():
    """分别报告后端、检索服务和当前模型平台的实际可用性。"""
    search_ok, llm_ok = await asyncio.gather(check_search(), check_llm())
    return {"status": "ok", "search": "ok" if search_ok else "down",
            "llm": "ok" if llm_ok else "down"}


@app.get("/api/versions")
async def versions():
    """返回已注册的真实版本，不添加占位版本。"""
    return list_versions()


@app.post("/api/research")
async def start_research(body: ResearchRequest, request: Request):
    """通过独立任务执行研究，通过订阅队列流式推送事件。"""
    try:
        get_version(body.version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="题面不能为空")

    async def stream():
        trace = Trace()
        queue = trace.subscribe()
        task = asyncio.create_task(research(body.question, body.version, trace))
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1)
                except TimeoutError:
                    if task.done() and queue.empty():
                        break
                    yield ": heartbeat\n\n"
                    continue
                yield f"event: {item['event']}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item["event"] in {"done", "error"}:
                    break
        finally:
            # Starlette 断开监听会取消流生成器；屏蔽该取消，等研究真正清理完。
            with anyio.CancelScope(shield=True):
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            trace.unsubscribe(queue)
            logger.info("研究结束 version=%s reason=%s search=%s read=%s",
                        body.version, trace.stop_reason, trace.n_search, trace.n_read)

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
