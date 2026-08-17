"""LangGraph 图全流程冒烟测试(假 LLM,不依赖 API Key)。

覆盖:
- 完整拓扑:世界观 → 角色 → 大纲 → 写作 → 润色 → 质检 → 人工审查(暂停)
- interrupt 恢复:approve 定稿 → END;修改意见 → 回写重写循环
- chapters reducer:每章仅终稿入列
"""

from langgraph.types import Command

# 首段流会依次经过的节点(human_review 被 interrupt 打断,不产生 update 事件)
EXPECTED_NODES = [
    "world_builder",
    "character_designer",
    "plot_planner",
    "scene_writer",
    "style_editor",
    "consistency_checker",
]


def _patch_llms(monkeypatch, fake_llm) -> None:
    """把全部 Agent 的 LLM 工厂替换为共享假模型。"""
    for mod, attr in [
        ("agents.world_builder", "get_llm"),
        ("agents.character_designer", "get_llm"),
        ("agents.plot_planner", "get_analyzer_llm"),
        ("agents.scene_writer", "get_llm"),
        ("agents.style_editor", "get_llm"),
        ("agents.consistency_checker", "get_analyzer_llm"),
    ]:
        monkeypatch.setattr(f"{mod}.{attr}", lambda **kw: fake_llm)


def _initial_state(total: int = 1) -> dict:
    return {
        "title": "雾中剑",
        "genre": "武侠",
        "inspiration": "失忆剑客寻找过去",
        "total_chapters": total,
        "style": "gu_long",
        "novel_id": "",  # 空串:跳过向量/SQLite 持久化,纯内存跑图
        "current_chapter": 1,
        "current_phase": "writing",
        "max_revision_attempts": 2,
        "chapters": [],
    }


async def _drive(graph, config, payload) -> list[str]:
    """同步迭代一段流,返回本段执行的节点名序列(剔除 orchestrator 调度中枢)。"""
    visited: list[str] = []
    async for update in graph.astream(payload, config, stream_mode="updates"):
        visited.extend(n for n in (update or {}) if not n.startswith("__"))
    return [n for n in visited if n != "orchestrator"]


async def test_full_flow_with_auto_approve(monkeypatch, fake_llm):
    """1 章全流程:6 次 LLM 调用 + interrupt 暂停 + approve 定稿 → END。"""
    _patch_llms(monkeypatch, fake_llm)

    from graph.builder import build_graph

    graph = build_graph()
    config = {"configurable": {"thread_id": "t-auto"}}

    visited = await _drive(graph, config, _initial_state())
    assert visited == EXPECTED_NODES

    # 图暂停在 human_review
    snap = await graph.aget_state(config)
    assert "human_review" in snap.next
    draft = snap.values.get("current_draft") or {}
    assert "润色" in draft["content"]  # 经过 StyleEditor

    # approve → 定稿(human_review 完成;orchestrator 判定 END,被 _drive 过滤)
    tail = await _drive(graph, config, Command(resume="approve"))
    assert tail == ["human_review"]

    snap_final = await graph.aget_state(config)
    assert snap_final.next == ()  # 图已运行至 END
    final = snap_final.values
    assert len(final["chapters"]) == 1
    assert final["current_chapter"] == 2  # 1 章 total → 推进后 END
    assert final["chapters"][0]["status"] == "final"


async def test_revision_loop_on_human_feedback(monkeypatch):
    """人工修改意见触发回写:scene_writer 重写 → 润色 → 质检 → 再审查 → 定稿。"""
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    responses = [
        "```yaml\n世界观名称: 测试\n```",
        "- name: 林寒\n  role: 主角\n",
        "- chapter: 1\n  title: 雾起\n  estimated_words: 100\n",
        "初稿正文。", "初稿润色。", "[]",   # 第 1 轮
        "重写正文。", "重写润色。", "[]",   # 人工反馈后重写
    ]
    fake = FakeListChatModel(responses=responses)
    _patch_llms(monkeypatch, fake)

    from graph.builder import build_graph

    graph = build_graph()
    config = {"configurable": {"thread_id": "t-revise"}}

    visited = await _drive(graph, config, _initial_state())
    assert visited == EXPECTED_NODES

    # 修改意见 → 回写循环(重写→润色→质检,再次于 human_review 处打断)
    visited2 = await _drive(graph, config, Command(resume="结尾太仓促,补充决战场面"))
    assert visited2 == ["human_review", "scene_writer", "style_editor", "consistency_checker"]
    assert "human_review" in (await graph.aget_state(config)).next

    snap = await graph.aget_state(config)
    assert "重写" in (snap.values.get("current_draft") or {}).get("content", "")
    assert snap.values.get("revision_count") == 1

    # 最终 approve → 定稿
    tail = await _drive(graph, config, Command(resume="approve"))
    assert tail == ["human_review"]
    final = (await graph.aget_state(config)).values
    assert len(final["chapters"]) == 1
    assert "重写" in final["chapters"][0]["content"]
    assert final["revision_count"] == 0  # 定稿清零


