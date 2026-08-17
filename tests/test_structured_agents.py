"""结构化 Agent 输出重试与严格校验测试。"""

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from agents import StructuredOutputError
from agents.character_designer import CharacterDesignerAgent
from agents.consistency_checker import ConsistencyCheckerAgent
from agents.plot_planner import PlotPlannerAgent


async def test_character_designer_retries_once_after_invalid_yaml():
    fake = FakeListChatModel(responses=[
        "这不是 YAML 列表",
        "- name: 林寒\n  role: 主角\n",
    ])
    agent = CharacterDesignerAgent(llm=fake)

    characters = await agent.generate("世界观", "灵感")

    assert characters[0]["name"] == "林寒"


async def test_plot_planner_fails_when_retry_still_misses_chapters():
    incomplete = "- chapter: 1\n  title: 开端\n"
    fake = FakeListChatModel(responses=[incomplete, incomplete])
    agent = PlotPlannerAgent(llm=fake)

    with pytest.raises(StructuredOutputError, match="PlotPlannerAgent"):
        await agent.generate("世界观", [], total_chapters=2, inspiration="灵感")


async def test_consistency_checker_never_treats_unparseable_text_as_success():
    fake = FakeListChatModel(responses=["一致性检查通过", "仍然没有 JSON"])
    agent = ConsistencyCheckerAgent(llm=fake)

    with pytest.raises(StructuredOutputError, match="ConsistencyCheckerAgent"):
        await agent.check(
            chapter={"chapter_number": 1, "content": "正文"},
            world_bible="世界观",
            characters=[],
            outline=[],
            previous_chapters=[],
        )
