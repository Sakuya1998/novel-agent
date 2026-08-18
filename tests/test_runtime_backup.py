"""运行时全量备份与校验测试。"""

import sqlite3
from pathlib import Path

import pytest

from config import Config
from memory.sql_store import NovelStore
from tools.runtime_backup import create_runtime_backup, restore_runtime_backup, verify_runtime_backup


def _runtime_config(tmp_path):
    cfg = Config(
        sqlite_db_path=str(tmp_path / "novels.db"),
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        model_secret_key_path=str(tmp_path / "model-settings.key"),
        runtime_backup_dir=str(tmp_path / "backups"),
    )
    NovelStore(cfg).create_novel("n1", "备份测试")
    conn = sqlite3.connect(cfg.checkpoint_db_path)
    try:
        conn.execute("CREATE TABLE checkpoints (id TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO checkpoints VALUES ('c1', '暂停现场')")
        conn.commit()
    finally:
        conn.close()
    cfg_path = Path(cfg.model_secret_key_path)
    cfg_path.write_bytes(b"test-secret-key")
    return cfg


def test_runtime_backup_roundtrip_and_retention(tmp_path):
    cfg = _runtime_config(tmp_path)
    first = create_runtime_backup(cfg, retention_count=2, confirm_stopped=True)
    second = create_runtime_backup(
        cfg,
        retention_count=2,
        password="correct horse",
        confirm_stopped=True,
    )

    assert first["manifest"]["schema_version"] == "novel-agent-runtime-backup-v1"
    assert verify_runtime_backup(first["path"])["encrypted"] is False
    assert verify_runtime_backup(second["path"], "correct horse")["encrypted"] is True
    assert len(list((tmp_path / "backups").iterdir())) == 2


def test_runtime_backup_rejects_wrong_password_and_tampering(tmp_path):
    cfg = _runtime_config(tmp_path)
    result = create_runtime_backup(cfg, password="secret", confirm_stopped=True)

    with pytest.raises(ValueError, match="备份密码错误|密码错误"):
        verify_runtime_backup(result["path"], "wrong")

    path = result["path"]
    payload = bytearray(Path(path).read_bytes())
    payload[-1] ^= 1
    Path(path).write_bytes(payload)
    with pytest.raises(ValueError):
        verify_runtime_backup(path, "secret")


def test_runtime_backup_restore_requires_confirmation_and_rolls_back_safely(tmp_path):
    cfg = _runtime_config(tmp_path)
    result = create_runtime_backup(cfg, password="restore-secret", confirm_stopped=True)

    with pytest.raises(ValueError, match="显式确认"):
        restore_runtime_backup(result["path"], cfg, password="restore-secret")

    NovelStore(cfg).save_chapter("n1", 1, "被修改", "修改后的正文", status="final")
    Path(cfg.model_secret_key_path).write_bytes(b"changed-secret")
    restored = restore_runtime_backup(result["path"], cfg, password="restore-secret", confirm=True)

    assert set(restored["restored"]) == {"novels.db", "checkpoints.db", "model-settings.key"}
    assert NovelStore(cfg).get_novel("n1")["title"] == "备份测试"
    assert Path(cfg.model_secret_key_path).read_bytes() == b"test-secret-key"


def test_runtime_backup_create_requires_stopped_confirmation(tmp_path):
    cfg = _runtime_config(tmp_path)
    with pytest.raises(ValueError, match="API 已停止"):
        create_runtime_backup(cfg)


def test_runtime_restore_removes_targets_absent_from_backup(tmp_path):
    cfg = Config(
        sqlite_db_path=str(tmp_path / "novels.db"),
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        model_secret_key_path=str(tmp_path / "model-settings.key"),
        runtime_backup_dir=str(tmp_path / "backups"),
    )
    NovelStore(cfg).create_novel("n1", "仅数据库备份")
    result = create_runtime_backup(cfg, confirm_stopped=True)

    Path(cfg.checkpoint_db_path).write_bytes(b"stale checkpoint")
    Path(cfg.model_secret_key_path).write_bytes(b"stale key")
    restored = restore_runtime_backup(result["path"], cfg, confirm=True)

    assert restored["restored"] == ["novels.db"]
    assert set(restored["removed"]) == {"checkpoints.db", "model-settings.key"}
    assert not Path(cfg.checkpoint_db_path).exists()
    assert not Path(cfg.model_secret_key_path).exists()
