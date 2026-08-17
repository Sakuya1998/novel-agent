"""情节规划 Agent(文档 3.4):三幕结构 + 冲突升级 + 伏笔回收的章节大纲。"""

import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from agents import invoke_structured, parse_yaml_block
from memory.vector_store import NovelMemory
from models.llm import get_analyzer_llm
from prompts import fill_template

logger = logging.getLogger(__name__)


class PlotPlannerAgent:
    """专业情节规划师:输出逐章大纲(冲突/悬念/角色/伏笔/情绪)。"""

    def __init__(self, llm: BaseChatModel | None = None, novel_id: str = ""):
        self.llm = llm or get_analyzer_llm()
        self.novel_id = novel_id

    async def generate(
        self,
        world_bible: str,
        characters: list[dict[str, Any]],
        total_chapters: int,
        inspiration: str,
    ) -> list[dict[str, Any]]:
        """规划全书章节大纲。

        Returns:
            大纲条目列表(chapter/title/summary/conflict/cliffhanger/characters/
            foreshadowing/emotion/estimated_words)
        """
        char_lines = "\n".join(
            f"- {c.get('name', '?')}({c.get('role', '?')}):{c.get('personality', '')}" for c in characters
        )
        context = (
            f"## 世界观圣经\n{world_bible}\n\n## 角色列表\n{char_lines}\n\n"
            f"## 用户灵感\n{inspiration}\n\n## 总章节数\n{total_chapters} 章"
        )
        prompt = fill_template("plot_planner", context=context)
        logger.info("PlotPlannerAgent 开始规划 %s 章大纲", total_chapters)
        def validate_outline(items: list[dict]) -> None:
            chapters = {int(item.get("chapter", 0)) for item in items}
            expected = set(range(1, total_chapters + 1))
            if chapters != expected:
                raise ValueError(f"章节编号必须完整覆盖 1..{total_chapters},实际为 {sorted(chapters)}")

        _, outline = await invoke_structured(
            self.llm,
            prompt,
            parser=parse_yaml_block,
            validator=validate_outline,
            agent_name=type(self).__name__,
            format_name="YAML",
        )
        # 按 chapter 字段排序,保证章节顺序稳定
        outline.sort(key=lambda c: int(c.get("chapter", 0)))

        if self.novel_id:
            try:
                memory = NovelMemory(self.novel_id)
                for ch in outline:
                    memory.store_content(
                        f"第{ch.get('chapter', '?')}章大纲:{ch.get('summary', '')}",
                        metadata={"type": "outline", "chapter": ch.get("chapter", 0)},
                        content_id=f"{self.novel_id}:outline:{ch.get('chapter', 0)}",
                    )
            except Exception as exc:
                logger.warning("大纲写入向量记忆失败(%s)", type(exc).__name__)

        return outline
