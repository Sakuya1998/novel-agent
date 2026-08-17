"""正文写作 Agent(文档 3.5):章节正文生成,风格档案控制输出。"""

import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from config import get_style_prompt
from memory.vector_store import NovelMemory
from models.llm import get_llm
from prompts import fill_template

logger = logging.getLogger(__name__)

# 注入 prompt 的上下文长度上限(字符),防止超长 prompt 撑爆 token 预算
_WORLD_LIMIT = 3000
_MEMORY_LIMIT = 4


class SceneWriterAgent:
    """专业小说家:展示而非告知,按风格档案逐章写作。"""

    def __init__(self, llm: BaseChatModel | None = None, novel_id: str = ""):
        self.llm = llm or get_llm(temperature=0.8)
        self.novel_id = novel_id

    async def write_chapter(
        self,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """撰写当前章节。

        Args:
            state: NovelState(chapter_plan/style/chapters/current_chapter/...)

        Returns:
            {"chapter_number", "title", "content", "summary"} 章节记录
        """
        number = int(state.get("current_chapter", 1))
        plan: dict[str, Any] = state.get("chapter_plan") or {}
        style_prompt = get_style_prompt(state.get("style", ""))

        # 组装上下文:世界观(截断)+ 相关记忆(向量检索)
        world = str(state.get("world_bible", ""))[:_WORLD_LIMIT]
        memory_snippets: list[str] = []
        if self.novel_id:
            try:
                memory = NovelMemory(self.novel_id)
                memory_snippets = memory.get_chapter_memory(number, k=_MEMORY_LIMIT)
            except Exception as exc:
                logger.warning("章节记忆检索失败: %s", exc)
        memory_text = "\n".join(f"- {s[:300]}" for s in memory_snippets) or "无"

        # 重写指引:一致性 high 问题 / 人工修改意见(首次写作为空)
        revision_notes = str(state.get("revision_notes", "")).strip()
        revision_block = (
            f"\n\n## 重写指引(必须修正以下问题后重写本章)\n{revision_notes}" if revision_notes else ""
        )

        # 上一章结尾 600 字用于衔接
        chapters = state.get("chapters") or []
        prev_ending = "这是第一章,无需衔接。"
        if chapters:
            prev_content = str(chapters[-1].get("content", ""))
            prev_ending = prev_content[-600:] if prev_content else "(上一章为空)"

        target_words = int(plan.get("estimated_words") or state.get("max_chapter_words") or 6000)
        prompt = fill_template(
            "scene_writer",
            target_words=target_words,
            style_prompt=style_prompt,
            context=f"## 世界观摘要\n{world}\n\n## 相关记忆\n{memory_text}{revision_block}",
            chapter_plan=str(plan),
            previous_ending=prev_ending,
            chapter_number=number,
        )
        logger.info("SceneWriterAgent 开始撰写第 %s 章(目标 %s 字)", number, target_words)
        resp = await self.llm.ainvoke(prompt)
        content = resp.content if isinstance(resp.content, str) else str(resp.content)

        chapter = {
            "chapter": number,
            "chapter_number": number,
            "title": str(plan.get("title", f"第{number}章")),
            "content": content.strip(),
            "summary": str(plan.get("summary", ""))[:300],  # 大纲摘要先占位,后续可精炼
            "word_count": len(content),
            "status": "draft",
        }

        return chapter
