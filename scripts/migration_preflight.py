"""Read-only checks before frontend cutover.

Usage: python -m scripts.migration_preflight --database memory/novel_agent.db --backup <backup>
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path


def check_database(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"ok": False, "reason": "database_missing", "path": str(path)}
    with sqlite3.connect(path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"novels", "chapters", "schema_migrations"}
        missing = sorted(required - tables)
        novel_count = conn.execute("SELECT COUNT(*) FROM novels").fetchone()[0] if "novels" in tables else 0
    return {"ok": not missing, "path": str(path), "missing_tables": missing, "novel_count": novel_count}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=os.getenv("NOVEL_DATABASE", "memory/novel_agent.db"))
    parser.add_argument("--backup", required=True)
    args = parser.parse_args()
    backup = Path(args.backup)
    result = {
        "ok": backup.is_file() and backup.stat().st_size > 0,
        "backup": {
            "path": str(backup),
            "exists": backup.is_file(),
            "bytes": backup.stat().st_size if backup.is_file() else 0,
        },
        "database": check_database(Path(args.database)),
        "resource_snapshot_migration": "run scripts.migrate_resource_snapshots --dry-run on a copy before --apply",
    }
    result["ok"] = bool(result["ok"] and result["database"]["ok"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
