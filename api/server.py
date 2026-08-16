"""FastAPI 服务(文档 10.4)。

对外提供小说创建 / 图运行(NDJSON 流式)/ interrupt 恢复 / 查询导出接口。
每部小说独立图实例 + MemorySaver(thread_id = novel_id)。

运行:uvicorn api.server:app --reload
"""

import asyncio
import json
import logging
import os
from collections import OrderedDict
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import BaseModel, Field

from config import Config
from graph.builder import build_graph
from memory.sql_store import NovelStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("api")

cfg = Config()
cfg.ensure_dirs()
store = NovelStore(cfg)


class _GraphRegistry:
    """图实例的 LRU 缓存(容量上限,防内存无限增长)。

    每项包含编译图 + MemorySaver(持有该小说全部 checkpoint 历史,随章节
    数线性膨胀),故必须限量。淘汰规则:
    - 超出 max_size 时按最久未使用顺序淘汰
    - 暂停中的图(interrupt 待 resume)跳过:其暂停状态仅存在于
      checkpointer 内,淘汰即丢失人工审查现场
    - 若全部处于暂停态则暂不淘汰(接受临时超限,活动后自然收敛)

    线程模型:仅在事件循环内访问,无需自身加锁(entry.lock 负责同图互斥)。
    """

    def __init__(self, max_size: int | None = None):
        env_limit = os.environ.get("NOVEL_AGENT_GRAPH_CACHE_SIZE")
        self.max_size = max_size if max_size is not None else (
            int(env_limit) if env_limit else 16
        )
        self._items: OrderedDict[str, dict] = OrderedDict()

    def get_or_create(self, novel_id: str) -> dict:
        entry = self._items.get(novel_id)
        if entry is None:
            entry = {"graph": build_graph(checkpointer=MemorySaver()), "lock": asyncio.Lock()}
            self._items[novel_id] = entry
        else:
            self._items.move_to_end(novel_id)  # 标记为最近使用
        self._evict_if_needed(protect=novel_id)
        return entry

    def _evict_if_needed(self, protect: str | None = None) -> None:
        """超出容量时,淘汰一项最久未使用的非暂停图。

        单轮淘汰(非 while 收敛):稳态下每次新建 +1 / 淘汰 -1,
        大小有界于 max_size(+被保护的暂停项),避免一次批量清空。
        protect: 当前正在获取的图不参与本轮淘汰(全暂停场景下
        若不豁免,新建图自身会成为唯一可删项被误删)。
        """
        if len(self._items) <= self.max_size:
            return
        for nid, entry in self._items.items():  # OrderedDict 首端即最久未用
            if nid == protect or self._is_suspended(nid, entry):
                continue
            del self._items[nid]
            logger.info("LRU 淘汰图实例: %s(当前 %d/%d)", nid, len(self._items), self.max_size)
            return
        logger.warning("图缓存超限但全部暂停中,暂缓淘汰(%d 项)", len(self._items))

    @staticmethod
    def _is_suspended(novel_id: str, entry: dict) -> bool:
        """图是否暂停等待人工 resume(interrupt 现场)。"""
        try:
            snap = entry["graph"].get_state({"configurable": {"thread_id": novel_id}})
            return bool(snap.next)
        except Exception:  # 状态不可读视为可淘汰(不因查询失败阻塞回收)
            return False

    def clear(self) -> None:
        self._items.clear()


# 全局图注册表(novel_id → {graph, lock});容量可经 NOVEL_AGENT_GRAPH_CACHE_SIZE 配置
_graphs = _GraphRegistry()


def get_or_create_graph(novel_id: str) -> dict:
    """获取或创建小说的图实例(命中即刷新 LRU 位置)。"""
    return _graphs.get_or_create(novel_id)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Novel Agent API 启动,存储:%s", cfg.sqlite_db_path)
    yield


app = FastAPI(title="Multi-Agent 小说创作系统 API", version="1.0.0", lifespan=lifespan)


