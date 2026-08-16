"""风格编辑 Agent(文档 3.6):保持情节,只改风格。"""

import logging

from langchain_core.language_models.chat_models import BaseChatModel

from config import get_style_prompt
from models.llm import get_llm
from prompts import fill_template

logger = logging.getLogger(__name__)


class StyleEditorAgent:
    """专业文体学家:按 STYLE_PROFILES 润色章节,情节零改动。"""

    def __init__(self, llm: BaseChatModel | None = None):
        self.llm = llm or get_llm(temperature=0.7)

    async def polish(self, chapter: dict, style: str) -> dict:
        """润色章节正文。

        Args:
            chapter: 章节记录(content 为待润色正文)
            style: 风格 key

        Returns:
            新章节记录(content 为润色后正文,status=polished)
        """
        number = chapter.get("chapter_number", chapter.get("chapter", 0))
        style_prompt = get_style_prompt(style)
        prompt = fill_template(
            "style_editor",
            style_prompt=style_prompt,
            chapter_draft=chapter.get("content", ""),
        )
        logger.info("StyleEditorAgent 开始润色第 %s 章", number)
        resp = await self.llm.ainvoke(prompt)
        content = resp.content if isinstance(resp.content, str) else str(resp.content)

        polished = dict(chapter)
        polished["content"] = content.strip()
        polished["word_count"] = len(content)
        polished["status"] = "polished"
        return polished
