"""共享状态定义(文档 4.1)。

LangGraph 的核心:所有节点通过 NovelState 读写共享数据,
StateGraph 在节点返回后自动做状态合并(chapters 用 operator.add 累加)。
"""

import operator
from typing import Annotated, Any, TypedDict

from config import Config


class NovelState(TypedDict, total=False):
    """小说创作的全局状态。"""

    # --- 用户输入 ---
    title: str  # 小说标题
    genre: str  # 类型:如"武侠"、"科幻"、"言情"
    inspiration: str  # 一句话灵感描述
    total_chapters: int  # 预计总章节数
    style: str  # 目标风格:对应 config.STYLE_PROFILES 的 key
    novel_id: str  # 小说标识(记忆/持久化用;空串表示内存运行)

    # --- 创作状态 ---
    current_chapter: int  # 当前章节号
    current_phase: str  # 当前创作阶段
    chapter_plan: dict[str, Any]  # 当前章节的大纲(单章详情)
    current_draft: dict[str, Any]  # 当前章节草稿(写作/润色/质检间流转,定稿后并入 chapters)
    revision_notes: str  # 重写指引(一致性问题/人工反馈,供 SceneWriter 修正)

    # --- 创作内容 ---
    world_bible: str  # 世界观圣经(YAML 文本)
    characters: list[dict[str, Any]]  # 角色列表(结构化)
    outline: list[dict[str, Any]]  # 章节大纲(结构化)
    chapters: Annotated[list[dict[str, Any]], operator.add]  # 已写章节

    # --- 质控与协作 ---
    issues: list[dict[str, Any]]  # 一致性问题
    revision_count: int  # 当前章节修订次数
    max_revision_attempts: int  # 最大修订次数
    max_chapter_words: int  # 单章目标字数上限
    human_feedback: str  # 人工反馈
    persistence_error: str  # SQLite 定稿失败信息;非空时回到人工审查重试
    error: str  # 错误信息
    next_agent: str  # Orchestrator 决定的下一个 Agent


def create_initial_state(
    *,
    novel_id: str,
    title: str,
    genre: str,
    inspiration: str,
    total_chapters: int,
    style: str,
    config: Config | None = None,
) -> NovelState:
    """为所有入口构造一致的 LangGraph 初始状态。"""
    cfg = config or Config()
    return {
        "title": title,
        "genre": genre,
        "inspiration": inspiration,
        "total_chapters": total_chapters,
        "style": style,
        "novel_id": novel_id,
        "current_chapter": 1,
        "current_phase": "writing",
        "max_revision_attempts": cfg.max_revision_attempts,
        "max_chapter_words": cfg.max_chapter_words,
        "revision_count": 0,
        "revision_notes": "",
        "chapters": [],
    }
