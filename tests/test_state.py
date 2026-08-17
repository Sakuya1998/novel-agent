"""NovelState 初始化测试。"""

from config import Config
from graph.state import create_initial_state


def test_initial_state_uses_generation_config(tmp_path):
    cfg = Config(
        max_chapter_words=2345,
        max_revision_attempts=4,
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
    )

    state = create_initial_state(
        novel_id="novel_1",
        title="雾中剑",
        genre="武侠",
        inspiration="失忆剑客",
        total_chapters=3,
        style="gu_long",
        config=cfg,
    )

    assert state["max_chapter_words"] == 2345
    assert state["max_revision_attempts"] == 4
    assert state["revision_count"] == 0
    assert state["revision_notes"] == ""
    assert state["chapters"] == []
