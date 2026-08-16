"""章节 CRUD 与章节生成(写作 / 续写 / 润色 / 摘要)。

生成互斥:同一章节同时只允许一个 write/continue/polish 任务,
并发请求收到错误事件(前端表现为可读报错),避免两次流式输出互相覆盖。
"""

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends

from ..core.exceptions import NotFoundError, UpstreamError
from ..schemas import ChapterAddIn, ChapterIn, InstructionIn
from ..services.agent import NovelAgent
from ..services.generation import chapter_generation_lock, generation_registry, metrics
from ..services.llm import LLMError
from ..storage import Store
from .deps import get_agent, get_store, ndjson, project_or_404

logger = logging.getLogger("novel.chapter")

router = APIRouter(prefix="/api/projects/{pid}/chapters", tags=["chapters"])


def _upsert_chapter(p: dict[str, Any], index: int, **fields):
    for ch in p["chapters"]:
        if int(ch.get("index", 0)) == index:
            ch.update(fields)
            ch["updated_at"] = time.time()
            return
    chapter = {
        "index": index,
        "title": fields.get("title", f"第{index}章"),
        "content": "",
        "summary": "",
        "updated_at": time.time(),
    }
    chapter.update(fields)
    p["chapters"].append(chapter)


def _chapter_fields(p: dict[str, Any], index: int, mode: str, buf: str, summary: str) -> dict[str, Any]:
    plan_title = f"第{index}章"
    for o in p.get("outline") or []:
        if int(o.get("index", 0)) == index and o.get("title"):
            plan_title = o["title"]
            break
    fields: dict[str, Any] = {"title": plan_title, "summary": summary}
    if mode == "continue":
        old = ""
        for c in p.get("chapters") or []:
            if int(c.get("index", 0)) == index:
                old = c.get("content", "")
                break
        fields["content"] = (old + ("\n\n" if old and not old.endswith("\n") else "") + buf).strip()
    else:  # write / polish 均为整章替换
        fields["content"] = buf.strip()
    return fields


# ================= 章节 CRUD =================
@router.post("")
async def add_chapter(pid: str, body: ChapterAddIn, store: Store = Depends(get_store)):
    project = project_or_404(store, pid)
    indexes = [int(o.get("index", 0)) for o in (project.get("outline") or [])]
    indexes += [int(c.get("index", 0)) for c in (project.get("chapters") or [])]
    next_index = (max(indexes) + 1) if indexes else 1

    def mutate(p):
        _upsert_chapter(p, next_index, title=body.title or f"第{next_index}章")

    return await store.update_project(pid, mutate)


@router.put("/{index}")
async def put_chapter(pid: str, index: int, body: ChapterIn, store: Store = Depends(get_store)):
    project_or_404(store, pid)

    def mutate(p):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        _upsert_chapter(p, index, **fields)

    return await store.update_project(pid, mutate)


@router.delete("/{index}")
async def delete_chapter(pid: str, index: int, store: Store = Depends(get_store)):
    project_or_404(store, pid)

    def mutate(p):
        p["chapters"] = [c for c in p["chapters"] if int(c.get("index", 0)) != index]

    return await store.update_project(pid, mutate)


# ================= 章节生成 =================
async def _chapter_stream(store: Store, agent: NovelAgent, pid: str, index: int, mode: str, instruction: str):
    """章节生成的通用流水线:互斥 → 流式生成 → 保存 → 自动摘要 → 返回最新项目。"""
    project = store.get_project(pid)
    if project is None:
        yield {"type": "error", "message": "项目不存在"}
        return

    with chapter_generation_lock(generation_registry, pid, index, f"{mode}") as acquired:
        if not acquired:
            yield {"type": "error", "message": "该章节正在生成中,请等待当前任务完成后再试。"}
            return

        buf = ""
        try:
            async for ev in agent.stream_chapter(project, index, mode, instruction):
                if ev["type"] == "delta":
                    buf += ev["text"]
                yield ev
        except LLMError as e:
            # 生成中断也保存已生成的部分
            if buf.strip():
                await _save_partial(store, pid, index, mode, buf)
            logger.warning("章节生成中断 pid=%s index=%s mode=%s: %s", pid, index, mode, e)
            yield {"type": "error", "message": str(e)}
            return

        if not buf.strip():
            yield {"type": "error", "message": "模型返回了空内容,请重试。"}
            return

        yield {"type": "status", "text": "正在生成本章摘要…"}

        def mutate(p):
            _upsert_chapter(p, index, **_chapter_fields(p, index, mode, buf, ""))

        await store.update_project(pid, mutate)

        summary = ""
        try:
            final = NovelAgent.get_chapter(store.get_project(pid), index)
            content = (final or {}).get("content", "")
            summary = await agent.summarize_text(content)
        except LLMError as e:
            logger.warning("章节摘要生成失败 pid=%s index=%s: %s", pid, index, e)
            summary = ""

        def mutate2(p):
            _upsert_chapter(p, index, summary=summary)

        updated = await store.update_project(pid, mutate2)
        metrics["generations_total"] += 1
        logger.info("章节生成完成 pid=%s index=%s mode=%s chars=%d", pid, index, mode, len(buf))
        yield {"type": "done", "project": updated}


async def _save_partial(store: Store, pid: str, index: int, mode: str, buf: str):
    def mutate(p):
        _upsert_chapter(p, index, **_chapter_fields(p, index, mode, buf, ""))

    try:
        await store.update_project(pid, mutate)
    except NotFoundError:
        return  # 项目已被删除,放弃保存部分内容


def _stream_route(mode: str):
    async def endpoint(
        pid: str,
        index: int,
        body: InstructionIn,
        store: Store = Depends(get_store),
        agent: NovelAgent = Depends(get_agent),
    ):
        project_or_404(store, pid)
        return ndjson(_chapter_stream(store, agent, pid, index, mode, body.instruction))

    endpoint.__name__ = f"chapter_{mode}"
    return endpoint


router.post("/{index}/write")(_stream_route("write"))
router.post("/{index}/continue")(_stream_route("continue"))
router.post("/{index}/polish")(_stream_route("polish"))


@router.post("/{index}/summary")
async def chapter_summary(
    pid: str, index: int, store: Store = Depends(get_store), agent: NovelAgent = Depends(get_agent)
):
    project = project_or_404(store, pid)
    chapter = next((c for c in project.get("chapters", []) if int(c.get("index", 0)) == index), None)
    if not chapter or not (chapter.get("content") or "").strip():
        raise NotFoundError("本章还没有正文")
    try:
        summary = await agent.summarize_text(chapter["content"])
    except LLMError as e:
        raise UpstreamError(str(e)) from e

    def mutate(p):
        _upsert_chapter(p, index, summary=summary)

    return await store.update_project(pid, mutate)
