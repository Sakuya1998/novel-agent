"""Post-migration verification for API readiness and resource snapshots."""
from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path


def check_url(url: str) -> dict[str, object]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return {"ok": 200 <= response.status < 300, "status": response.status}
    except (OSError, urllib.error.URLError) as reason:
        return {"ok": False, "error": str(reason)}


def check_snapshots(database: Path) -> dict[str, object]:
    if not database.is_file():
        return {"ok": False, "reason": "database_missing"}
    with sqlite3.connect(database) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(novels)")}
        expected = {"style_snapshot_json", "creative_template_snapshot_json", "quality_policy_snapshot_json"}
        missing = sorted(expected - columns)
        count = 0 if missing else conn.execute("SELECT COUNT(*) FROM novels").fetchone()[0]
    return {"ok": not missing, "novel_count": count, "missing_columns": missing}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--database", default="memory/novel_agent.db")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    result = {
        "healthz": check_url(f"{base}/healthz"),
        "readyz": check_url(f"{base}/readyz"),
        "snapshots": check_snapshots(Path(args.database)),
    }
    result["ok"] = all(item["ok"] for item in result.values())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
