"""CLI 新建、暂停和跨进程恢复测试。"""

from argparse import Namespace

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel


def _patch_llms(monkeypatch, fake_llm) -> None:
    for mod, attr in [
        ("agents.world_builder", "get_llm"),
        ("agents.character_designer", "get_llm"),
        ("agents.plot_planner", "get_analyzer_llm"),
        ("agents.scene_planner", "get_analyzer_llm"),
        ("agents.scene_writer", "get_llm"),
        ("agents.scene_rewriter", "get_llm"),
        ("agents.style_editor", "get_llm"),
        ("agents.consistency_checker", "get_analyzer_llm"),
    ]:
        monkeypatch.setattr(f"{mod}.{attr}", lambda **kw: fake_llm)


def _args(**overrides) -> Namespace:
    values = {
        "title": "雾中剑",
        "genre": "武侠",
        "inspiration": "失忆剑客",
        "chapters": 1,
        "style": "gu_long",
        "auto": False,
        "resume": None,
        "feedback": None,
        "scene_number": None,
        "version_number": None,
    }
    values.update(overrides)
    return Namespace(**values)


async def test_cli_can_resume_persisted_review(tmp_path, monkeypatch):
    from config import Config
    from main import run_novel_pipeline
    from memory.sql_store import NovelStore

    fake = FakeListChatModel(responses=[
        "```yaml\n世界观名称: 测试世界\n```",
        "- name: 林寒\n  role: 主角\n",
        "- chapter: 1\n  title: 雾起\n  estimated_words: 100\n",
        "- scene_number: 1\n  goal: 进入雾都\n  conflict: 城门盘查\n"
        "  turn: 发现追兵\n  location: 城门\n  characters: [林寒]\n"
        "  emotion: 紧张\n  estimated_words: 100\n",
        "初稿正文。",
        "润色正文。",
        "[]",
    ])
    _patch_llms(monkeypatch, fake)
    cfg = Config(
        sqlite_db_path=str(tmp_path / "novels.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
        model_secret_key_path=str(tmp_path / "model-settings.key"),
        openai_api_key="test-openai-key",
    )
    store = NovelStore(cfg)
    monkeypatch.setattr("graph.nodes._store", store)

    await run_novel_pipeline(_args(), config=cfg, store=store)
    novel_id = store.list_novels()[0]["id"]
    assert store.get_all_chapters(novel_id) == []

    await run_novel_pipeline(
        _args(
            title=None,
            inspiration=None,
            resume=novel_id,
            feedback="approve",
        ),
        config=cfg,
        store=store,
    )

    chapters = store.get_all_chapters(novel_id)
    assert len(chapters) == 1
    assert chapters[0]["status"] == "final"


async def test_cli_validates_models_before_creating_novel(tmp_path, monkeypatch):
    from config import Config
    from main import run_novel_pipeline
    from memory.sql_store import NovelStore
    from models.resolver import ModelConfigurationError

    cfg = Config(
        sqlite_db_path=str(tmp_path / "novels.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
        model_secret_key_path=str(tmp_path / "model-settings.key"),
        openai_api_key="",
        anthropic_api_key="",
    )
    store = NovelStore(cfg)

    def fail_validation(self):
        raise ModelConfigurationError("未配置创作模型")

    monkeypatch.setattr("main.ModelResolver.validate_runtime", fail_validation)
    with pytest.raises(ModelConfigurationError, match="未配置创作模型"):
        await run_novel_pipeline(_args(), config=cfg, store=store)
    assert store.list_novels() == []


def test_parse_args_accepts_resume_mode():
    from main import parse_args

    args = parse_args(["--resume", "novel_1", "--feedback", "approve"])
    assert args.resume == "novel_1"
    assert args.feedback == "approve"


def test_parse_args_accepts_scene_scoped_feedback():
    from main import parse_args

    args = parse_args([
        "--resume", "novel_1", "--feedback", "加强追逐", "--scene-number", "2",
    ])
    assert args.scene_number == 2
    assert args.feedback == "加强追逐"


def test_parse_args_rejects_scene_number_without_feedback():
    from main import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--resume", "novel_1", "--scene-number", "2"])


def test_parse_args_accepts_version_restore_without_feedback():
    from main import parse_args

    args = parse_args(["--resume", "novel_1", "--version-number", "3"])
    assert args.version_number == 3
    assert args.feedback == "restore"


def test_parse_args_rejects_out_of_range_chapters():
    from main import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--title", "书", "--inspiration", "灵感", "--chapters", "51"])
