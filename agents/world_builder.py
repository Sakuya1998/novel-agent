"""世界观构建 Agent(文档 3.2):输入类型+灵感,输出世界观圣经(YAML)。"""

import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from agents import parse_yaml_block
from memory.vector_store import NovelMemory
from models.llm import get_llm
from prompts import fill_template

logger = logging.getLogger(__name__)


class WorldBuilderAgent:
    """专业世界观架构师:构建自洽、有深度的小说世界观。"""

    def __init__(self, llm: BaseChatModel | None = None, novel_id: str = ""):
        self.llm = llm or get_llm(temperature=0.8)
        self.novel_id = novel_id

    async def generate(self, genre: str, inspiration: str, title: str = "") -> dict[str, Any]:
        """生成世界观圣经。

        Returns:
            {"world_bible": YAML 文本, "world_yaml": 解析后的顶层 dict(尽力而为)}
        """
        prompt = fill_template(
            "world_builder",
            user_input=f"小说标题:{title}\n类型:{genre}\n灵感:{inspiration}",
        )
        logger.info("WorldBuilderAgent 开始生成世界观: %s / %s", title, genre)
        resp = await self.llm.ainvoke(prompt)
        world_bible = resp.content if isinstance(resp.content, str) else str(resp.content)

        # 写入向量记忆,供后续章节检索
        if self.novel_id:
            try:
                memory = NovelMemory(self.novel_id)
                memory.store_content(world_bible, metadata={"type": "world_bible", "title": title})
            except Exception as exc:  # 向量库故障不阻断创作主流程
                logger.warning("世界观写入向量记忆失败: %s", exc)

        world_yaml: dict[str, Any] = {}
        try:
            parsed = parse_yaml_block(world_bible)
            world_yaml = parsed[0] if parsed else {}
        except Exception:
            logger.warning("世界观 YAML 解析失败,保留原文")
        return {"world_bible": world_bible, "world_yaml": world_yaml}
