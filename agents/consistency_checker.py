"""一致性检查 Agent(文档 3.7):设定/角色/情节/时间线/伏笔五维检查。"""

import logging
from typing import Any

from agents import invoke_structured, parse_json_block
from models.llm import get_analyzer_llm
from prompts import fill_template

logger = logging.getLogger(__name__)

# 供 prompt 注入的历史摘要上限(章)
_SUMMARY_WINDOW = 5
_CONTENT_LIMIT = 8000


class ConsistencyCheckerAgent:
    """专职质检:输出结构化 issues,驱动章节回滚重写。"""

    def __init__(self, llm=None):
        self.llm = llm or get_analyzer_llm()

    async def check(
        self,
        chapter: dict[str, Any],
        world_bible: str,
        characters: list[dict[str, Any]],
        outline: list[dict[str, Any]],
        previous_chapters: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """检查章节一致性。

        Returns:
            issues 列表: [{"type", "description", "chapter", "severity", "suggestion"}]
        """
        number = chapter.get("chapter_number", chapter.get("chapter", 0))

        char_lines = "\n".join(
            f"- {c.get('name', '?')}({c.get('role', '?')}):{c.get('personality', '')}" for c in characters
        )
        context = (
            f"## 世界观圣经(摘要)\n{world_bible[:2000]}\n\n"
            f"## 角色设定\n{char_lines}\n\n## 大纲\n{outline!r}"
        )[:4000]

        summaries = "\n".join(
            f"- 第{c.get('chapter_number', '?')}章:{str(c.get('summary', ''))[:200]}"
            for c in previous_chapters[-_SUMMARY_WINDOW:]
        ) or "暂无"

        prompt = fill_template(
            "consistency_checker",
            context=context,
            chapter_summaries=summaries,
            chapter_number=number,
            chapter_content=chapter.get("content", "")[:_CONTENT_LIMIT],
        )
        logger.info("ConsistencyCheckerAgent 检查第 %s 章", number)
        def validate_issues(items: list[dict]) -> None:
            allowed = {"high", "medium", "low"}
            for item in items:
                severity = str(item.get("severity", "")).lower()
                if severity not in allowed:
                    raise ValueError(f"无效 severity:{severity or '<empty>'}")

        _, issues = await invoke_structured(
            self.llm,
            prompt,
            parser=parse_json_block,
            validator=validate_issues,
            agent_name=type(self).__name__,
            format_name="JSON",
        )
        return issues
