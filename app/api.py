"""提供健康检查、版本与题集管理、历史记录、文档转发和可取消的研究 SSE。"""

import asyncio
import json
import logging
from time import monotonic

import anyio
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.llm import LLM
from app import runner
from app import history
from app.history import process_alive
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


def dataset_metadata(name: str, items: list[dict]) -> dict:
    """返回题集概要，不把评测标注混入研究请求。"""
    return {"name": name, "n": len(items),
            "source": "builtin" if name in runner.BUILTIN_DATASETS else "uploaded",
            "has_evidence": any(bool(item.get("evidence_docids")) for item in items)}


@app.get("/api/datasets")
async def list_datasets():
    """只列公开开发题集和独立上传目录，不扫描其他课程题集。"""
    names = list(runner.BUILTIN_DATASETS)
    if runner.UPLOADED_DATASET_DIR.exists():
        names.extend(path.stem for path in sorted(runner.UPLOADED_DATASET_DIR.glob("*.jsonl"))
                     if path.stem not in runner.BUILTIN_DATASETS)
    return [dataset_metadata(name, runner.read_dataset(name)) for name in names]


@app.get("/api/datasets/{name}")
async def get_dataset(name: str):
    """完整标注仅提供给评测页面；研究任务始终只接收题面。"""
    try:
        return runner.read_dataset(name)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="题集不存在") from exc


@app.post("/api/datasets")
async def upload_dataset(request: Request):
    """验证整份上传后才写文件，补齐编号，拒绝覆盖内置或已有题集。"""
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("上传内容必须是对象")
        name, items = body.get("name"), body.get("items")
        path = runner.dataset_path(name)
        # Windows 保留设备名不能用作文件名。
        if name.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)),
                            *(f"LPT{i}" for i in range(10))}:
            raise ValueError("题集名不能使用系统保留名称")
        if name in runner.BUILTIN_DATASETS or path.exists():
            raise ValueError("题集已存在，不能覆盖")
        if not isinstance(items, list) or not items:
            raise ValueError("items 必须是非空数组")
        normalized, seen = [], set()
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict) or any(
                not isinstance(item.get(key), str) or not item[key].strip()
                for key in ("query", "answer")
            ):
                raise ValueError("每道题必须包含非空字符串 query 和 answer")
            query_id = item.get("query_id", str(index))
            if isinstance(query_id, bool) or not isinstance(query_id, (str, int)) or not str(query_id).strip():
                raise ValueError("query_id 必须是非空字符串或整数")
            query_id = str(query_id)
            if query_id in seen:
                raise ValueError("题集中存在重复编号")
            seen.add(query_id)
            for key in ("gold_docids", "evidence_docids"):
                if key in item and (not isinstance(item[key], list) or any(
                    isinstance(value, bool) or not isinstance(value, (str, int)) for value in item[key]
                )):
                    raise ValueError(f"{key} 必须是文档编号数组")
            normalized.append({**item, "query_id": query_id})
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    content = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(content)
    except FileExistsError as exc:
        raise HTTPException(status_code=400, detail="题集已存在，不能覆盖") from exc
    return dataset_metadata(name, normalized)


@app.delete("/api/datasets/{name}")
async def delete_dataset(name: str):
    """只删除独立上传目录中的指定题集，内置题集始终不可删除。"""
    try:
        if name in runner.BUILTIN_DATASETS:
            raise FileNotFoundError(name)
        runner.dataset_path(name).unlink()
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="上传题集不存在") from exc
    return {"ok": True}


@app.get("/api/runs")
def list_runs():
    """列出本项目真实运行，按进程存活状态适配前端字段。"""
    if not runner.RUNS_DIR.exists():
        return []
    results = []
    for directory in sorted(runner.RUNS_DIR.iterdir(), reverse=True):
        if not directory.is_dir() or not (directory / "config.json").is_file():
            continue
        try:
            results.append(history.run_info(directory.name, alive=process_alive))
        except FileNotFoundError:
            continue
        except (ValueError, OSError):
            logger.warning("运行记录无法读取 run_id=%s", directory.name)
    return results


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    """返回单次运行的配置、状态、汇总，不改写磁盘状态。"""
    try:
        return history.run_info(run_id, alive=process_alive)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="运行不存在") from exc


@app.get("/api/runs/{run_id}/items")
def list_run_items(run_id: str):
    """供列表和同题对照使用，尚未判分的题保留未知状态。"""
    try:
        return [history.item_summary(item) for item in history.run_items(run_id).values()]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="运行不存在") from exc


@app.get("/api/runs/{run_id}/items/{query_id}")
def get_run_item(run_id: str, query_id: str):
    """返回单题原始响应、完整事件及对应判分，支持泳道回放。"""
    try:
        items = history.run_items(run_id)
        if query_id not in items:
            raise FileNotFoundError(query_id)
        return items[query_id]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="运行或题目不存在") from exc


@app.get("/api/documents/{docid}")
async def get_document(docid: str):
    """只通过本地检索服务读取文档原文，确保关闭客户端。"""
    client = SearchClient()
    try:
        return await client.document(docid)
    except httpx.HTTPStatusError as exc:
        code = 404 if exc.response.status_code == 404 else 502
        raise HTTPException(status_code=code, detail="文档不存在" if code == 404 else "检索服务响应异常") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="检索服务连接失败") from exc
    finally:
        await client.close()


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
