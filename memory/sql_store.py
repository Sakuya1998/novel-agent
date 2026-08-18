"""基于 SQLite 的结构化存储(文档 5.3)。

NovelStore:小说元数据、章节内容、创作进度的持久化。
作为向量记忆的补充,支持精确查询与导出。
"""

import hashlib
import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from config import Config
from models.creative_brief import normalize_creative_brief
from security import LOCAL_TENANT_ID, LOCAL_USER_ID, Principal, current_principal, current_tenant_id

logger = logging.getLogger(__name__)


class NovelStore:
    """SQLite 持久化存储,管理小说/章节/进度三类记录。"""

    SCHEMA_COMPONENT = "novel_store"
    SCHEMA_VERSION = 3

    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.config.ensure_dirs()
        self.db_path = Path(self.config.sqlite_db_path)
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS novels (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'tenant_local',
                    created_by TEXT NOT NULL DEFAULT 'user_local',
                    title TEXT NOT NULL,
                    genre TEXT,
                    inspiration TEXT,
                    style TEXT,
                    total_chapters INTEGER DEFAULT 10,
                    planning_review_enabled INTEGER NOT NULL DEFAULT 0,
                    creative_brief_json TEXT NOT NULL DEFAULT '{}',
                    creative_brief_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS schema_migrations (
                    component TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    username TEXT NOT NULL UNIQUE,
                    email TEXT NOT NULL DEFAULT '' UNIQUE,
                    display_name TEXT NOT NULL DEFAULT '',
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'owner',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash);

                CREATE TABLE IF NOT EXISTS auth_rate_limits (
                    key_hash TEXT PRIMARY KEY,
                    window_started_at INTEGER NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    actor_user_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL DEFAULT '',
                    resource_id TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    ip_address TEXT NOT NULL DEFAULT '',
                    user_agent TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_time
                ON audit_logs(tenant_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_logs_action
                ON audit_logs(tenant_id, action, created_at DESC);

                CREATE TABLE IF NOT EXISTS creative_brief_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id TEXT NOT NULL,
                    version_number INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    brief_json TEXT NOT NULL,
                    change_summary TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL,
                    created_at TEXT,
                    FOREIGN KEY (novel_id) REFERENCES novels(id),
                    UNIQUE(novel_id, version_number)
                );

                CREATE INDEX IF NOT EXISTS idx_creative_brief_versions_lookup
                ON creative_brief_versions(novel_id, version_number);

                CREATE TABLE IF NOT EXISTS chapters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id TEXT,
                    chapter_number INTEGER,
                    title TEXT,
                    content TEXT,
                    summary TEXT,
                    scene_plan_json TEXT,
                    digest_json TEXT,
                    word_count INTEGER,
                    status TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY (novel_id) REFERENCES novels(id),
                    UNIQUE(novel_id, chapter_number)
                );

                CREATE TABLE IF NOT EXISTS progress (
                    novel_id TEXT PRIMARY KEY,
                    current_chapter INTEGER,
                    current_phase TEXT,
                    state_json TEXT,
                    updated_at TEXT,
                    FOREIGN KEY (novel_id) REFERENCES novels(id)
                );

                CREATE TABLE IF NOT EXISTS chapter_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id TEXT NOT NULL,
                    chapter_number INTEGER NOT NULL,
                    version_number INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    content TEXT NOT NULL,
                    summary TEXT,
                    scene_plan_json TEXT,
                    scene_drafts_json TEXT,
                    word_count INTEGER,
                    content_hash TEXT NOT NULL,
                    created_at TEXT,
                    FOREIGN KEY (novel_id) REFERENCES novels(id),
                    UNIQUE(novel_id, chapter_number, version_number),
                    UNIQUE(novel_id, chapter_number, source, content_hash)
                );

                CREATE TABLE IF NOT EXISTS chapter_candidates (
                    id TEXT PRIMARY KEY,
                    generation_id TEXT NOT NULL,
                    novel_id TEXT NOT NULL,
                    chapter_number INTEGER NOT NULL,
                    candidate_number INTEGER NOT NULL,
                    source_hash TEXT NOT NULL,
                    instruction TEXT,
                    title TEXT,
                    content TEXT NOT NULL,
                    summary TEXT,
                    scene_plan_json TEXT,
                    scene_drafts_json TEXT,
                    scores_json TEXT NOT NULL,
                    overall_score REAL NOT NULL,
                    evaluation_schema_version TEXT,
                    status TEXT NOT NULL DEFAULT 'available',
                    created_at TEXT,
                    selected_at TEXT,
                    FOREIGN KEY (novel_id) REFERENCES novels(id),
                    UNIQUE(generation_id, candidate_number)
                );

                CREATE INDEX IF NOT EXISTS idx_chapter_candidates_lookup
                ON chapter_candidates(novel_id, chapter_number, created_at);

                CREATE TABLE IF NOT EXISTS planning_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    chapter_number INTEGER NOT NULL DEFAULT 0,
                    version_number INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT,
                    FOREIGN KEY (novel_id) REFERENCES novels(id),
                    UNIQUE(novel_id, artifact_type, chapter_number, version_number),
                    UNIQUE(novel_id, artifact_type, chapter_number, source, content_hash)
                );

                CREATE INDEX IF NOT EXISTS idx_planning_versions_lookup
                ON planning_versions(novel_id, artifact_type, chapter_number, version_number);

                CREATE TABLE IF NOT EXISTS chapter_evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id TEXT NOT NULL,
                    chapter_number INTEGER NOT NULL,
                    version_number INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    evaluator_version TEXT NOT NULL,
                    rubric_version TEXT NOT NULL,
                    model_provider TEXT,
                    model_name TEXT,
                    deterministic_scores_json TEXT NOT NULL,
                    judge_scores_json TEXT NOT NULL,
                    overall_score REAL NOT NULL,
                    findings_json TEXT NOT NULL,
                    judge_error TEXT,
                    is_baseline INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT,
                    FOREIGN KEY (novel_id) REFERENCES novels(id)
                );

                CREATE INDEX IF NOT EXISTS idx_chapter_evaluations_lookup
                ON chapter_evaluations(novel_id, chapter_number, version_number, created_at);

                CREATE TABLE IF NOT EXISTS evaluation_benchmark_runs (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'tenant_local',
                    suite_version TEXT NOT NULL,
                    evaluator_version TEXT NOT NULL,
                    rubric_version TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    include_judge INTEGER NOT NULL DEFAULT 0,
                    model_provider TEXT,
                    model_name TEXT,
                    baseline_run_id TEXT,
                    gate_threshold REAL NOT NULL,
                    regression_threshold REAL NOT NULL,
                    overall_score REAL NOT NULL,
                    status TEXT NOT NULL,
                    judge_error TEXT,
                    report_json TEXT NOT NULL,
                    created_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_evaluation_benchmark_runs_lookup
                ON evaluation_benchmark_runs(id, created_at);

                CREATE TABLE IF NOT EXISTS book_audits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id TEXT NOT NULL,
                    manuscript_hash TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    rubric_version TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    created_at TEXT,
                    FOREIGN KEY (novel_id) REFERENCES novels(id),
                    UNIQUE(novel_id, manuscript_hash, schema_version, rubric_version)
                );

                CREATE INDEX IF NOT EXISTS idx_book_audits_lookup
                ON book_audits(novel_id, id);

                CREATE TABLE IF NOT EXISTS memory_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT,
                    FOREIGN KEY (novel_id) REFERENCES novels(id),
                    UNIQUE(novel_id, schema_version, content_hash)
                );

                CREATE INDEX IF NOT EXISTS idx_memory_snapshots_lookup
                ON memory_snapshots(novel_id, id);

                CREATE TABLE IF NOT EXISTS memory_quality_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL DEFAULT 'tenant_local',
                    mode TEXT NOT NULL,
                    index_hash TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    created_at TEXT,
                    FOREIGN KEY (novel_id) REFERENCES novels(id)
                );

                CREATE INDEX IF NOT EXISTS idx_memory_quality_runs_lookup
                ON memory_quality_runs(novel_id, id);

                CREATE TABLE IF NOT EXISTS run_jobs (
                    id TEXT PRIMARY KEY,
                    novel_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    current_node TEXT,
                    error TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    heartbeat_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY (novel_id) REFERENCES novels(id)
                );

                CREATE TABLE IF NOT EXISTS run_job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT,
                    FOREIGN KEY (job_id) REFERENCES run_jobs(id),
                    UNIQUE(job_id, sequence)
                );

                CREATE INDEX IF NOT EXISTS idx_run_jobs_novel
                ON run_jobs(novel_id, created_at);

                CREATE UNIQUE INDEX IF NOT EXISTS idx_run_jobs_one_active
                ON run_jobs(novel_id) WHERE status IN ('queued', 'running');

                CREATE INDEX IF NOT EXISTS idx_run_job_events_lookup
                ON run_job_events(job_id, sequence);

                CREATE TABLE IF NOT EXISTS transfer_jobs (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    novel_id TEXT,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    input_path TEXT,
                    output_path TEXT,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_transfer_jobs_tenant
                ON transfer_jobs(tenant_id, created_at);
                """
            )
            chapter_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(chapters)").fetchall()
            }
            if "scene_plan_json" not in chapter_columns:
                conn.execute("ALTER TABLE chapters ADD COLUMN scene_plan_json TEXT")
            if "digest_json" not in chapter_columns:
                conn.execute("ALTER TABLE chapters ADD COLUMN digest_json TEXT")
            novel_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(novels)").fetchall()
            }
            if "planning_review_enabled" not in novel_columns:
                conn.execute(
                    "ALTER TABLE novels ADD COLUMN planning_review_enabled INTEGER NOT NULL DEFAULT 0"
                )
            if "creative_brief_json" not in novel_columns:
                conn.execute(
                    "ALTER TABLE novels ADD COLUMN creative_brief_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "creative_brief_version" not in novel_columns:
                conn.execute(
                    "ALTER TABLE novels ADD COLUMN creative_brief_version INTEGER NOT NULL DEFAULT 1"
                )
            if "tenant_id" not in novel_columns:
                conn.execute(
                    "ALTER TABLE novels ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'tenant_local'"
                )
            if "created_by" not in novel_columns:
                conn.execute(
                    "ALTER TABLE novels ADD COLUMN created_by TEXT NOT NULL DEFAULT 'user_local'"
                )
            now = datetime.now(UTC).isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO tenants (id, name, created_by, created_at) VALUES (?, ?, ?, ?)",
                (LOCAL_TENANT_ID, "本地工作区", LOCAL_USER_ID, now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO users ("
                "id, tenant_id, username, email, display_name, password_hash, role, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (LOCAL_USER_ID, LOCAL_TENANT_ID, "local", "local@localhost", "本地用户", "", "owner", now),
            )
            conn.execute(
                "UPDATE novels SET tenant_id = ?, created_by = ? WHERE tenant_id IS NULL OR tenant_id = ''",
                (LOCAL_TENANT_ID, LOCAL_USER_ID),
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_novels_tenant ON novels(tenant_id, created_at)"
            )
            run_job_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(run_jobs)").fetchall()
            }
            for name, definition in (
                ("lease_owner", "TEXT"),
                ("lease_expires_at", "TEXT"),
                ("heartbeat_at", "TEXT"),
                ("attempt_count", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in run_job_columns:
                    conn.execute(f"ALTER TABLE run_jobs ADD COLUMN {name} {definition}")
            benchmark_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(evaluation_benchmark_runs)").fetchall()
            }
            if "tenant_id" not in benchmark_columns:
                conn.execute(
                    "ALTER TABLE evaluation_benchmark_runs "
                    "ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'tenant_local'"
                )
            conn.execute(
                "INSERT INTO schema_migrations (component, version, applied_at) VALUES (?, ?, ?) "
                "ON CONFLICT(component) DO UPDATE SET version = excluded.version, "
                "applied_at = excluded.applied_at",
                (self.SCHEMA_COMPONENT, self.SCHEMA_VERSION, datetime.now(UTC).isoformat()),
            )

    def get_schema_versions(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute("SELECT component, version FROM schema_migrations").fetchall()
        return {str(row["component"]): int(row["version"]) for row in rows}

    # ------------------------------------------------------------------
    # 小说
    # ------------------------------------------------------------------
    def create_novel(
        self,
        novel_id: str,
        title: str,
        genre: str = "",
        style: str = "",
        total_chapters: int = 10,
        inspiration: str = "",
        planning_review_enabled: bool = False,
        creative_brief: dict | None = None,
        tenant_id: str | None = None,
        created_by: str | None = None,
    ) -> dict:
        now = datetime.now().isoformat()
        normalized_brief = normalize_creative_brief(creative_brief)
        brief_json = json.dumps(normalized_brief, ensure_ascii=False, sort_keys=True)
        content_hash = hashlib.sha256(brief_json.encode("utf-8")).hexdigest()
        principal = current_principal()
        tenant = str(tenant_id or (principal.tenant_id if principal else None) or LOCAL_TENANT_ID)
        creator = str(created_by or (principal.user_id if principal else None) or LOCAL_USER_ID)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO novels (id, tenant_id, created_by, title, genre, inspiration, style, total_chapters, "
                "planning_review_enabled, creative_brief_json, creative_brief_version, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    novel_id, tenant, creator, title, genre, inspiration, style, total_chapters,
                    int(planning_review_enabled),
                    brief_json,
                    1,
                    now,
                    now,
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO creative_brief_versions "
                "(novel_id, version_number, source, brief_json, change_summary, content_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (novel_id, 1, "created", brief_json, "初始创作约束", content_hash, now),
            )
        return {"id": novel_id, "title": title, "genre": genre, "inspiration": inspiration,
                "style": style, "total_chapters": total_chapters,
                "planning_review_enabled": planning_review_enabled,
                "creative_brief_version": 1,
                "creative_brief": normalized_brief,
                "created_at": now, "updated_at": now}

    def get_novel(self, novel_id: str, tenant_id: str | None = None) -> dict | None:
        tenant = tenant_id if tenant_id is not None else current_tenant_id()
        with self._conn() as conn:
            query = "SELECT * FROM novels WHERE id = ?"
            params: list[object] = [novel_id]
            if tenant:
                query += " AND tenant_id = ?"
                params.append(tenant)
            row = conn.execute(query, params).fetchone()
        return self._novel_dict(row) if row else None

    def list_novels(self, tenant_id: str | None = None) -> list[dict]:
        tenant = tenant_id if tenant_id is not None else current_tenant_id()
        with self._conn() as conn:
            query = "SELECT * FROM novels"
            params: list[object] = []
            if tenant:
                query += " WHERE tenant_id = ?"
                params.append(tenant)
            rows = conn.execute(query + " ORDER BY created_at DESC", params).fetchall()
        return [self._novel_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 用户、租户与会话
    # ------------------------------------------------------------------
    def create_user_with_tenant(
        self,
        *,
        user_id: str,
        tenant_id: str,
        username: str,
        email: str,
        display_name: str,
        password_hash: str,
        tenant_name: str,
    ) -> dict:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO tenants (id, name, created_by, created_at) VALUES (?, ?, ?, ?)",
                (tenant_id, tenant_name, user_id, now),
            )
            conn.execute(
                "INSERT INTO users (id, tenant_id, username, email, display_name, password_hash, role, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'owner', ?)",
                (user_id, tenant_id, username, email, display_name, password_hash, now),
            )
            row = conn.execute(
                "SELECT u.*, t.name AS tenant_name FROM users u "
                "JOIN tenants t ON t.id = u.tenant_id WHERE u.id = ?",
                (user_id,),
            ).fetchone()
        return self._user_dict(row)

    def get_user_by_login(self, identifier: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT u.*, t.name AS tenant_name FROM users u "
                "JOIN tenants t ON t.id = u.tenant_id "
                "WHERE lower(u.username) = lower(?) OR "
                "(u.email <> '' AND lower(u.email) = lower(?))",
                (identifier, identifier),
            ).fetchone()
        return self._user_dict(row, include_secret=True) if row else None

    def create_user_in_tenant(
        self,
        *,
        user_id: str,
        tenant_id: str,
        username: str,
        email: str,
        display_name: str,
        password_hash: str,
        role: str,
    ) -> dict:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO users (id, tenant_id, username, email, display_name, password_hash, role, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, tenant_id, username, email, display_name, password_hash, role, now),
            )
            row = conn.execute(
                "SELECT u.*, t.name AS tenant_name FROM users u "
                "JOIN tenants t ON t.id = u.tenant_id WHERE u.id = ?",
                (user_id,),
            ).fetchone()
        return self._user_dict(row)

    def get_user(self, user_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT u.*, t.name AS tenant_name FROM users u "
                "JOIN tenants t ON t.id = u.tenant_id WHERE u.id = ?",
                (user_id,),
            ).fetchone()
        return self._user_dict(row) if row else None

    def list_users(self, tenant_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT u.*, t.name AS tenant_name FROM users u "
                "JOIN tenants t ON t.id = u.tenant_id "
                "WHERE u.tenant_id = ? ORDER BY u.created_at, u.username",
                (tenant_id,),
            ).fetchall()
        return [self._user_dict(row) for row in rows]

    def create_session(
        self,
        session_id: str,
        user_id: str,
        token_hash_value: str,
        expires_at: str,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sessions (id, user_id, token_hash, expires_at, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, user_id, token_hash_value, expires_at, datetime.now(UTC).isoformat()),
            )

    def get_session_principal(self, token_hash_value: str) -> Principal | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT u.id AS user_id, u.tenant_id, u.username, u.role, u.display_name, s.expires_at "
                "FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = ? AND s.revoked_at IS NULL",
                (token_hash_value,),
            ).fetchone()
        if row is None:
            return None
        try:
            expires = datetime.fromisoformat(str(row["expires_at"]))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires <= datetime.now(UTC):
                return None
        except ValueError:
            return None
        return Principal(
            user_id=str(row["user_id"]),
            tenant_id=str(row["tenant_id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            display_name=str(row["display_name"] or ""),
        )

    def revoke_session(self, token_hash_value: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (datetime.now(UTC).isoformat(), token_hash_value),
            )
        return cursor.rowcount > 0

    def consume_auth_rate_limit(
        self,
        key_hash: str,
        *,
        window_seconds: int,
        max_attempts: int,
        now_epoch: int | None = None,
    ) -> int | None:
        """在 SQLite 中原子消费一次认证额度，返回剩余等待秒数或 None。"""
        now = int(now_epoch if now_epoch is not None else datetime.now(UTC).timestamp())
        window = max(int(window_seconds), 1)
        maximum = max(int(max_attempts), 1)
        key = str(key_hash).strip()
        if not key:
            raise ValueError("认证限流键不能为空")
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT window_started_at, attempt_count FROM auth_rate_limits WHERE key_hash = ?",
                (key,),
            ).fetchone()
            if row is None or now - int(row["window_started_at"]) >= window:
                conn.execute(
                    "INSERT INTO auth_rate_limits (key_hash, window_started_at, attempt_count, updated_at) "
                    "VALUES (?, ?, 1, ?) "
                    "ON CONFLICT(key_hash) DO UPDATE SET window_started_at = excluded.window_started_at, "
                    "attempt_count = excluded.attempt_count, updated_at = excluded.updated_at",
                    (key, now, datetime.now(UTC).isoformat()),
                )
                retry_after = None
            elif int(row["attempt_count"]) >= maximum:
                retry_after = max(1, window - (now - int(row["window_started_at"])))
            else:
                conn.execute(
                    "UPDATE auth_rate_limits SET attempt_count = attempt_count + 1, updated_at = ? "
                    "WHERE key_hash = ?",
                    (datetime.now(UTC).isoformat(), key),
                )
                retry_after = None
            conn.execute(
                "DELETE FROM auth_rate_limits WHERE updated_at < ?",
                ((datetime.now(UTC) - timedelta(seconds=window * 2)).isoformat(),),
            )
        return retry_after

    def clear_auth_rate_limits(self) -> None:
        """清理认证限流记录，供测试或运维切换窗口使用。"""
        with self._conn() as conn:
            conn.execute("DELETE FROM auth_rate_limits")

    def get_monitoring_summary(self, tenant_id: str) -> dict:
        """返回当前租户的后台任务和模型调用聚合，不包含正文或密钥。"""
        tenant = str(tenant_id)
        with self._conn() as conn:
            run_rows = conn.execute(
                """
                SELECT r.status, COUNT(*) AS count
                FROM run_jobs r JOIN novels n ON n.id = r.novel_id
                WHERE n.tenant_id = ?
                GROUP BY r.status
                """,
                (tenant,),
            ).fetchall()
            transfer_rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM transfer_jobs WHERE tenant_id = ? GROUP BY status",
                (tenant,),
            ).fetchall()
            try:
                model = conn.execute(
                    """
                    SELECT COUNT(*) AS total,
                           COALESCE(SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END), 0) AS failed,
                           COALESCE(SUM(duration_ms), 0) AS duration_ms,
                           COALESCE(SUM(input_tokens), 0) AS input_tokens,
                           COALESCE(SUM(output_tokens), 0) AS output_tokens
                    FROM model_call_metrics WHERE tenant_id = ?
                    """,
                    (tenant,),
                ).fetchone()
            except sqlite3.OperationalError:
                model = None
        return {
            "run_jobs": {str(row["status"]): int(row["count"]) for row in run_rows},
            "transfer_jobs": {str(row["status"]): int(row["count"]) for row in transfer_rows},
            "model_calls": {
                "total": int(model["total"] if model else 0),
                "failed": int(model["failed"] if model else 0),
                "duration_ms": int(model["duration_ms"] if model else 0),
                "input_tokens": int(model["input_tokens"] if model else 0),
                "output_tokens": int(model["output_tokens"] if model else 0),
            },
        }

    def append_audit_log(
        self,
        action: str,
        *,
        tenant_id: str | None = None,
        actor_user_id: str | None = None,
        resource_type: str = "",
        resource_id: str = "",
        metadata: dict | None = None,
        ip_address: str = "",
        user_agent: str = "",
    ) -> dict:
        """写入一条不含敏感正文的租户审计记录。"""
        principal = current_principal()
        tenant = tenant_id or (principal.tenant_id if principal else LOCAL_TENANT_ID)
        actor = actor_user_id or (principal.user_id if principal else LOCAL_USER_ID)
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_logs (
                    tenant_id, actor_user_id, action, resource_type, resource_id,
                    metadata_json, ip_address, user_agent, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(tenant),
                    str(actor),
                    str(action)[:120],
                    str(resource_type)[:80],
                    str(resource_id)[:200],
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    str(ip_address)[:120],
                    str(user_agent)[:500],
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM audit_logs WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._audit_log_dict(row)

    def list_audit_logs(
        self,
        tenant_id: str | None = None,
        *,
        limit: int = 100,
        action: str = "",
    ) -> list[dict]:
        principal = current_principal()
        tenant = tenant_id or (principal.tenant_id if principal else LOCAL_TENANT_ID)
        safe_limit = max(1, min(int(limit), 500))
        clauses = ["tenant_id = ?"]
        params: list[object] = [str(tenant)]
        if action.strip():
            clauses.append("action = ?")
            params.append(action.strip()[:120])
        params.append(safe_limit)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM audit_logs WHERE {' AND '.join(clauses)} "
                "ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._audit_log_dict(row) for row in rows]

    @staticmethod
    def _audit_log_dict(row: sqlite3.Row) -> dict:
        record = dict(row)
        try:
            metadata = json.loads(record.pop("metadata_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        record["metadata"] = metadata if isinstance(metadata, dict) else {}
        return record

    def update_user_role(self, user_id: str, tenant_id: str, role: str) -> dict | None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET role = ? WHERE id = ? AND tenant_id = ?",
                (role, user_id, tenant_id),
            )
            row = conn.execute(
                "SELECT u.*, t.name AS tenant_name FROM users u "
                "JOIN tenants t ON t.id = u.tenant_id WHERE u.id = ?",
                (user_id,),
            ).fetchone()
        return self._user_dict(row) if row else None

    @staticmethod
    def _user_dict(row: sqlite3.Row, *, include_secret: bool = False) -> dict:
        user = dict(row)
        if not include_secret:
            user.pop("password_hash", None)
        return user

    def update_creative_brief(
        self,
        novel_id: str,
        creative_brief: dict | None,
        *,
        change_summary: str = "",
    ) -> dict | None:
        """Update the brief atomically and append an idempotent version snapshot."""
        normalized = normalize_creative_brief(creative_brief)
        brief_json = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        content_hash = hashlib.sha256(brief_json.encode("utf-8")).hexdigest()
        now = datetime.now().isoformat()
        summary = " ".join(str(change_summary).strip().split())[:500]
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM novels WHERE id = ?",
                (novel_id,),
            ).fetchone()
            if row is None:
                return None
            raw_current = row["creative_brief_json"] or "{}"
            try:
                current_brief = json.loads(raw_current)
            except (TypeError, json.JSONDecodeError):
                current_brief = {}
            current_json = json.dumps(
                normalize_creative_brief(current_brief),
                ensure_ascii=False,
                sort_keys=True,
            )
            if current_json == brief_json:
                version_number = max(int(row["creative_brief_version"] or 1), 1)
                conn.execute(
                    "INSERT OR IGNORE INTO creative_brief_versions "
                    "(novel_id, version_number, source, brief_json, change_summary, content_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (novel_id, version_number, "legacy", brief_json, summary, content_hash, now),
                )
            else:
                latest = conn.execute(
                    "SELECT MAX(version_number) AS version_number "
                    "FROM creative_brief_versions WHERE novel_id = ?",
                    (novel_id,),
                ).fetchone()
                latest_number = int(latest["version_number"] or 0)
                version_number = max(latest_number + 1, int(row["creative_brief_version"] or 1))
                conn.execute(
                    "INSERT INTO creative_brief_versions "
                    "(novel_id, version_number, source, brief_json, change_summary, content_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (novel_id, version_number, "manual", brief_json, summary, content_hash, now),
                )
            conn.execute(
                "UPDATE novels SET creative_brief_json = ?, creative_brief_version = ?, updated_at = ? "
                "WHERE id = ?",
                (brief_json, version_number, now, novel_id),
            )
            updated = conn.execute(
                "SELECT * FROM novels WHERE id = ?",
                (novel_id,),
            ).fetchone()
        return self._novel_dict(updated)

    def list_creative_brief_versions(self, novel_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM creative_brief_versions "
                "WHERE novel_id = ? ORDER BY version_number DESC",
                (novel_id,),
            ).fetchall()
        return [self._creative_brief_version_dict(row) for row in rows]

    @staticmethod
    def _creative_brief_version_dict(row: sqlite3.Row) -> dict:
        version = dict(row)
        raw_brief = version.pop("brief_json", "{}") or "{}"
        try:
            brief = json.loads(raw_brief)
        except (TypeError, json.JSONDecodeError):
            brief = {}
        version["creative_brief"] = normalize_creative_brief(brief)
        return version

    @staticmethod
    def _novel_dict(row: sqlite3.Row) -> dict:
        novel = dict(row)
        novel["planning_review_enabled"] = bool(novel.get("planning_review_enabled"))
        novel["creative_brief_version"] = max(int(novel.get("creative_brief_version") or 1), 1)
        raw_brief = novel.pop("creative_brief_json", "{}") or "{}"
        try:
            creative_brief = json.loads(raw_brief)
        except (TypeError, json.JSONDecodeError):
            creative_brief = {}
        novel["creative_brief"] = normalize_creative_brief(creative_brief)
        return novel

    def delete_novel(self, novel_id: str) -> bool:
        """删除作品及其章节、进度记录;返回是否确实删除了一部作品。"""
        with self._conn() as conn:
            exists = conn.execute("SELECT 1 FROM novels WHERE id = ?", (novel_id,)).fetchone()
            if not exists:
                return False
            conn.execute("DELETE FROM chapters WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM book_audits WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM memory_snapshots WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM chapter_evaluations WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM chapter_candidates WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM chapter_versions WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM planning_versions WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM creative_brief_versions WHERE novel_id = ?", (novel_id,))
            conn.execute(
                "DELETE FROM run_job_events WHERE job_id IN "
                "(SELECT id FROM run_jobs WHERE novel_id = ?)",
                (novel_id,),
            )
            conn.execute("DELETE FROM run_jobs WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM progress WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
            return True

    # ------------------------------------------------------------------
    # 章节
    # ------------------------------------------------------------------
    def save_chapter(
        self,
        novel_id: str,
        chapter_number: int,
        title: str,
        content: str,
        summary: str = "",
        status: str = "draft",
        scene_plan: list[dict] | None = None,
        digest: dict | None = None,
    ) -> int:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO chapters (novel_id, chapter_number, title, content, summary,
                                      scene_plan_json, digest_json, word_count, status,
                                      created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(novel_id, chapter_number) DO UPDATE SET
                    title=excluded.title, content=excluded.content, summary=excluded.summary,
                    scene_plan_json=excluded.scene_plan_json, digest_json=excluded.digest_json,
                    word_count=excluded.word_count, status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    novel_id,
                    chapter_number,
                    title,
                    content,
                    summary,
                    json.dumps(scene_plan or [], ensure_ascii=False),
                    json.dumps(digest or {}, ensure_ascii=False),
                    len(content),
                    status,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM chapters WHERE novel_id = ? AND chapter_number = ?",
                (novel_id, chapter_number),
            ).fetchone()
            return int(row["id"]) if row else 0

    def get_chapter(self, novel_id: str, chapter_number: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM chapters WHERE novel_id = ? AND chapter_number = ?",
                (novel_id, chapter_number),
            ).fetchone()
        return self._chapter_dict(row) if row else None

    def get_all_chapters(self, novel_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM chapters WHERE novel_id = ? ORDER BY chapter_number",
                (novel_id,),
            ).fetchall()
        return [self._chapter_dict(row) for row in rows]

    @staticmethod
    def _chapter_dict(row: sqlite3.Row) -> dict:
        chapter = dict(row)
        raw_scene_plan = chapter.pop("scene_plan_json") or "[]"
        try:
            scene_plan = json.loads(raw_scene_plan)
        except (TypeError, json.JSONDecodeError):
            logger.warning(
                "章节场景计划 JSON 损坏,已降级为空列表(novel_id=%s, chapter=%s)",
                chapter.get("novel_id", ""),
                chapter.get("chapter_number", ""),
            )
            scene_plan = []
        if not isinstance(scene_plan, list):
            logger.warning(
                "章节场景计划不是列表,已降级为空列表(novel_id=%s, chapter=%s)",
                chapter.get("novel_id", ""),
                chapter.get("chapter_number", ""),
            )
            scene_plan = []
        chapter["scene_plan"] = scene_plan
        raw_digest = chapter.pop("digest_json") or "{}"
        try:
            digest = json.loads(raw_digest)
        except (TypeError, json.JSONDecodeError):
            logger.warning(
                "章节提炼 JSON 损坏,已降级为空对象(novel_id=%s, chapter=%s)",
                chapter.get("novel_id", ""),
                chapter.get("chapter_number", ""),
            )
            digest = {}
        if not isinstance(digest, dict):
            logger.warning(
                "章节提炼结果不是对象,已降级为空对象(novel_id=%s, chapter=%s)",
                chapter.get("novel_id", ""),
                chapter.get("chapter_number", ""),
            )
            digest = {}
        chapter["digest"] = digest
        for field in (
            "events",
            "characters",
            "locations",
            "emotion",
            "extracted_facts",
            "digest_version",
            "digest_content_hash",
        ):
            if field in digest:
                chapter[field] = digest[field]
        return chapter

    # ------------------------------------------------------------------
    # 章节版本
    # ------------------------------------------------------------------
    def save_chapter_version(
        self,
        novel_id: str,
        chapter_number: int,
        *,
        source: str,
        content: str,
        summary: str = "",
        scene_plan: list[dict] | None = None,
        scene_drafts: list[dict] | None = None,
    ) -> dict:
        """幂等保存章节快照，相同来源与正文不会重复生成版本。"""
        now = datetime.now().isoformat()
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT * FROM chapter_versions
                WHERE novel_id = ? AND chapter_number = ? AND source = ? AND content_hash = ?
                """,
                (novel_id, chapter_number, source, content_hash),
            ).fetchone()
            if existing:
                return self._version_dict(existing)

            row = conn.execute(
                """
                SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version
                FROM chapter_versions WHERE novel_id = ? AND chapter_number = ?
                """,
                (novel_id, chapter_number),
            ).fetchone()
            version_number = int(row["next_version"])
            conn.execute(
                """
                INSERT INTO chapter_versions (
                    novel_id, chapter_number, version_number, source, content, summary,
                    scene_plan_json, scene_drafts_json, word_count, content_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    chapter_number,
                    version_number,
                    source,
                    content,
                    summary,
                    json.dumps(scene_plan or [], ensure_ascii=False),
                    json.dumps(scene_drafts or [], ensure_ascii=False),
                    len(content),
                    content_hash,
                    now,
                ),
            )
            saved = conn.execute(
                """
                SELECT * FROM chapter_versions
                WHERE novel_id = ? AND chapter_number = ? AND version_number = ?
                """,
                (novel_id, chapter_number, version_number),
            ).fetchone()
            return self._version_dict(saved)

    def list_chapter_versions(self, novel_id: str, chapter_number: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM chapter_versions
                WHERE novel_id = ? AND chapter_number = ? ORDER BY version_number
                """,
                (novel_id, chapter_number),
            ).fetchall()
        versions = [self._version_dict(row) for row in rows]
        for version in versions:
            version["preview"] = str(version["content"])[:120]
            version.pop("content", None)
            version.pop("content_hash", None)
        return versions

    def get_chapter_version(
        self,
        novel_id: str,
        chapter_number: int,
        version_number: int,
    ) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM chapter_versions
                WHERE novel_id = ? AND chapter_number = ? AND version_number = ?
                """,
                (novel_id, chapter_number, version_number),
            ).fetchone()
        return self._version_dict(row) if row else None

    @staticmethod
    def _version_dict(row: sqlite3.Row) -> dict:
        version = dict(row)
        for raw_key, target_key in (
            ("scene_plan_json", "scene_plan"),
            ("scene_drafts_json", "scene_drafts"),
        ):
            raw_value = version.pop(raw_key) or "[]"
            try:
                parsed = json.loads(raw_value)
            except (TypeError, json.JSONDecodeError):
                parsed = []
            version[target_key] = parsed if isinstance(parsed, list) else []
        return version

    # ------------------------------------------------------------------
    # 章节候选稿
    # ------------------------------------------------------------------
    def save_chapter_candidate(
        self,
        novel_id: str,
        chapter_number: int,
        *,
        generation_id: str,
        candidate_number: int,
        source_hash: str,
        instruction: str,
        title: str,
        content: str,
        summary: str = "",
        scene_plan: list[dict] | None = None,
        scene_drafts: list[dict] | None = None,
        scores: dict[str, float] | None = None,
        overall_score: float = 0.0,
        evaluation_schema_version: str = "",
    ) -> dict:
        """Persist one candidate, idempotently within a generation."""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            existing = conn.execute(
                """
                SELECT * FROM chapter_candidates
                WHERE generation_id = ? AND candidate_number = ?
                """,
                (generation_id, candidate_number),
            ).fetchone()
            if existing:
                return self._candidate_dict(existing)
            candidate_id = f"candidate_{uuid4().hex[:16]}"
            conn.execute(
                """
                INSERT INTO chapter_candidates (
                    id, generation_id, novel_id, chapter_number, candidate_number,
                    source_hash, instruction, title, content, summary,
                    scene_plan_json, scene_drafts_json, scores_json, overall_score,
                    evaluation_schema_version, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'available', ?)
                """,
                (
                    candidate_id,
                    generation_id,
                    novel_id,
                    int(chapter_number),
                    int(candidate_number),
                    source_hash,
                    instruction,
                    title,
                    content,
                    summary,
                    json.dumps(scene_plan or [], ensure_ascii=False),
                    json.dumps(scene_drafts or [], ensure_ascii=False),
                    json.dumps(scores or {}, ensure_ascii=False),
                    float(overall_score),
                    evaluation_schema_version,
                    now,
                ),
            )
            saved = conn.execute(
                "SELECT * FROM chapter_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
        return self._candidate_dict(saved)

    def list_chapter_candidates(
        self,
        novel_id: str,
        chapter_number: int,
    ) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM chapter_candidates
                WHERE novel_id = ? AND chapter_number = ?
                ORDER BY created_at DESC, candidate_number ASC
                """,
                (novel_id, int(chapter_number)),
            ).fetchall()
        return [self._candidate_dict(row) for row in rows]

    def get_chapter_candidate(self, novel_id: str, candidate_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM chapter_candidates
                WHERE novel_id = ? AND id = ?
                """,
                (novel_id, candidate_id),
            ).fetchone()
        return self._candidate_dict(row) if row else None

    def invalidate_chapter_candidates(self, novel_id: str) -> int:
        """Mark all selectable candidates stale after a global creative-context change."""
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE chapter_candidates SET status = 'stale', selected_at = NULL "
                "WHERE novel_id = ? AND status IN ('available', 'selected')",
                (novel_id,),
            )
        return int(cursor.rowcount)

    def mark_chapter_candidate_selected(
        self,
        novel_id: str,
        chapter_number: int,
        candidate_id: str,
    ) -> dict | None:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            candidate = conn.execute(
                """
                SELECT * FROM chapter_candidates
                WHERE novel_id = ? AND chapter_number = ? AND id = ?
                """,
                (novel_id, int(chapter_number), candidate_id),
            ).fetchone()
            if candidate is None:
                return None
            conn.execute(
                """
                UPDATE chapter_candidates
                SET status = 'available', selected_at = NULL
                WHERE novel_id = ? AND chapter_number = ? AND status = 'selected'
                """,
                (novel_id, int(chapter_number)),
            )
            conn.execute(
                """
                UPDATE chapter_candidates
                SET status = 'selected', selected_at = ? WHERE id = ?
                """,
                (now, candidate_id),
            )
            selected = conn.execute(
                "SELECT * FROM chapter_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
        return self._candidate_dict(selected)

    @staticmethod
    def _candidate_dict(row: sqlite3.Row) -> dict:
        candidate = dict(row)
        for raw_key, target_key, fallback in (
            ("scene_plan_json", "scene_plan", []),
            ("scene_drafts_json", "scene_drafts", []),
            ("scores_json", "scores", {}),
        ):
            raw_value = candidate.pop(raw_key) or json.dumps(fallback)
            try:
                parsed = json.loads(raw_value)
            except (TypeError, json.JSONDecodeError):
                parsed = fallback
            candidate[target_key] = parsed if isinstance(parsed, type(fallback)) else fallback
        candidate["preview"] = str(candidate.get("content", ""))[:240]
        return candidate

    # ------------------------------------------------------------------
    # 规划版本
    # ------------------------------------------------------------------
    def save_planning_version(
        self,
        novel_id: str,
        artifact_type: str,
        chapter_number: int,
        *,
        source: str,
        payload: dict,
    ) -> dict:
        """幂等保存蓝图或分镜快照，并按作品/类型/章节递增编号。"""
        if artifact_type not in {"blueprint", "scene"}:
            raise ValueError("artifact_type 必须是 blueprint 或 scene")
        normalized_chapter = 0 if artifact_type == "blueprint" else int(chapter_number)
        if artifact_type == "scene" and normalized_chapter < 1:
            raise ValueError("scene 版本必须包含有效章节号")
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        content_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT * FROM planning_versions
                WHERE novel_id = ? AND artifact_type = ? AND chapter_number = ?
                  AND source = ? AND content_hash = ?
                """,
                (novel_id, artifact_type, normalized_chapter, source, content_hash),
            ).fetchone()
            if existing:
                return self._planning_version_dict(existing)

            row = conn.execute(
                """
                SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version
                FROM planning_versions
                WHERE novel_id = ? AND artifact_type = ? AND chapter_number = ?
                """,
                (novel_id, artifact_type, normalized_chapter),
            ).fetchone()
            version_number = int(row["next_version"])
            conn.execute(
                """
                INSERT INTO planning_versions (
                    novel_id, artifact_type, chapter_number, version_number,
                    source, payload_json, content_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    artifact_type,
                    normalized_chapter,
                    version_number,
                    source,
                    serialized,
                    content_hash,
                    now,
                ),
            )
            saved = conn.execute(
                """
                SELECT * FROM planning_versions
                WHERE novel_id = ? AND artifact_type = ? AND chapter_number = ?
                  AND version_number = ?
                """,
                (novel_id, artifact_type, normalized_chapter, version_number),
            ).fetchone()
        return self._planning_version_dict(saved)

    def list_planning_versions(
        self,
        novel_id: str,
        artifact_type: str,
        chapter_number: int = 0,
    ) -> list[dict]:
        normalized_chapter = 0 if artifact_type == "blueprint" else int(chapter_number)
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM planning_versions
                WHERE novel_id = ? AND artifact_type = ? AND chapter_number = ?
                ORDER BY version_number
                """,
                (novel_id, artifact_type, normalized_chapter),
            ).fetchall()
        versions = [self._planning_version_dict(row) for row in rows]
        for version in versions:
            payload = version.pop("payload")
            version["preview"] = self._planning_version_preview(artifact_type, payload)
            version.pop("content_hash", None)
        return versions

    def get_planning_version(
        self,
        novel_id: str,
        artifact_type: str,
        chapter_number: int,
        version_number: int,
    ) -> dict | None:
        normalized_chapter = 0 if artifact_type == "blueprint" else int(chapter_number)
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM planning_versions
                WHERE novel_id = ? AND artifact_type = ? AND chapter_number = ?
                  AND version_number = ?
                """,
                (novel_id, artifact_type, normalized_chapter, version_number),
            ).fetchone()
        return self._planning_version_dict(row) if row else None

    @staticmethod
    def _planning_version_dict(row: sqlite3.Row) -> dict:
        version = dict(row)
        raw_payload = version.pop("payload_json") or "{}"
        try:
            payload = json.loads(raw_payload)
        except (TypeError, json.JSONDecodeError):
            payload = {}
        version["payload"] = payload if isinstance(payload, dict) else {}
        return version

    @staticmethod
    def _planning_version_preview(artifact_type: str, payload: dict) -> str:
        if artifact_type == "blueprint":
            world = str(payload.get("world_bible", ""))
            return (
                f"世界观 {len(world)} 字 · {len(payload.get('characters') or [])} 角色 · "
                f"{len(payload.get('outline') or [])} 章"
            )
        scenes = payload.get("scene_plan") or []
        words = sum(int(item.get("estimated_words", 0) or 0) for item in scenes)
        return f"{len(scenes)} 场 · {words} 字"

    # ------------------------------------------------------------------
    # 章节评测
    # ------------------------------------------------------------------
    def save_chapter_evaluation(
        self,
        novel_id: str,
        chapter_number: int,
        version_number: int,
        *,
        content_hash: str,
        evaluator_version: str,
        rubric_version: str,
        deterministic_scores: dict[str, float],
        judge_scores: dict[str, float] | None,
        overall_score: float,
        findings: list[dict],
        model_provider: str = "",
        model_name: str = "",
        judge_error: str = "",
    ) -> dict:
        """保存一次评测运行；同一版本允许保留多次模型评审结果。"""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO chapter_evaluations (
                    novel_id, chapter_number, version_number, content_hash,
                    evaluator_version, rubric_version, model_provider, model_name,
                    deterministic_scores_json, judge_scores_json, overall_score,
                    findings_json, judge_error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    chapter_number,
                    version_number,
                    content_hash,
                    evaluator_version,
                    rubric_version,
                    model_provider,
                    model_name,
                    json.dumps(deterministic_scores, ensure_ascii=False),
                    json.dumps(judge_scores or {}, ensure_ascii=False),
                    float(overall_score),
                    json.dumps(findings, ensure_ascii=False),
                    judge_error,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM chapter_evaluations WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return self._evaluation_dict(row)

    def list_chapter_evaluations(
        self,
        novel_id: str,
        chapter_number: int,
        version_number: int | None = None,
    ) -> list[dict]:
        query = """
            SELECT * FROM chapter_evaluations
            WHERE novel_id = ? AND chapter_number = ?
        """
        params: list[object] = [novel_id, chapter_number]
        if version_number is not None:
            query += " AND version_number = ?"
            params.append(version_number)
        query += " ORDER BY id DESC"
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._evaluation_dict(row) for row in rows]

    def get_chapter_evaluation(self, evaluation_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM chapter_evaluations WHERE id = ?",
                (evaluation_id,),
            ).fetchone()
        return self._evaluation_dict(row) if row else None

    def get_latest_chapter_evaluation(
        self,
        novel_id: str,
        chapter_number: int,
        version_number: int,
    ) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM chapter_evaluations
                WHERE novel_id = ? AND chapter_number = ? AND version_number = ?
                ORDER BY id DESC LIMIT 1
                """,
                (novel_id, chapter_number, version_number),
            ).fetchone()
        return self._evaluation_dict(row) if row else None

    def get_chapter_evaluation_baseline(
        self,
        novel_id: str,
        chapter_number: int,
    ) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM chapter_evaluations
                WHERE novel_id = ? AND chapter_number = ? AND is_baseline = 1
                ORDER BY id DESC LIMIT 1
                """,
                (novel_id, chapter_number),
            ).fetchone()
        return self._evaluation_dict(row) if row else None

    def set_chapter_evaluation_baseline(
        self,
        novel_id: str,
        chapter_number: int,
        evaluation_id: int,
    ) -> dict | None:
        """每章只保留一个人工选定的评测基准。"""
        with self._conn() as conn:
            target = conn.execute(
                """
                SELECT * FROM chapter_evaluations
                WHERE id = ? AND novel_id = ? AND chapter_number = ?
                """,
                (evaluation_id, novel_id, chapter_number),
            ).fetchone()
            if target is None:
                return None
            conn.execute(
                """
                UPDATE chapter_evaluations SET is_baseline = 0
                WHERE novel_id = ? AND chapter_number = ?
                """,
                (novel_id, chapter_number),
            )
            conn.execute(
                "UPDATE chapter_evaluations SET is_baseline = 1 WHERE id = ?",
                (evaluation_id,),
            )
            updated = conn.execute(
                "SELECT * FROM chapter_evaluations WHERE id = ?",
                (evaluation_id,),
            ).fetchone()
        return self._evaluation_dict(updated)

    @staticmethod
    def _evaluation_dict(row: sqlite3.Row) -> dict:
        evaluation = dict(row)
        for raw_key, target_key, fallback in (
            ("deterministic_scores_json", "deterministic_scores", {}),
            ("judge_scores_json", "judge_scores", {}),
            ("findings_json", "findings", []),
        ):
            raw_value = evaluation.pop(raw_key) or json.dumps(fallback)
            try:
                parsed = json.loads(raw_value)
            except (TypeError, json.JSONDecodeError):
                parsed = fallback
            evaluation[target_key] = parsed if isinstance(parsed, type(fallback)) else fallback
        evaluation["is_baseline"] = bool(evaluation.get("is_baseline"))
        return evaluation

    # ------------------------------------------------------------------
    # 固定评测基准
    # ------------------------------------------------------------------
    def save_evaluation_benchmark(self, report: dict) -> dict:
        """保存一次完整评测套件运行及其可追踪元数据。"""
        run_id = str(report.get("id") or f"eval_{uuid4().hex}")
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO evaluation_benchmark_runs (
                    id, tenant_id, suite_version, evaluator_version, rubric_version,
                    prompt_hash, input_hash, include_judge, model_provider,
                    model_name, baseline_run_id, gate_threshold,
                    regression_threshold, overall_score, status, judge_error,
                    report_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    current_tenant_id() or LOCAL_TENANT_ID,
                    str(report.get("suite_version", "")),
                    str(report.get("evaluator_version", "")),
                    str(report.get("rubric_version", "")),
                    str(report.get("prompt_hash", "")),
                    str(report.get("input_hash", "")),
                    int(bool(report.get("include_judge"))),
                    str(report.get("model_provider", "")),
                    str(report.get("model_name", "")),
                    report.get("baseline_run_id") or None,
                    float(report.get("gate_threshold", 0.0)),
                    float(report.get("regression_threshold", 0.0)),
                    float(report.get("overall_score", 0.0)),
                    str(report.get("status", "failed")),
                    str(report.get("judge_error", "")),
                    json.dumps(report, ensure_ascii=False),
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM evaluation_benchmark_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return self._evaluation_benchmark_dict(row)

    def get_evaluation_benchmark(self, run_id: str) -> dict | None:
        tenant = current_tenant_id()
        with self._conn() as conn:
            query = "SELECT * FROM evaluation_benchmark_runs WHERE id = ?"
            params: list[object] = [run_id]
            if tenant:
                query += " AND tenant_id = ?"
                params.append(tenant)
            row = conn.execute(query, params).fetchone()
        return self._evaluation_benchmark_dict(row) if row else None

    def list_evaluation_benchmarks(self, limit: int = 50) -> list[dict]:
        tenant = current_tenant_id()
        with self._conn() as conn:
            query = "SELECT * FROM evaluation_benchmark_runs"
            params: list[object] = []
            if tenant:
                query += " WHERE tenant_id = ?"
                params.append(tenant)
            query += " ORDER BY created_at DESC, id DESC LIMIT ?"
            params.append(max(1, min(int(limit), 200)))
            rows = conn.execute(query, params).fetchall()
        return [self._evaluation_benchmark_dict(row) for row in rows]

    @staticmethod
    def _evaluation_benchmark_dict(row: sqlite3.Row) -> dict:
        record = dict(row)
        raw_report = record.pop("report_json") or "{}"
        try:
            report = json.loads(raw_report)
        except (TypeError, json.JSONDecodeError):
            report = {}
        merged = {**record, **(report if isinstance(report, dict) else {})}
        merged["id"] = record["id"]
        merged["created_at"] = record["created_at"]
        merged["include_judge"] = bool(record.get("include_judge"))
        merged["cases"] = merged.get("cases") if isinstance(merged.get("cases"), list) else []
        return merged

    # ------------------------------------------------------------------
    # 全书审计
    # ------------------------------------------------------------------
    def save_book_audit(
        self,
        novel_id: str,
        *,
        manuscript_hash: str,
        schema_version: str,
        rubric_version: str,
        report: dict,
    ) -> dict:
        """幂等保存同一份终稿、同一审计版本的全书报告。"""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO book_audits (
                    novel_id, manuscript_hash, schema_version,
                    rubric_version, report_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    manuscript_hash,
                    schema_version,
                    rubric_version,
                    json.dumps(report, ensure_ascii=False),
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM book_audits
                WHERE novel_id = ? AND manuscript_hash = ?
                  AND schema_version = ? AND rubric_version = ?
                """,
                (novel_id, manuscript_hash, schema_version, rubric_version),
            ).fetchone()
        return self._book_audit_dict(row)

    def list_book_audits(self, novel_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM book_audits WHERE novel_id = ? ORDER BY id DESC",
                (novel_id,),
            ).fetchall()
        return [self._book_audit_dict(row) for row in rows]

    def get_latest_book_audit(self, novel_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM book_audits WHERE novel_id = ? ORDER BY id DESC LIMIT 1",
                (novel_id,),
            ).fetchone()
        return self._book_audit_dict(row) if row else None

    @staticmethod
    def _book_audit_dict(row: sqlite3.Row) -> dict:
        audit = dict(row)
        raw_report = audit.pop("report_json") or "{}"
        try:
            report = json.loads(raw_report)
        except (TypeError, json.JSONDecodeError):
            report = {}
        audit["report"] = report if isinstance(report, dict) else {}
        return audit

    # ------------------------------------------------------------------
    # 分层长篇记忆
    # ------------------------------------------------------------------
    def save_memory_snapshot(
        self,
        novel_id: str,
        *,
        schema_version: str,
        content_hash: str,
        payload: dict,
    ) -> dict:
        """按索引哈希幂等保存一份全书记忆快照。"""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_snapshots (
                    novel_id, schema_version, content_hash, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    schema_version,
                    content_hash,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM memory_snapshots
                WHERE novel_id = ? AND schema_version = ? AND content_hash = ?
                """,
                (novel_id, schema_version, content_hash),
            ).fetchone()
        return self._memory_snapshot_dict(row)

    def get_latest_memory_snapshot(self, novel_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM memory_snapshots
                WHERE novel_id = ? ORDER BY id DESC LIMIT 1
                """,
                (novel_id,),
            ).fetchone()
        return self._memory_snapshot_dict(row) if row else None

    def list_memory_snapshots(self, novel_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_snapshots WHERE novel_id = ? ORDER BY id DESC",
                (novel_id,),
            ).fetchall()
        return [self._memory_snapshot_dict(row) for row in rows]

    @staticmethod
    def _memory_snapshot_dict(row: sqlite3.Row) -> dict:
        snapshot = dict(row)
        raw_payload = snapshot.pop("payload_json") or "{}"
        try:
            payload = json.loads(raw_payload)
        except (TypeError, json.JSONDecodeError):
            payload = {}
        snapshot["payload"] = payload if isinstance(payload, dict) else {}
        return snapshot

    # ------------------------------------------------------------------
    # 记忆检索质量评测
    # ------------------------------------------------------------------
    def save_memory_quality_run(
        self,
        novel_id: str,
        *,
        mode: str,
        index_hash: str,
        report: dict,
    ) -> dict:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memory_quality_runs (
                    novel_id, tenant_id, mode, index_hash, report_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    current_tenant_id() or LOCAL_TENANT_ID,
                    str(mode or "evaluate"),
                    str(index_hash or ""),
                    json.dumps(report, ensure_ascii=False),
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM memory_quality_runs WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return self._memory_quality_run_dict(row)

    def list_memory_quality_runs(self, novel_id: str, limit: int = 20) -> list[dict]:
        tenant = current_tenant_id()
        with self._conn() as conn:
            query = "SELECT * FROM memory_quality_runs WHERE novel_id = ?"
            params: list[object] = [novel_id]
            if tenant:
                query += " AND tenant_id = ?"
                params.append(tenant)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(max(1, min(int(limit), 100)))
            rows = conn.execute(query, params).fetchall()
        return [self._memory_quality_run_dict(row) for row in rows]

    @staticmethod
    def _memory_quality_run_dict(row: sqlite3.Row) -> dict:
        record = dict(row)
        raw_report = record.pop("report_json") or "{}"
        try:
            report = json.loads(raw_report)
        except (TypeError, json.JSONDecodeError):
            report = {}
        record["report"] = report if isinstance(report, dict) else {}
        return record

    # ------------------------------------------------------------------
    # 后台运行任务
    # ------------------------------------------------------------------
    def create_transfer_job(
        self,
        job_id: str,
        kind: str,
        request: dict | None = None,
        *,
        novel_id: str = "",
        input_path: str = "",
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> dict:
        principal = current_principal()
        tenant = tenant_id or (principal.tenant_id if principal else LOCAL_TENANT_ID)
        creator = user_id or (principal.user_id if principal else LOCAL_USER_ID)
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO transfer_jobs (
                    id, tenant_id, user_id, kind, novel_id, status, request_json,
                    input_path, output_path, result_json, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, '', '{}', '', ?, ?)
                """,
                (
                    job_id,
                    tenant,
                    creator,
                    kind,
                    novel_id or None,
                    json.dumps(request or {}, ensure_ascii=False),
                    input_path or None,
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM transfer_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._transfer_job_dict(row)

    def get_transfer_job(self, job_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM transfer_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._transfer_job_dict(row) if row else None

    def update_transfer_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        output_path: str | None = None,
        result: dict | None = None,
        error: str | None = None,
    ) -> dict | None:
        now = datetime.now().isoformat()
        assignments = ["updated_at = ?"]
        params: list[object] = [now]
        if status is not None:
            assignments.append("status = ?")
            params.append(status)
            if status == "running":
                assignments.append("started_at = COALESCE(started_at, ?)")
                params.append(now)
            if status in {"completed", "failed", "cancelled", "interrupted"}:
                assignments.append("finished_at = ?")
                params.append(now)
        if output_path is not None:
            assignments.append("output_path = ?")
            params.append(output_path)
        if result is not None:
            assignments.append("result_json = ?")
            params.append(json.dumps(result, ensure_ascii=False))
        if error is not None:
            assignments.append("error = ?")
            params.append(error)
        params.append(job_id)
        with self._conn() as conn:
            cursor = conn.execute(
                f"UPDATE transfer_jobs SET {', '.join(assignments)} WHERE id = ?",
                params,
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute("SELECT * FROM transfer_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._transfer_job_dict(row) if row else None

    def recover_transfer_jobs(self, reason: str = "服务重启，传输任务已中断") -> int:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                UPDATE transfer_jobs
                SET status = 'interrupted', error = ?, finished_at = ?, updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (reason, now, now),
            )
            return int(cursor.rowcount)

    @staticmethod
    def _transfer_job_dict(row: sqlite3.Row) -> dict:
        job = dict(row)
        try:
            request = json.loads(job.pop("request_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            request = {}
        try:
            result = json.loads(job.pop("result_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            result = {}
        job["request"] = request if isinstance(request, dict) else {}
        job["result"] = result if isinstance(result, dict) else {}
        return job

    def create_run_job(
        self,
        job_id: str,
        novel_id: str,
        action: str,
        request: dict | None = None,
        *,
        lease_owner: str = "",
        lease_seconds: int = 60,
    ) -> dict:
        """创建排队任务；同一作品同一时刻只允许一个活动任务。"""
        now_dt = datetime.now()
        now = now_dt.isoformat()
        owner = str(lease_owner).strip()
        expires = (
            now_dt + timedelta(seconds=max(int(lease_seconds), 1))
        ).isoformat() if owner else None
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO run_jobs (
                        id, novel_id, action, status, request_json,
                        lease_owner, lease_expires_at, heartbeat_at, attempt_count,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        novel_id,
                        action,
                        json.dumps(request or {}, ensure_ascii=False),
                        owner or None,
                        expires,
                        now if owner else None,
                        1 if owner else 0,
                        now,
                        now,
                    ),
                )
                row = conn.execute("SELECT * FROM run_jobs WHERE id = ?", (job_id,)).fetchone()
        except sqlite3.IntegrityError as exc:
            active = self.get_active_run_job(novel_id)
            if active:
                raise ValueError(f"作品已有活动任务 {active['id']}") from exc
            raise
        return self._run_job_dict(row)

    def get_run_job(self, job_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM run_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._run_job_dict(row) if row else None

    def get_active_run_job(self, novel_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM run_jobs
                WHERE novel_id = ? AND status IN ('queued', 'running')
                ORDER BY created_at DESC LIMIT 1
                """,
                (novel_id,),
            ).fetchone()
        return self._run_job_dict(row) if row else None

    def claim_run_job(
        self,
        job_id: str,
        lease_owner: str,
        lease_seconds: int,
    ) -> dict | None:
        """原子领取排队或租约已过期的任务,防止多进程重复执行。"""
        owner = str(lease_owner).strip()
        if not owner:
            raise ValueError("任务租约必须包含 Worker 标识")
        now_dt = datetime.now()
        now = now_dt.isoformat()
        expires = (now_dt + timedelta(seconds=max(int(lease_seconds), 1))).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                UPDATE run_jobs
                SET status = 'running',
                    lease_owner = ?,
                    lease_expires_at = ?,
                    heartbeat_at = ?,
                    attempt_count = attempt_count + CASE WHEN lease_owner = ? THEN 0 ELSE 1 END,
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?
                WHERE id = ?
                  AND status IN ('queued', 'running')
                  AND (
                    lease_owner IS NULL OR lease_owner = ?
                    OR lease_expires_at IS NULL OR lease_expires_at <= ?
                  )
                """,
                (owner, expires, now, owner, now, now, job_id, owner, now),
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute("SELECT * FROM run_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._run_job_dict(row) if row else None

    def renew_run_job_lease(
        self,
        job_id: str,
        lease_owner: str,
        lease_seconds: int,
    ) -> bool:
        """续租任务;返回 False 表示当前 Worker 已失去执行权。"""
        now_dt = datetime.now()
        now = now_dt.isoformat()
        expires = (now_dt + timedelta(seconds=max(int(lease_seconds), 1))).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                UPDATE run_jobs
                SET lease_expires_at = ?, heartbeat_at = ?, updated_at = ?
                WHERE id = ? AND lease_owner = ? AND status IN ('queued', 'running')
                """,
                (expires, now, now, job_id, str(lease_owner)),
            )
        return cursor.rowcount == 1

    def release_run_job_lease(self, job_id: str, lease_owner: str) -> bool:
        """释放仍由当前 Worker 持有的任务租约。"""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                UPDATE run_jobs
                SET lease_owner = NULL, lease_expires_at = NULL,
                    heartbeat_at = ?, updated_at = ?
                WHERE id = ? AND lease_owner = ?
                  AND status IN ('queued', 'running')
                """,
                (now, now, job_id, str(lease_owner)),
            )
        return cursor.rowcount == 1

    def get_latest_run_job(self, novel_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM run_jobs WHERE novel_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (novel_id,),
            ).fetchone()
        return self._run_job_dict(row) if row else None

    def update_run_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        current_node: str | None = None,
        error: str | None = None,
        lease_owner: str | None = None,
    ) -> dict | None:
        now = datetime.now().isoformat()
        assignments = ["updated_at = ?"]
        params: list[object] = [now]
        if status is not None:
            assignments.append("status = ?")
            params.append(status)
            if status == "running":
                assignments.append("started_at = COALESCE(started_at, ?)")
                params.append(now)
            if status in {"waiting_review", "completed", "failed", "cancelled", "interrupted"}:
                assignments.append("finished_at = ?")
                params.append(now)
                assignments.extend(["lease_owner = NULL", "lease_expires_at = NULL"])
        if current_node is not None:
            assignments.append("current_node = ?")
            params.append(current_node)
        if error is not None:
            assignments.append("error = ?")
            params.append(error)
        where = "id = ?"
        params.append(job_id)
        if lease_owner is not None:
            where += " AND lease_owner = ?"
            params.append(str(lease_owner))
        with self._conn() as conn:
            cursor = conn.execute(
                f"UPDATE run_jobs SET {', '.join(assignments)} WHERE {where}",
                params,
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute("SELECT * FROM run_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._run_job_dict(row) if row else None

    def request_run_job_cancel(self, job_id: str) -> dict | None:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE run_jobs SET cancel_requested = 1, updated_at = ?
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (now, job_id),
            )
            row = conn.execute("SELECT * FROM run_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._run_job_dict(row) if row else None

    def append_run_job_event(self, job_id: str, event: dict) -> dict:
        now = datetime.now().isoformat()
        event_type = str(event.get("type", "event"))
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence
                FROM run_job_events WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            sequence = int(row["next_sequence"])
            cursor = conn.execute(
                """
                INSERT INTO run_job_events (
                    job_id, sequence, event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, sequence, event_type, json.dumps(event, ensure_ascii=False), now),
            )
            saved = conn.execute(
                "SELECT * FROM run_job_events WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return self._run_job_event_dict(saved)

    def list_run_job_events(
        self,
        job_id: str,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM run_job_events
                WHERE job_id = ? AND sequence > ?
                ORDER BY sequence LIMIT ?
                """,
                (job_id, max(after_sequence, 0), max(1, min(limit, 1000))),
            ).fetchall()
        return [self._run_job_event_dict(row) for row in rows]

    def recover_expired_run_jobs(
        self,
        reason: str = "任务租约已过期，任务已中断",
    ) -> int:
        """只中断没有租约或租约已过期的任务,不干扰其他进程的活动任务。"""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                UPDATE run_jobs
                SET status = 'interrupted', error = ?, finished_at = ?, updated_at = ?,
                    lease_owner = NULL, lease_expires_at = NULL
                WHERE status IN ('queued', 'running')
                  AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                """,
                (reason, now, now, now),
            )
            return int(cursor.rowcount)

    def interrupt_run_jobs_by_owner(
        self,
        lease_owner: str,
        reason: str = "服务关闭，任务可从检查点继续",
    ) -> int:
        """服务关闭时只中断当前 Worker 持有的任务。"""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                """
                UPDATE run_jobs
                SET status = 'interrupted', error = ?, finished_at = ?, updated_at = ?,
                    lease_owner = NULL, lease_expires_at = NULL
                WHERE lease_owner = ? AND status IN ('queued', 'running')
                """,
                (reason, now, now, str(lease_owner)),
            )
            return int(cursor.rowcount)

    def interrupt_active_run_jobs(self, reason: str = "服务重启，任务已中断") -> int:
        """兼容旧调用:只处理中断时没有有效租约的活动任务。"""
        return self.recover_expired_run_jobs(reason)

    @staticmethod
    def _run_job_dict(row: sqlite3.Row) -> dict:
        job = dict(row)
        raw_request = job.pop("request_json") or "{}"
        try:
            request = json.loads(raw_request)
        except (TypeError, json.JSONDecodeError):
            request = {}
        job["request"] = request if isinstance(request, dict) else {}
        job["cancel_requested"] = bool(job.get("cancel_requested"))
        return job

    @staticmethod
    def _run_job_event_dict(row: sqlite3.Row) -> dict:
        event = dict(row)
        raw_payload = event.pop("payload_json") or "{}"
        try:
            payload = json.loads(raw_payload)
        except (TypeError, json.JSONDecodeError):
            payload = {}
        event["payload"] = payload if isinstance(payload, dict) else {}
        return event

    # ------------------------------------------------------------------
    # 进度(含 LangGraph 状态快照)
    # ------------------------------------------------------------------
    def save_progress(
        self, novel_id: str, current_chapter: int, current_phase: str, state: dict | None = None
    ) -> None:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO progress (novel_id, current_chapter, current_phase, state_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(novel_id) DO UPDATE SET
                    current_chapter=excluded.current_chapter,
                    current_phase=excluded.current_phase,
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (novel_id, current_chapter, current_phase,
                 json.dumps(state, ensure_ascii=False, default=str) if state else None, now),
            )

    def get_progress(self, novel_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM progress WHERE novel_id = ?", (novel_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["state"] = json.loads(d.pop("state_json") or "{}")
        return d