async def test_automatic_revision_count_stops_at_limit(monkeypatch):
    """连续 high 问题只允许配置次数的自动重写,随后转人工审查。"""
    from graph import nodes

    class AlwaysHighChecker:
        async def check(self, **kwargs):
            return [{
                "type": "设定冲突",
                "description": "持续冲突",
                "chapter": 1,
                "severity": "high",
                "suggestion": "重写",
            }]

    monkeypatch.setattr(nodes, "ConsistencyCheckerAgent", AlwaysHighChecker)
    state = {
        "current_draft": {"chapter_number": 1, "content": "正文"},
        "current_phase": "consistency_check",
        "revision_count": 0,
        "max_revision_attempts": 2,
    }

    first = await nodes.consistency_checker_node(state)
    assert first["revision_count"] == 1
    assert first["current_phase"] == "writing"

    state.update(first)
    state["current_phase"] = "consistency_check"
    second = await nodes.consistency_checker_node(state)
    assert second["revision_count"] == 2
    assert second["current_phase"] == "writing"

    state.update(second)
    state["current_phase"] = "consistency_check"
    third = await nodes.consistency_checker_node(state)
    assert "revision_count" not in third
    assert "current_phase" not in third


async def test_chapter_vector_memory_is_written_only_after_approval(monkeypatch, fake_llm, store):
    """草稿不进入长期记忆,人工批准后以确定 ID 写入一次终稿。"""
    from graph import nodes
    from graph.builder import build_graph

    records: list[dict] = []

    class RecordingMemory:
        def __init__(self, novel_id: str):
            self.novel_id = novel_id

        def get_chapter_memory(self, chapter_number: int, k: int = 3):
            return []

        def store_content(self, content: str, metadata=None, content_id: str | None = None):
            records.append({
                "novel_id": self.novel_id,
                "content": content,
                "metadata": metadata or {},
                "content_id": content_id,
            })

    _patch_llms(monkeypatch, fake_llm)
    for module in [
        "agents.world_builder",
        "agents.character_designer",
        "agents.plot_planner",
        "agents.scene_writer",
    ]:
        monkeypatch.setattr(f"{module}.NovelMemory", RecordingMemory)
    monkeypatch.setattr(nodes, "NovelMemory", RecordingMemory, raising=False)
    monkeypatch.setattr(nodes, "_store", store)
    store.create_novel("memory-test", "雾中剑", total_chapters=1)

    state = _initial_state()
    state["novel_id"] = "memory-test"
    graph = build_graph()
    config = {"configurable": {"thread_id": "memory-test"}}

    await _drive(graph, config, state)
    assert not [r for r in records if r["metadata"].get("type") == "chapter"]

    await _drive(graph, config, Command(resume="approve"))
    chapter_records = [r for r in records if r["metadata"].get("type") == "chapter"]
    assert len(chapter_records) == 1
    assert chapter_records[0]["metadata"]["status"] == "final"
    assert chapter_records[0]["content_id"] == "memory-test:chapter:1"


async def test_sqlite_failure_prevents_chapter_finalization(monkeypatch, fake_llm):
    """权威 SQLite 写入失败时保留可恢复人工审查现场,稍后可重试定稿。"""
    from graph import nodes
    from graph.builder import build_graph

    class ToggleStore:
        def __init__(self):
            self.fail = True

        def save_chapter(self, **kwargs):
            if self.fail:
                raise OSError("disk full")

        def save_progress(self, **kwargs):
            if self.fail:
                raise AssertionError("save_progress 不应在章节写入失败后执行")

    failing_store = ToggleStore()

    _patch_llms(monkeypatch, fake_llm)
    monkeypatch.setattr(nodes, "_store", failing_store)
    monkeypatch.setattr(nodes, "NovelMemory", lambda novel_id: None)

    state = _initial_state()
    state["novel_id"] = "sqlite-failure"
    graph = build_graph()
    config = {"configurable": {"thread_id": "sqlite-failure"}}
    await _drive(graph, config, state)

    await _drive(graph, config, Command(resume="approve"))

    snapshot = await graph.aget_state(config)
    assert "human_review" in snapshot.next
    assert snapshot.values.get("chapters") == []

    failing_store.fail = False
    await _drive(graph, config, Command(resume="approve"))
    final = await graph.aget_state(config)
    assert final.next == ()
    assert len(final.values.get("chapters") or []) == 1