# ----------------------------------------------------------------------
# 请求模型
# ----------------------------------------------------------------------
class CreateNovelRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    genre: str = Field(default="武侠", max_length=20)
    inspiration: str = Field(min_length=1, max_length=2000)
    total_chapters: int = Field(default=3, ge=1, le=50)
    style: str = Field(default="jin_yong", max_length=30)


class ResumeRequest(BaseModel):
    feedback: str = Field(default="approve", max_length=5000)


# ----------------------------------------------------------------------
# 小说管理
# ----------------------------------------------------------------------
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


# ----------------------------------------------------------------------
# 图运行(NDJSON 流)
# ----------------------------------------------------------------------
async def _stream_graph(novel_id: str, payload: object):
    """驱动图并以 NDJSON 输出:节点完成事件 → 暂停(interrupt)→ END。"""
    entry = get_or_create_graph(novel_id)
    graph, lock = entry["graph"], entry["lock"]
    config = {"configurable": {"thread_id": novel_id}}

    async with lock:
        async def gen():
            try:
                async for update in graph.astream(payload, config, stream_mode="updates"):
                    for node, _ in (update or {}).items():
                        if node.startswith("__"):
                            continue
                        yield json.dumps({"type": "node_done", "node": node}, ensure_ascii=False) + "\n"
            except Exception as exc:
                logger.exception("图执行失败")
                yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"
                return

            snap = await graph.aget_state(config)
            if snap.next and "human_review" in snap.next:
                draft = snap.values.get("current_draft") or {}
                yield json.dumps(
                    {
                        "type": "interrupt",
                        "node": "human_review",
                        "chapter_number": draft.get("chapter_number"),
                        "title": draft.get("title", ""),
                        "content": draft.get("content", ""),
                        "issues": snap.values.get("issues") or [],
                        "instruction": "POST /api/novels/{id}/resume feedback=approve 或修改意见",
                    },
                    ensure_ascii=False,
                ) + "\n"
            else:
                values = snap.values or {}
                yield json.dumps(
                    {
                        "type": "end",
                        "chapters_done": len(values.get("chapters") or []),
                        "current_chapter": values.get("current_chapter"),
                    },
                    ensure_ascii=False,
                ) + "\n"

        async for line in gen():
            yield line


@app.post("/api/novels/{novel_id}/run")
async def run_novel(novel_id: str) -> StreamingResponse:
    """从头运行创作图(NDJSON 流)。"""
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    novel = store.get_novel(novel_id)

    # 从既有检查点续跑:若已有状态则传 None 续跑,否则初始状态
    entry = get_or_create_graph(novel_id)
    snapshot = entry["graph"].get_state({"configurable": {"thread_id": novel_id}})
    if snapshot.values:
        payload: object = None  # astream(None) 从当前检查点继续
    else:
        payload = {
            "title": novel["title"],
            "genre": novel["genre"] or "武侠",
            "inspiration": novel.get("inspiration", ""),
            "total_chapters": int(novel["total_chapters"] or 3),
            "style": novel["style"] or "jin_yong",
            "novel_id": novel_id,
            "current_chapter": 1,
            "current_phase": "writing",
            "max_revision_attempts": 2,
            "chapters": [],
        }
    return StreamingResponse(_stream_graph(novel_id, payload), media_type="application/x-ndjson")


@app.post("/api/novels/{novel_id}/resume")
async def resume_novel(novel_id: str, req: ResumeRequest) -> StreamingResponse:
    """恢复人工审查暂停的图(feedback=approve 或修改意见)。"""
    entry = get_or_create_graph(novel_id)
    snapshot = entry["graph"].get_state({"configurable": {"thread_id": novel_id}})
    if not snapshot.next:
        raise HTTPException(409, "图不在暂停状态,无法恢复")
    return StreamingResponse(
        _stream_graph(novel_id, Command(resume=req.feedback)), media_type="application/x-ndjson"
    )


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
