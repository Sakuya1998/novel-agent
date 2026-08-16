"""LangGraph 节点实现(文档 4.2 / 4.3)。

节点即"读取状态 → 调用 Agent → 返回状态增量"的纯函数。
定稿语义:current_draft 在 写作→润色→质检→人工审查 之间流转,
人工批准时才 append 到 chapters(operator.add reducer 的唯一写入点),
保证 chapters 中的每一章都是终稿。
"""

import logging
from typing import Any

from langgraph.types import interrupt

from agents.character_designer import CharacterDesignerAgent
from agents.consistency_checker import ConsistencyCheckerAgent
from agents.orchestrator import OrchestratorAgent
from agents.plot_planner import PlotPlannerAgent
from agents.scene_writer import SceneWriterAgent
from agents.style_editor import StyleEditorAgent
from agents.world_builder import WorldBuilderAgent
from memory.sql_store import NovelStore

logger = logging.getLogger(__name__)
orchestrator_agent = OrchestratorAgent()

# 结构化存储:模块级惰性单例(测试可注入隔离实例)
_store: NovelStore | None = None


def _novel_store() -> NovelStore:
    global _store
    if _store is None:
        _store = NovelStore()
    return _store


def _novel_id(state: dict[str, Any]) -> str:
    """从状态中提取小说 ID(用于记忆/持久化);缺省空串表示不持久化。"""
    return str(state.get("novel_id", ""))


async def orchestrator_node(state: dict[str, Any]) -> dict[str, Any]:
    """主控调度:决定下一个 Agent,并准备当前章节大纲。"""
    next_agent = await orchestrator_agent.decide_next(state)
    updates: dict[str, Any] = {"next_agent": next_agent}

    # 进入新章节的写作循环时,取对应大纲作为 chapter_plan
    if next_agent == "scene_writer":
        outline = state.get("outline") or []
        current = int(state.get("current_chapter", 1))
        plan = next(
            (c for c in outline if int(c.get("chapter", 0)) == current),
            {"chapter": current, "title": f"第{current}章", "summary": ""},
        )
        updates["chapter_plan"] = plan
        updates["current_phase"] = "writing"
    return updates


async def world_builder_node(state: dict[str, Any]) -> dict[str, Any]:
    """构建世界观圣经,进入角色设计阶段。"""
    agent = WorldBuilderAgent(novel_id=_novel_id(state))
    result = await agent.generate(
        genre=state.get("genre", ""),
        inspiration=state.get("inspiration", ""),
        title=state.get("title", ""),
    )
    return {"world_bible": result["world_bible"]}


async def character_designer_node(state: dict[str, Any]) -> dict[str, Any]:
    """设计五维角色档案。"""
    agent = CharacterDesignerAgent(novel_id=_novel_id(state))
    characters = await agent.generate(
        world_bible=state.get("world_bible", ""),
        inspiration=state.get("inspiration", ""),
    )
    return {"characters": characters}


async def plot_planner_node(state: dict[str, Any]) -> dict[str, Any]:
    """规划全书章节大纲。"""
    agent = PlotPlannerAgent(novel_id=_novel_id(state))
    outline = await agent.generate(
        world_bible=state.get("world_bible", ""),
        characters=state.get("characters") or [],
        total_chapters=int(state.get("total_chapters", 10)),
        inspiration=state.get("inspiration", ""),
    )
    return {"outline": outline}


async def scene_writer_node(state: dict[str, Any]) -> dict[str, Any]:
    """撰写当前章草稿,交由风格编辑。"""
    agent = SceneWriterAgent(novel_id=_novel_id(state))
    chapter = await agent.write_chapter(state)
    return {
        "current_draft": chapter,
        "current_phase": "style_editing",
        "revision_count": int(state.get("revision_count", 0)),
    }


async def style_editor_node(state: dict[str, Any]) -> dict[str, Any]:
    """风格润色当前草稿,交由一致性检查。"""
    agent = StyleEditorAgent()
    polished = await agent.polish(state.get("current_draft") or {}, state.get("style", ""))
    return {
        "current_draft": polished,
        "current_phase": "consistency_check",
    }


async def consistency_checker_node(state: dict[str, Any]) -> dict[str, Any]:
    """一致性检查:结果写入 issues;存在 high 问题且未超重写上限 → 回写重写。

    通过(无问题/仅轻微/已超上限)→ human_review 人工终审。
    """
    agent = ConsistencyCheckerAgent()
    draft = state.get("current_draft") or {}
    issues = await agent.check(
        chapter=draft,
        world_bible=state.get("world_bible", ""),
        characters=state.get("characters") or [],
        outline=state.get("outline") or [],
        previous_chapters=state.get("chapters") or [],
    )
    updates: dict[str, Any] = {"issues": issues}

    serious = [i for i in issues if str(i.get("severity", "low")).lower() == "high"]
    over_limit = int(state.get("revision_count", 0)) >= int(
        state.get("max_revision_attempts", 3)
    )
    if serious and not over_limit:
        notes = "\n".join(
            f"- [{i.get('severity')}] {i.get('description')} 修正建议:{i.get('suggestion')}"
            for i in serious
        )
        updates.update({
            "revision_notes": notes,
            "current_phase": "writing",  # 条件边将路由回 scene_writer 重写
        })
    # else: 保持 phase=consistency_check,条件边放行至 human_review
    return updates


async def human_review_node(state: dict[str, Any]) -> dict[str, Any]:
    """人工审查(文档 9.1):interrupt 暂停图,等待 resume。

    resume 值约定:
        - "approve" / "通过" / 空白 → 定稿并进入下一章
        - 其他文本 → 视为修改意见,回 scene_writer 重写

    注意:interrupt 后节点将在 resume 时重新执行,本节点必须保持幂等。
    """
    draft = state.get("current_draft") or {}
    number = draft.get("chapter_number", state.get("current_chapter", 0))

    feedback = interrupt(
        {
            "type": "human_review",
            "chapter_number": number,
            "title": draft.get("title", ""),
            "summary": draft.get("summary", ""),
            "word_count": draft.get("word_count", 0),
            "content": str(draft.get("content", "")),
            "issues": state.get("issues") or [],
            "instruction": "输入 approve 定稿进入下一章;或直接输入修改意见。",
        }
    )

    approved = str(feedback).strip().lower() in {"", "approve", "通过", "y", "yes"}
    if approved:
        # 定稿:chapters 是 operator.add reducer,此处为唯一 append 点
        final_draft = {**draft, "status": "final"}
        updates: dict[str, Any] = {
            "chapters": [final_draft],
            "current_chapter": int(state.get("current_chapter", 1)) + 1,
            "current_phase": "writing",
            "revision_count": 0,
            "revision_notes": "",
        }
        nid = _novel_id(state)
        if nid:
            try:
                next_chapter = int(state.get("current_chapter", 1)) + 1
                store = _novel_store()
                store.save_chapter(
                    novel_id=nid,
                    chapter_number=int(number),
                    title=str(draft.get("title", "")),
                    content=str(draft.get("content", "")),
                    summary=str(draft.get("summary", "")),
                    status="final",
                )
                store.save_progress(
                    novel_id=nid,
                    current_chapter=next_chapter,
                    current_phase="writing",
                )
            except Exception as exc:
                logger.warning("定稿章节持久化失败: %s", exc)
        return updates

    return {
        "revision_notes": str(feedback),
        "current_phase": "writing",
        "revision_count": int(state.get("revision_count", 0)) + 1,
    }
