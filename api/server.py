"""FastAPI 服务:小说管理、持久化图运行与人工审查恢复。"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4
from weakref import WeakValueDictionary

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from pydantic import BaseModel, Field

from config import Config
from graph.builder import build_graph
from graph.state import create_initial_state
from memory.sql_store import NovelStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("api")

cfg = Config()
cfg.ensure_dirs()
store = NovelStore(cfg)

# 持久检查点使图实例可共享;这里只保留同一作品的进程内执行互斥。
_novel_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


def get_novel_lock(novel_id: str) -> asyncio.Lock:
    """返回作品级锁;无活动请求后锁可被垃圾回收。"""
    lock = _novel_locks.get(novel_id)
    if lock is None:
        lock = asyncio.Lock()
        _novel_locks[novel_id] = lock
    return lock


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    cfg.ensure_dirs()
    async with AsyncSqliteSaver.from_conn_string(cfg.checkpoint_db_path) as checkpointer:
        fastapi_app.state.graph = build_graph(checkpointer=checkpointer)
        logger.info("Novel Agent API 启动,存储:%s,检查点:%s", cfg.sqlite_db_path, cfg.checkpoint_db_path)
        yield


app = FastAPI(title="Multi-Agent 小说创作系统 API", version="1.0.0", lifespan=lifespan)


class CreateNovelRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    genre: str = Field(default="武侠", max_length=20)
    inspiration: str = Field(min_length=1, max_length=2000)
    total_chapters: int = Field(default=3, ge=1, le=50)
    style: str = Field(default="jin_yong", max_length=30)


class ResumeRequest(BaseModel):
    feedback: str = Field(default="approve", max_length=5000)


@app.post("/api/novels")
async def create_novel(req: CreateNovelRequest) -> dict:
    novel_id = f"novel_{uuid4().hex[:8]}"
    return store.create_novel(
        novel_id, req.title, req.genre, req.style, req.total_chapters, req.inspiration
    )


@app.get("/api/novels")
async def list_novels() -> list[dict]:
    return store.list_novels()


@app.get("/api/novels/{novel_id}")
async def get_novel(novel_id: str) -> dict:
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    novel["chapters"] = store.get_all_chapters(novel_id)
    return novel


def _graph():
    graph = getattr(app.state, "graph", None)
    if graph is None:
        raise RuntimeError("API lifespan 尚未初始化 LangGraph")
    return graph


def _line(event: dict) -> str:
    return json.dumps(event, ensure_ascii=False) + "\n"


async def _single_event(event: dict) -> AsyncIterator[str]:
    yield _line(event)


def _end_event(values: dict, chapters_done: int | None = None) -> dict:
    chapters = values.get("chapters") or []
    return {
        "type": "end",
        "chapters_done": len(chapters) if chapters_done is None else chapters_done,
        "current_chapter": values.get("current_chapter"),
    }


def _human_review_event(snapshot) -> dict:
    """将 LangGraph interrupt 载荷转换为兼容的人工审查 NDJSON 事件。"""
    info: dict = {}
    for task in getattr(snapshot, "tasks", ()):
        interrupts = getattr(task, "interrupts", ())
        if interrupts:
            value = getattr(interrupts[0], "value", None)
            if isinstance(value, dict):
                info = value
                break
    draft = snapshot.values.get("current_draft") or {}
    event = {
        "type": "interrupt",
        "node": "human_review",
        "chapter_number": info.get("chapter_number", draft.get("chapter_number")),
        "title": info.get("title", draft.get("title", "")),
        "content": info.get("content", draft.get("content", "")),
        "issues": info.get("issues", snapshot.values.get("issues") or []),
        "instruction": info.get(
            "instruction", "POST /api/novels/{id}/resume feedback=approve 或修改意见"
        ),
    }
    if info.get("persistence_error"):
        event["persistence_error"] = info["persistence_error"]
    return event


async def _stream_graph(
    novel_id: str,
    payload: object,
    lock: asyncio.Lock,
) -> AsyncIterator[str]:
    """在已持有作品锁的前提下驱动图,结束时负责释放锁。"""
    graph = _graph()
    graph_config = {"configurable": {"thread_id": novel_id}}
    try:
        try:
            async for update in graph.astream(payload, graph_config, stream_mode="updates"):
                for node in (update or {}):
                    if not node.startswith("__"):
                        yield _line({"type": "node_done", "node": node})
        except Exception as exc:
            logger.exception("图执行失败")
            yield _line({"type": "error", "message": str(exc)})
            return

        snapshot = await graph.aget_state(graph_config)
        if snapshot.next and "human_review" in snapshot.next:
            yield _line(_human_review_event(snapshot))
        else:
            yield _line(_end_event(snapshot.values or {}))
    finally:
        lock.release()


@app.post("/api/novels/{novel_id}/run")
async def run_novel(novel_id: str) -> StreamingResponse:
    """开始或从非人工中断检查点继续创作图。"""
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")

    lock = get_novel_lock(novel_id)
    await lock.acquire()
    try:
        graph_config = {"configurable": {"thread_id": novel_id}}
        snapshot = await _graph().aget_state(graph_config)

        if snapshot.values:
            if snapshot.next and "human_review" in snapshot.next:
                raise HTTPException(409, "图正在等待人工审查,请调用 /resume")
            if not snapshot.next:
                lock.release()
                return StreamingResponse(
                    _single_event(_end_event(snapshot.values or {})),
                    media_type="application/x-ndjson",
                )
            payload: object = None
        else:
            chapters = store.get_all_chapters(novel_id)
            total = int(novel["total_chapters"] or 3)
            if chapters:
                if len(chapters) >= total:
                    lock.release()
                    return StreamingResponse(
                        _single_event({
                            "type": "end",
                            "chapters_done": len(chapters),
                            "current_chapter": len(chapters) + 1,
                        }),
                        media_type="application/x-ndjson",
                    )
                raise HTTPException(409, "旧作品缺少 LangGraph 检查点,仅支持查看和导出")

            payload = create_initial_state(
                novel_id=novel_id,
                title=novel["title"],
                genre=novel["genre"] or "武侠",
                inspiration=novel.get("inspiration", ""),
                total_chapters=total,
                style=novel["style"] or "jin_yong",
                config=cfg,
            )

        return StreamingResponse(
            _stream_graph(novel_id, payload, lock),
            media_type="application/x-ndjson",
        )
    except Exception:
        if lock.locked():
            lock.release()
        raise


@app.post("/api/novels/{novel_id}/resume")
async def resume_novel(novel_id: str, req: ResumeRequest) -> StreamingResponse:
    """恢复等待人工审查的图。"""
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")

    lock = get_novel_lock(novel_id)
    await lock.acquire()
    try:
        graph_config = {"configurable": {"thread_id": novel_id}}
        snapshot = await _graph().aget_state(graph_config)
        if not snapshot.next or "human_review" not in snapshot.next:
            raise HTTPException(409, "图不在人工审查暂停状态,无法恢复")
        return StreamingResponse(
            _stream_graph(novel_id, Command(resume=req.feedback), lock),
            media_type="application/x-ndjson",
        )
    except Exception:
        if lock.locked():
            lock.release()
        raise


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
