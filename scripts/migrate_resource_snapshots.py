"""回填旧作品资源快照。

默认只做 dry-run；使用 ``--apply`` 前必须显式提供一个存在且可读的数据库备份。
回滚方式：停止服务后用备份文件覆盖 ``SQLITE_DB_PATH``，再重启服务。
"""

import argparse
import json
import sqlite3
from pathlib import Path

from novel_agent.config import Config
from novel_agent.models.workspace_resources import default_resource_snapshots


def inspect_database(path: Path) -> list[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(novels)")}
        required = {"id", "tenant_id", "style", "creative_brief_json", "content_type_snapshot_json",
                    "style_snapshot_json", "creative_template_snapshot_json", "quality_policy_snapshot_json"}
        if not required.issubset(columns):
            raise RuntimeError("数据库缺少作品或资源快照字段，请先升级应用")
        rows = conn.execute(
            "SELECT id, tenant_id, style, creative_brief_json, content_type_snapshot_json, "
            "style_snapshot_json, creative_template_snapshot_json, quality_policy_snapshot_json FROM novels"
        ).fetchall()
        result = []
        for row in rows:
            snapshot_fields = required - {"id", "tenant_id", "style", "creative_brief_json"}
            if all(row[key] not in (None, "", "{}") for key in snapshot_fields):
                continue
            try:
                brief = json.loads(row["creative_brief_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                brief = {}
            result.append({
                "id": row["id"],
                "tenant_id": row["tenant_id"],
                "style": row["style"],
                "snapshots": default_resource_snapshots(
                    row["tenant_id"], style_key=row["style"] or "", creative_brief=brief
                ),
            })
        return result
    finally:
        conn.close()


def apply_database(path: Path, rows: list[dict]) -> int:
    conn = sqlite3.connect(path)
    try:
        for item in rows:
            snapshots = item["snapshots"]
            conn.execute(
                "UPDATE novels SET content_type_snapshot_json=?, style_snapshot_json=?, "
                "creative_template_snapshot_json=?, quality_policy_snapshot_json=? WHERE id=?",
                tuple(json.dumps(snapshots[key], ensure_ascii=False, sort_keys=True) for key in (
                    "content_type_snapshot", "style_snapshot", "creative_template_snapshot", "quality_policy_snapshot"))
                + (item["id"],),
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=Config().sqlite_db_path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", help="--apply 时必须提供现有数据库备份路径")
    args = parser.parse_args()
    db = Path(args.db)
    rows = inspect_database(db)
    if not args.apply:
        print(json.dumps({"mode": "dry-run", "database": str(db), "would_update": len(rows)}, ensure_ascii=False))
        return 0
    backup = Path(args.backup) if args.backup else None
    if backup is None or not backup.is_file() or not backup.stat().st_size:
        raise SystemExit("--apply 需要提供存在且非空的 --backup 文件；失败时可用该文件回滚")
    applied = apply_database(db, rows)
    print(json.dumps({"mode": "apply", "updated": applied, "backup": str(backup),
                      "rollback": "停止服务后用 backup 覆盖数据库文件并重启"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
