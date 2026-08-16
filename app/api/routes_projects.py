"""项目 CRUD 与设定生成(故事圣经 / 角色卡 / 大纲)。"""

import json

from fastapi import APIRouter, Depends

from ..core.exceptions import NotFoundError
from ..schemas import ChaptersIn, CountIn, PremiseIn, ProjectIn, ProjectPatch
from ..services.agent import NovelAgent, extract_json_array, normalize_characters, normalize_outline
from ..services.generation import metrics
from ..services.llm import LLMError
from ..storage import Store
from .deps import get_agent, get_store, ndjson, project_or_404

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
def list_projects(store: Store = Depends(get_store)):
    return store.list_projects()


@router.post("")
def create_project(p: ProjectIn, store: Store = Depends(get_store)):
    return store.create_project(p.title, p.idea, p.genre)


@router.get("/{pid}")
def get_project(pid: str, store: Store = Depends(get_store)):
    return project_or_404(store, pid)


@router.patch("/{pid}")
async def patch_project(pid: str, patch: ProjectPatch, store: Store = Depends(get_store)):
    def mutate(p):
        for k in ("title", "idea", "genre", "premise", "characters", "outline"):
            v = getattr(patch, k)
            if v is not None:
                p[k] = v

    # update_project 对不存在的项目抛 NotFoundError,由全局异常处理器返回 404
    return await store.update_project(pid, mutate)


@router.delete("/{pid}")
def delete_project(pid: str, store: Store = Depends(get_store)):
    if not store.delete_project(pid):
        raise NotFoundError("项目不存在")
    return {"ok": True}


# ================= 生成:故事圣经 =================
@router.post("/{pid}/generate/premise")
async def gen_premise(
    pid: str, body: PremiseIn, store: Store = Depends(get_store), agent: NovelAgent = Depends(get_agent)
):
    project_or_404(store, pid)

    async def gen():
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
        metrics["generations_total"] += 1
        yield {"type": "done", "project": updated}

    return ndjson(gen())


# ================= 生成:角色卡 =================
@router.post("/{pid}/generate/characters")
async def gen_characters(
    pid: str, body: CountIn, store: Store = Depends(get_store), agent: NovelAgent = Depends(get_agent)
):
    project_or_404(store, pid)

    async def gen():
        project = store.get_project(pid)
        buf = ""
        try:
            async for ev in agent.stream_characters(project, body.count):
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
        metrics["generations_total"] += 1
        yield {"type": "done", "project": updated}

    return ndjson(gen())


# ================= 生成:大纲 =================
@router.post("/{pid}/generate/outline")
async def gen_outline(
    pid: str, body: ChaptersIn, store: Store = Depends(get_store), agent: NovelAgent = Depends(get_agent)
):
    project_or_404(store, pid)

    async def gen():
        project = store.get_project(pid)
        buf = ""
        try:
            async for ev in agent.stream_outline(project, body.num_chapters):
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
        metrics["generations_total"] += 1
        yield {"type": "done", "project": updated}

    return ndjson(gen())
