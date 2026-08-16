"""墨笔 · 小说创作 Agent — FastAPI 后端入口。"""
import json
import time
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import NovelAgent, extract_json_array, normalize_characters, normalize_outline
from .config import DATA_DIR, load_settings, save_settings
from .llm import LLMError
from .storage import Store

app = FastAPI(title="墨笔 · 小说创作 Agent")
store = Store(DATA_DIR)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def get_agent() -> NovelAgent:
    return NovelAgent(load_settings())


def _project_or_404(pid: str) -> Dict[str, Any]:
    p = store.get_project(pid)
    if p is None:
        raise HTTPException(404, "项目不存在")
    return p


def ndjson(gen: AsyncIterator[Dict[str, Any]]) -> StreamingResponse:
    async def iterator():
        try:
            async for ev in gen:
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as e:  # 兜底:保证客户端总能收到错误事件
            yield json.dumps({"type": "error", "message": f"服务器错误:{e}"}, ensure_ascii=False) + "\n"

    return StreamingResponse(iterator(), media_type="application/x-ndjson")


# ================= 设置 =================
class SettingsIn(BaseModel):
    provider: str
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    temperature: float = 0.8
    chapter_words: int = 2500


@app.get("/api/settings")
def read_settings():
    return load_settings()


@app.put("/api/settings")
def update_settings(s: SettingsIn):
    return save_settings(s.model_dump())


# ================= 项目 CRUD =================
class ProjectIn(BaseModel):
    title: str
    idea: str = ""
    genre: str = ""


class ProjectPatch(BaseModel):
    title: Optional[str] = None
    idea: Optional[str] = None
    genre: Optional[str] = None
    premise: Optional[str] = None
    characters: Optional[List[Dict[str, Any]]] = None
    outline: Optional[List[Dict[str, Any]]] = None


@app.get("/api/projects")
def list_projects():
    return store.list_projects()


@app.post("/api/projects")
def create_project(p: ProjectIn):
    return store.create_project(p.title, p.idea, p.genre)


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return _project_or_404(pid)


@app.patch("/api/projects/{pid}")
async def patch_project(pid: str, patch: ProjectPatch):
    def mutate(p):
        for k in ("title", "idea", "genre", "premise", "characters", "outline"):
            v = getattr(patch, k)
            if v is not None:
                p[k] = v

    try:
        return await store.update_project(pid, mutate)
    except KeyError:
        raise HTTPException(404, "项目不存在")


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    if not store.delete_project(pid):
        raise HTTPException(404, "项目不存在")
    return {"ok": True}


# ================= 生成:故事圣经 =================
class PremiseIn(BaseModel):
    idea: str = ""
    genre: str = ""


@app.post("/api/projects/{pid}/generate/premise")
async def gen_premise(pid: str, body: PremiseIn):
    _project_or_404(pid)

    async def gen():
        agent = get_agent()
        project = store.get_project(pid)
        buf = ""
        try:
            async for ev in agent.stream_premise(project, body.idea, body.genre):
                if ev["type"] == "delta":
                    buf += ev["text"]
                yield ev
        except LLMError as e:
            yield {"type": "error", "message": str(e)}
            return

        def mutate(p):
            p["premise"] = buf
            if body.idea:
                p["idea"] = body.idea
            if body.genre:
                p["genre"] = body.genre

        updated = await store.update_project(pid, mutate)
        yield {"type": "done", "project": updated}

    return ndjson(gen())


# ================= 生成:角色卡 =================
class CountIn(BaseModel):
    count: int = 5


@app.post("/api/projects/{pid}/generate/characters")
async def gen_characters(pid: str, body: CountIn):
    _project_or_404(pid)

    async def gen():
        agent = get_agent()
        project = store.get_project(pid)
        buf = ""
        try:
            async for ev in agent.stream_characters(project, max(1, min(body.count, 20))):
                if ev["type"] == "delta":
                    buf += ev["text"]
                yield ev
            characters = normalize_characters(extract_json_array(buf))
        except LLMError as e:
            yield {"type": "error", "message": str(e)}
            return
        except (ValueError, json.JSONDecodeError) as e:
            yield {"type": "error", "message": f"解析角色卡失败:{e}"}
            return

        updated = await store.update_project(pid, lambda p: p.__setitem__("characters", characters))
        yield {"type": "done", "project": updated}

    return ndjson(gen())


# ================= 生成:大纲 =================
class ChaptersIn(BaseModel):
    num_chapters: int = 12


@app.post("/api/projects/{pid}/generate/outline")
async def gen_outline(pid: str, body: ChaptersIn):
    _project_or_404(pid)

    async def gen():
        agent = get_agent()
        project = store.get_project(pid)
        buf = ""
        try:
            async for ev in agent.stream_outline(project, max(1, min(body.num_chapters, 200))):
                if ev["type"] == "delta":
                    buf += ev["text"]
                yield ev
            outline = normalize_outline(extract_json_array(buf))
        except LLMError as e:
            yield {"type": "error", "message": str(e)}
            return
        except (ValueError, json.JSONDecodeError) as e:
            yield {"type": "error", "message": f"解析大纲失败:{e}"}
            return

        updated = await store.update_project(pid, lambda p: p.__setitem__("outline", outline))
        yield {"type": "done", "project": updated}

    return ndjson(gen())


