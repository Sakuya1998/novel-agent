"""角色设计 Agent(文档 3.3):五维角色档案 + 角色弧光设计。"""

import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from agents import parse_yaml_block
from memory.vector_store import NovelMemory
from models.llm import get_llm
from prompts import fill_template

logger = logging.getLogger(__name__)


class CharacterDesignerAgent:
    """专业角色设计师:心理/关系/语言/行为/弧光五维建模。"""

    def __init__(self, llm: BaseChatModel | None = None, novel_id: str = ""):
        self.llm = llm or get_llm(temperature=0.7)
        self.novel_id = novel_id

    async def generate(self, world_bible: str, inspiration: str) -> list[dict[str, Any]]:
        """生成主要角色列表。

        Args:
            world_bible: 世界观圣经文本
            inspiration: 用户灵感

        Returns:
            角色档案列表(name/role/personality/relationships/speech_pattern/behavior/arc)
        """
        context = f"## 世界观圣经\n{world_bible}\n\n## 用户灵感\n{inspiration}"
        prompt = fill_template("character_designer", context=context)
        logger.info("CharacterDesignerAgent 开始设计角色")
        resp = await self.llm.ainvoke(prompt)
        content = resp.content if isinstance(resp.content, str) else str(resp.content)

        characters = parse_yaml_block(content)

        # 角色卡逐个写入向量记忆
        if self.novel_id:
            try:
                memory = NovelMemory(self.novel_id)
                for c in characters:
                    card = f"角色档案:{c.get('name', '未知')}\n{c!r}"
                    memory.store_content(card, metadata={"type": "character", "name": str(c.get("name", ""))})
            except Exception as exc:
                logger.warning("角色写入向量记忆失败: %s", exc)

        return characters
