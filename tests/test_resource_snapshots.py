from pathlib import Path

import pytest

from novel_agent.config import Config
from novel_agent.memory.sql_store import NovelStore


def make_store(tmp_path: Path) -> NovelStore:
    return NovelStore(Config(
        sqlite_db_path=str(tmp_path / "novels.db"),
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
    ))


def test_novel_freezes_published_resource_version(tmp_path: Path):
    store = make_store(tmp_path)
    store.create_resource(
        resource_id="style-1", tenant_id="tenant_local", kind="styles", key="custom",
        name="Custom", description="", payload={"syntax": ["短句"]}, created_by="user_local",
    )
    published = store.publish_resource("tenant_local", "styles", "style-1")
    novel = store.create_novel("novel-1", "作品", style_resource_id="style-1")
    assert novel["style_snapshot"]["version"] == published["version"]
    store.update_resource(
        tenant_id="tenant_local", kind="styles", resource_id="style-1", key="custom",
        name="Custom v2", description="", payload={"syntax": ["长句"]},
        expected_version=published["version"],
    )
    assert store.get_novel("novel-1")["style_snapshot"]["payload"]["syntax"] == ["短句"]


def test_new_novel_rejects_draft_or_foreign_resource(tmp_path: Path):
    store = make_store(tmp_path)
    store.create_resource(
        resource_id="style-1", tenant_id="tenant_local", kind="styles", key="draft",
        name="Draft", description="", payload={"syntax": ["短句"]}, created_by="user_local",
    )
    with pytest.raises(ValueError, match="已发布"):
        store.create_novel("novel-1", "作品", style_resource_id="style-1")


def test_legacy_novel_gets_default_snapshots(tmp_path: Path):
    store = make_store(tmp_path)
    with store._conn() as conn:
        conn.execute(
            "INSERT INTO novels (id, tenant_id, created_by, title, style, creative_brief_json) "
            "VALUES ('legacy', 'tenant_local', 'user_local', '旧作', 'jin_yong', '{}')"
        )
    novel = store.get_novel("legacy")
    assert novel["content_type_snapshot"]["id"] == "system_content_type_default"
    assert novel["style_snapshot"]["id"] == "system_style_jin_yong"