# ================= 章节 CRUD =================
def _upsert_chapter(p: Dict[str, Any], index: int, **fields):
    for ch in p["chapters"]:
        if int(ch.get("index", 0)) == index:
            ch.update(fields)
            ch["updated_at"] = time.time()
            return
    chapter = {"index": index, "title": fields.get("title", f"第{index}章"), "content": "",
               "summary": "", "updated_at": time.time()}
    chapter.update(fields)
    p["chapters"].append(chapter)


class ChapterAddIn(BaseModel):
    title: str = ""


class ChapterIn(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None


@app.post("/api/projects/{pid}/chapters")
async def add_chapter(pid: str, body: ChapterAddIn):
    _project_or_404(pid)
    indexes = [int(o.get("index", 0)) for o in (store.get_project(pid).get("outline") or [])]
    indexes += [int(c.get("index", 0)) for c in (store.get_project(pid).get("chapters") or [])]
    next_index = (max(indexes) + 1) if indexes else 1

    def mutate(p):
        _upsert_chapter(p, next_index, title=body.title or f"第{next_index}章")

    return await store.update_project(pid, mutate)


@app.put("/api/projects/{pid}/chapters/{index}")
async def put_chapter(pid: str, index: int, body: ChapterIn):
    _project_or_404(pid)

    def mutate(p):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        _upsert_chapter(p, index, **fields)

    return await store.update_project(pid, mutate)


@app.delete("/api/projects/{pid}/chapters/{index}")
async def delete_chapter(pid: str, index: int):
    _project_or_404(pid)

    def mutate(p):
        p["chapters"] = [c for c in p["chapters"] if int(c.get("index", 0)) != index]

    return await store.update_project(pid, mutate)


# ================= 生成:章节写作/续写/润色/摘要 =================
class InstructionIn(BaseModel):
    instruction: str = ""


async def _chapter_stream(pid: str, index: int, mode: str, instruction: str):
    """章节生成的通用流水线:流式生成 → 保存 → 自动生成摘要 → 返回最新项目。"""
    agent = get_agent()
    project = store.get_project(pid)
    if project is None:
        yield {"type": "error", "message": "项目不存在"}
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
            await _save(pid, index, mode, buf, "")
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
    except LLMError:
        summary = ""

    def mutate2(p):
        _upsert_chapter(p, index, summary=summary)

    updated = await store.update_project(pid, mutate2)
    yield {"type": "done", "project": updated}


def _chapter_fields(p: Dict[str, Any], index: int, mode: str, buf: str, summary: str) -> Dict[str, Any]:
    plan_title = f"第{index}章"
    for o in p.get("outline") or []:
        if int(o.get("index", 0)) == index and o.get("title"):
            plan_title = o["title"]
            break
    fields: Dict[str, Any] = {"title": plan_title, "summary": summary}
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


async def _save(pid: str, index: int, mode: str, buf: str, summary: str):
    def mutate(p):
        _upsert_chapter(p, index, **_chapter_fields(p, index, mode, buf, summary))

    try:
        await store.update_project(pid, mutate)
    except KeyError:
        pass


@app.post("/api/projects/{pid}/chapters/{index}/write")
async def chapter_write(pid: str, index: int, body: InstructionIn):
    _project_or_404(pid)
    return ndjson(_chapter_stream(pid, index, "write", body.instruction))


@app.post("/api/projects/{pid}/chapters/{index}/continue")
async def chapter_continue(pid: str, index: int, body: InstructionIn):
    _project_or_404(pid)
    return ndjson(_chapter_stream(pid, index, "continue", body.instruction))


@app.post("/api/projects/{pid}/chapters/{index}/polish")
async def chapter_polish(pid: str, index: int, body: InstructionIn):
    _project_or_404(pid)
    return ndjson(_chapter_stream(pid, index, "polish", body.instruction))


@app.post("/api/projects/{pid}/chapters/{index}/summary")
async def chapter_summary(pid: str, index: int):
    project = _project_or_404(pid)
    chapter = next((c for c in project.get("chapters", []) if int(c.get("index", 0)) == index), None)
    if not chapter or not (chapter.get("content") or "").strip():
        raise HTTPException(400, "本章还没有正文")
    try:
        summary = await get_agent().summarize_text(chapter["content"])
    except LLMError as e:
        raise HTTPException(502, str(e))

    def mutate(p):
        _upsert_chapter(p, index, summary=summary)

    return await store.update_project(pid, mutate)


# ================= 静态前端 =================
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
