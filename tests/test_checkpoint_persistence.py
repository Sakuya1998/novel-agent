"""LangGraph SQLite 检查点跨进程和跨入口恢复测试。"""

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command


def _patch_llms(monkeypatch, fake_llm) -> None:
    for mod, attr in [
        ("agents.world_builder", "get_llm"),
        ("agents.character_designer", "get_llm"),
        ("agents.plot_planner", "get_analyzer_llm"),
        ("agents.scene_writer", "get_llm"),
        ("agents.style_editor", "get_llm"),
        ("agents.consistency_checker", "get_analyzer_llm"),
    ]:
        monkeypatch.setattr(f"{mod}.{attr}", lambda **kw: fake_llm)


async def test_async_checkpoint_survives_restart_and_is_sync_readable(tmp_path, monkeypatch):
    """异步暂停现场可跨重启恢复,且同步 saver 能读取同一快照。"""
    from graph.builder import build_graph
    from graph.state import create_initial_state

    fake = FakeListChatModel(responses=[
        "```yaml\n世界观名称: 测试世界\n```",
        "- name: 林寒\n  role: 主角\n",
        "- chapter: 1\n  title: 雾起\n  estimated_words: 100\n",
        "初稿正文。",
        "润色正文。",
        "[]",
    ])
    _patch_llms(monkeypatch, fake)

    path = str(tmp_path / "checkpoints.db")
    graph_config = {"configurable": {"thread_id": "restart-test"}}
    state = create_initial_state(
        novel_id="",
        title="雾中剑",
        genre="武侠",
        inspiration="失忆剑客",
        total_chapters=1,
        style="gu_long",
    )

    async with AsyncSqliteSaver.from_conn_string(path) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        async for _ in graph.astream(state, graph_config, stream_mode="updates"):
            pass
        assert "human_review" in (await graph.aget_state(graph_config)).next

    with SqliteSaver.from_conn_string(path) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        assert "human_review" in graph.get_state(graph_config).next

    async with AsyncSqliteSaver.from_conn_string(path) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        async for _ in graph.astream(Command(resume="approve"), graph_config, stream_mode="updates"):
            pass
        final = await graph.aget_state(graph_config)

    assert final.next == ()
    assert len(final.values["chapters"]) == 1
