"""pytest 共享夹具:确保项目根在 sys.path,并提供假 LLM。"""

import sys
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def fake_llm() -> FakeListChatModel:
    """按序返回固定回复的假 LLM(不依赖 API Key)。"""
    return FakeListChatModel(
        responses=[
            "```yaml\n世界观名称: 测试世界\n历史背景: 五百年前大雾封锁全城\n```",
            "- name: 林寒\n  role: 主角\n  personality:\n    core_desire: 找回记忆\n    core_fear: 真相\n",
            "- chapter: 1\n  title: 雾起\n  summary: 失忆剑客入城\n  conflict: 身份之谜\n  estimated_words: 100\n",
            "夜雾漫过城门,他握紧了剑。",
            "夜雾漫过城门,他握紧了剑。(润色)",
            "[]",
        ]
    )


@pytest.fixture
def store(tmp_path):
    """隔离的 SQLite 存储。"""
    from config import Config
    from memory.sql_store import NovelStore

    cfg = Config(sqlite_db_path=str(tmp_path / "test.db"), chroma_persist_dir=str(tmp_path / "chroma"))
    return NovelStore(cfg)
