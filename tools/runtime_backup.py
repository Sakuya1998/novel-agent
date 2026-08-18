"""创建和校验整个运行时的 SQLite/checkpoint/密钥快照。"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from config import Config
from tools.backup_security import decrypt_backup, encrypt_backup, is_encrypted_backup

RUNTIME_BACKUP_SCHEMA = "novel-agent-runtime-backup-v1"
_ALLOWED_FILES = {"novels.db", "checkpoints.db", "model-settings.key"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_snapshot(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(source)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
    finally:
        target_conn.close()
        source_conn.close()


def _payload_bytes(path: Path, password: str) -> bytes:
    raw = path.read_bytes()
    return decrypt_backup(raw, password) if is_encrypted_backup(raw) else raw


def _validate_members(archive: zipfile.ZipFile) -> None:
    names = set(archive.namelist())
    if "manifest.json" not in names:
        raise ValueError("运行时备份缺少 manifest.json")
    for name in names - {"manifest.json"}:
        pure = Path(name)
        if pure.is_absolute() or ".." in pure.parts or name != pure.as_posix() or name not in _ALLOWED_FILES:
            raise ValueError(f"运行时备份包含非法文件: {name}")


def create_runtime_backup(
    config: Config | None = None,
    *,
    output_dir: str | Path | None = None,
    password: str = "",
    retention_count: int | None = None,
    confirm_stopped: bool = False,
) -> dict:
    """在 API 停止后创建一致性快照，并按保留数量清理旧备份。"""
    if not confirm_stopped:
        raise ValueError("创建运行时备份必须显式确认 API 已停止")
    cfg = config or Config()
    destination = Path(output_dir or cfg.runtime_backup_dir)
    destination.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    backup_id = f"runtime-backup-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    extension = ".novel-runtime-backup.enc" if password else ".novel-runtime-backup.zip"
    final_path = destination / f"{backup_id}{extension}"

    with tempfile.TemporaryDirectory(prefix="runtime-backup-") as temp_dir:
        temp_root = Path(temp_dir)
        sources = {
            "novels.db": Path(cfg.sqlite_db_path),
            "checkpoints.db": Path(cfg.checkpoint_db_path),
            "model-settings.key": Path(cfg.model_secret_key_path),
        }
        snapshots: dict[str, Path] = {}
        for name, source in sources.items():
            if not source.is_file():
                continue
            snapshot = temp_root / name
            if source.suffix == ".db":
                _sqlite_snapshot(source, snapshot)
            else:
                shutil.copy2(source, snapshot)
            snapshots[name] = snapshot

        manifest = {
            "schema_version": RUNTIME_BACKUP_SCHEMA,
            "created_at": created_at,
            "encrypted": bool(password),
            "files": {name: {"size": path.stat().st_size, "sha256": _sha256(path)} for name, path in snapshots.items()},
        }
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for name, path in snapshots.items():
                archive.write(path, name)
        payload = encrypt_backup(archive_bytes.getvalue(), password) if password else archive_bytes.getvalue()

    temporary_path = final_path.with_suffix(final_path.suffix + ".tmp")
    temporary_path.write_bytes(payload)
    temporary_path.replace(final_path)

    keep = max(int(retention_count if retention_count is not None else cfg.backup_retention_count), 1)
    backups = sorted(
        [
            *destination.glob("runtime-backup-*.novel-runtime-backup.zip"),
            *destination.glob("runtime-backup-*.novel-runtime-backup.enc"),
        ],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for old in backups[keep:]:
        old.unlink(missing_ok=True)
    return {"path": str(final_path), "manifest": manifest, "retained": min(len(backups), keep)}


def verify_runtime_backup(path: str | Path, password: str = "") -> dict:
    """校验运行时备份的 ZIP 成员、manifest 和每个文件 checksum。"""
    archive_bytes = _payload_bytes(Path(path), password)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        _validate_members(archive)
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, json.JSONDecodeError) as exc:
            raise ValueError("运行时备份 manifest 无效") from exc
        if manifest.get("schema_version") != RUNTIME_BACKUP_SCHEMA:
            raise ValueError("不支持的运行时备份版本")
        files = manifest.get("files")
        if not isinstance(files, dict):
            raise ValueError("运行时备份文件清单无效")
        for name, metadata in files.items():
            if name not in _ALLOWED_FILES or not isinstance(metadata, dict):
                raise ValueError("运行时备份文件清单无效")
            payload = archive.read(name)
            digest = hashlib.sha256(payload).hexdigest()
            if digest != metadata.get("sha256") or len(payload) != int(metadata.get("size", -1)):
                raise ValueError(f"运行时备份校验失败: {name}")
    return manifest


def _validate_sqlite(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if result is None or str(result[0]).lower() != "ok":
        raise ValueError(f"SQLite 快照完整性检查失败: {path.name}")


def _replace_with_retry(source: Path, target: Path) -> None:
    last_error: PermissionError | None = None
    for _ in range(20):
        try:
            source.replace(target)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05)
    if last_error is not None:
        raise last_error


def restore_runtime_backup(
    path: str | Path,
    config: Config | None = None,
    *,
    password: str = "",
    confirm: bool = False,
) -> dict:
    """离线恢复运行时文件；必须显式确认，失败时回滚已替换文件。"""
    if not confirm:
        raise ValueError("恢复运行时备份必须显式确认，并确保 API 已停止")
    cfg = config or Config()
    manifest = verify_runtime_backup(path, password)
    archive_bytes = _payload_bytes(Path(path), password)
    targets = {
        "novels.db": Path(cfg.sqlite_db_path),
        "checkpoints.db": Path(cfg.checkpoint_db_path),
        "model-settings.key": Path(cfg.model_secret_key_path),
    }
    restored: list[str] = []
    with tempfile.TemporaryDirectory(prefix="runtime-restore-") as temp_dir:
        temp_root = Path(temp_dir)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            for name in manifest["files"]:
                staged_source = temp_root / name
                staged_source.write_bytes(archive.read(name))
                if name.endswith(".db"):
                    _validate_sqlite(staged_source)

        manifest_files = set(manifest["files"])
        staged_targets: dict[str, Path] = {}
        rollback_copies: dict[str, Path | None] = {}
        for name, target in targets.items():
            token = uuid4().hex
            if name in manifest_files:
                staged = target.with_name(f".{target.name}.{token}.restore")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(temp_root / name, staged)
                staged_targets[name] = staged
            if target.is_file():
                rollback = target.with_name(f".{target.name}.{token}.rollback")
                shutil.copy2(target, rollback)
                rollback_copies[name] = rollback
            else:
                rollback_copies[name] = None

        applied: list[str] = []
        removed: list[str] = []
        try:
            for name, target in targets.items():
                if name in manifest_files:
                    _replace_with_retry(staged_targets[name], target)
                    restored.append(name)
                    applied.append(name)
                elif target.is_file():
                    target.unlink()
                    removed.append(name)
                    applied.append(name)
        except Exception:
            for name in reversed(applied):
                rollback = rollback_copies[name]
                if rollback is None:
                    targets[name].unlink(missing_ok=True)
                else:
                    shutil.copy2(rollback, targets[name])
            raise
        finally:
            for staged in staged_targets.values():
                staged.unlink(missing_ok=True)
            for rollback in rollback_copies.values():
                if rollback is not None:
                    rollback.unlink(missing_ok=True)
    return {"manifest": manifest, "restored": restored, "removed": removed}
