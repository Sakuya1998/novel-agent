"""模型服务档案、加密密钥与全局模型路由持久化。"""

import json
import os
import sqlite3
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlparse
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken

from config import Config
from security import LOCAL_TENANT_ID, current_tenant_id

ProviderName = Literal["openai", "anthropic", "deepseek", "qwen", "openai_compatible"]
RoutePurpose = Literal["creative", "analysis", "embedding"]

PROVIDERS = {"openai", "anthropic", "deepseek", "qwen", "openai_compatible"}
ROUTE_PURPOSES = {"creative", "analysis", "embedding"}

PROVIDER_TEMPLATES: dict[str, dict[str, object]] = {
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "chat_models": ["gpt-4o", "gpt-4.1", "gpt-5"],
        "embedding_models": ["text-embedding-3-small", "text-embedding-3-large"],
    },
    "anthropic": {
        "label": "Anthropic",
        "base_url": "",
        "chat_models": ["claude-sonnet-4-5", "claude-opus-4-1"],
        "embedding_models": [],
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "chat_models": ["deepseek-chat", "deepseek-reasoner"],
        "embedding_models": [],
    },
    "qwen": {
        "label": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "chat_models": ["qwen-plus", "qwen-max", "qwen-turbo"],
        "embedding_models": ["text-embedding-v3"],
    },
    "openai_compatible": {
        "label": "OpenAI Compatible",
        "base_url": "",
        "chat_models": [],
        "embedding_models": [],
    },
}


class ModelSettingsError(RuntimeError):
    """模型设置无法保存或读取。"""


class ModelProfileNotFoundError(ModelSettingsError):
    """指定模型服务档案不存在。"""


class ModelSecretError(ModelSettingsError):
    """模型密钥无法加密或解密。"""


class ProfileInUseError(ModelSettingsError):
    """模型服务正在被全局路由引用。"""


class InvalidModelRouteError(ModelSettingsError):
    """模型路由不完整或与服务能力不兼容。"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_models(models: list[str]) -> list[str]:
    normalized: list[str] = []
    for model in models:
        value = str(model).strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 7:
        return "*" * len(secret)
    return f"{secret[:3]}...{secret[-4:]}"


class ModelSettingsStore:
    """在应用 SQLite 中保存模型档案，并用本地主密钥保护 API Key。"""

    SCHEMA_COMPONENT = "model_settings"
    SCHEMA_VERSION = 2

    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.config.ensure_dirs()
        self.db_path = Path(self.config.sqlite_db_path)
        self.key_path = Path(self.config.model_secret_key_path)
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _tenant_id() -> str:
        return str(current_tenant_id() or LOCAL_TENANT_ID)

    def _tenant_for_novel(self, novel_id: str) -> str:
        current = current_tenant_id()
        if current:
            return current
        try:
            with self._conn() as conn:
                row = conn.execute("SELECT tenant_id FROM novels WHERE id = ?", (novel_id,)).fetchone()
        except sqlite3.OperationalError:
            row = None
        return str(row["tenant_id"] if row and row["tenant_id"] else LOCAL_TENANT_ID)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS model_profiles (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'tenant_local',
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    base_url TEXT NOT NULL DEFAULT '',
                    api_key_encrypted BLOB NOT NULL DEFAULT X'',
                    chat_models_json TEXT NOT NULL DEFAULT '[]',
                    embedding_models_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS model_routes (
                    tenant_id TEXT NOT NULL DEFAULT 'tenant_local',
                    purpose TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    fallback_profile_id TEXT,
                    fallback_model_name TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, purpose),
                    FOREIGN KEY (profile_id) REFERENCES model_profiles(id) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS schema_migrations (
                    component TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS model_call_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL DEFAULT 'tenant_local',
                    novel_id TEXT,
                    agent TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    fallback_used INTEGER NOT NULL DEFAULT 0,
                    success INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    usage_estimated INTEGER NOT NULL DEFAULT 0,
                    error_type TEXT NOT NULL DEFAULT '',
                    call_id TEXT NOT NULL DEFAULT '',
                    trace_id TEXT NOT NULL DEFAULT '',
                    input_hash TEXT NOT NULL DEFAULT '',
                    output_hash TEXT NOT NULL DEFAULT '',
                    input_chars INTEGER NOT NULL DEFAULT 0,
                    output_chars INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )
            metric_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(model_call_metrics)").fetchall()
            }
            if "tenant_id" not in metric_columns:
                conn.execute(
                    "ALTER TABLE model_call_metrics ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'tenant_local'"
                )
            for name, definition in (
                ("call_id", "TEXT NOT NULL DEFAULT ''"),
                ("trace_id", "TEXT NOT NULL DEFAULT ''"),
                ("input_hash", "TEXT NOT NULL DEFAULT ''"),
                ("output_hash", "TEXT NOT NULL DEFAULT ''"),
                ("input_chars", "INTEGER NOT NULL DEFAULT 0"),
                ("output_chars", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in metric_columns:
                    conn.execute(f"ALTER TABLE model_call_metrics ADD COLUMN {name} {definition}")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_model_call_metrics_trace "
                "ON model_call_metrics(novel_id, id DESC)"
            )
            route_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(model_routes)").fetchall()
            }
            profile_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(model_profiles)").fetchall()
            }
            if "tenant_id" not in profile_columns:
                conn.execute(
                    "ALTER TABLE model_profiles ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'tenant_local'"
                )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_model_profiles_tenant_name "
                "ON model_profiles(tenant_id, name)"
            )
            if "fallback_profile_id" not in route_columns:
                conn.execute("ALTER TABLE model_routes ADD COLUMN fallback_profile_id TEXT")
                route_columns.add("fallback_profile_id")
            if "fallback_model_name" not in route_columns:
                conn.execute("ALTER TABLE model_routes ADD COLUMN fallback_model_name TEXT")
                route_columns.add("fallback_model_name")
            if "tenant_id" not in route_columns:
                conn.commit()
                conn.execute("PRAGMA foreign_keys = OFF")
                conn.execute("ALTER TABLE model_routes RENAME TO model_routes_legacy")
                conn.execute(
                    """
                    CREATE TABLE model_routes (
                        tenant_id TEXT NOT NULL DEFAULT 'tenant_local',
                        purpose TEXT NOT NULL,
                        profile_id TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        fallback_profile_id TEXT,
                        fallback_model_name TEXT,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (tenant_id, purpose),
                        FOREIGN KEY (profile_id) REFERENCES model_profiles(id) ON DELETE RESTRICT
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO model_routes ("
                    "tenant_id, purpose, profile_id, model_name, "
                    "fallback_profile_id, fallback_model_name, updated_at) "
                    "SELECT 'tenant_local', purpose, profile_id, model_name, "
                    "fallback_profile_id, fallback_model_name, updated_at "
                    "FROM model_routes_legacy"
                )
                conn.execute("DROP TABLE model_routes_legacy")
                conn.execute("PRAGMA foreign_keys = ON")
                route_columns = {
                    "tenant_id", "purpose", "profile_id", "model_name",
                    "fallback_profile_id", "fallback_model_name", "updated_at",
                }
            conn.execute(
                "INSERT INTO schema_migrations (component, version, applied_at) VALUES (?, ?, ?) "
                "ON CONFLICT(component) DO UPDATE SET version = excluded.version, "
                "applied_at = excluded.applied_at",
                (self.SCHEMA_COMPONENT, self.SCHEMA_VERSION, datetime.now(UTC).isoformat()),
            )

    def _has_encrypted_secrets(self) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM model_profiles WHERE length(api_key_encrypted) > 0 LIMIT 1"
            ).fetchone()
        return row is not None

    def _read_fernet(self, *, create: bool) -> Fernet | None:
        if self.key_path.exists():
            try:
                return Fernet(self.key_path.read_bytes().strip())
            except (OSError, ValueError) as exc:
                raise ModelSecretError("模型密钥主密钥无效，请恢复主密钥或重新录入 API Key") from exc

        if not create:
            if self._has_encrypted_secrets():
                raise ModelSecretError("模型密钥主密钥已丢失，请恢复主密钥或重新录入 API Key")
            return None
        if self._has_encrypted_secrets():
            raise ModelSecretError("模型密钥主密钥已丢失，拒绝生成新主密钥覆盖现有密文")

        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        temp_path = self.key_path.with_name(f".{self.key_path.name}.{uuid4().hex}.tmp")
        try:
            with temp_path.open("xb") as handle:
                handle.write(key)
                handle.flush()
                os.fsync(handle.fileno())
            with suppress(OSError):
                temp_path.chmod(0o600)
            try:
                os.link(temp_path, self.key_path)
            except FileExistsError:
                return self._read_fernet(create=False)
            with suppress(OSError):
                self.key_path.chmod(0o600)
        except OSError as exc:
            raise ModelSecretError("无法创建模型密钥主密钥文件") from exc
        finally:
            temp_path.unlink(missing_ok=True)
        return Fernet(key)

    def _encrypt_secret(self, secret: str) -> bytes:
        value = secret.strip()
        if not value:
            return b""
        fernet = self._read_fernet(create=True)
        if fernet is None:
            raise ModelSecretError("无法初始化模型密钥主密钥")
        return fernet.encrypt(value.encode("utf-8"))

    def _decrypt_secret(self, encrypted: bytes | str | None) -> str:
        if not encrypted:
            return ""
        raw = encrypted.encode("utf-8") if isinstance(encrypted, str) else encrypted
        fernet = self._read_fernet(create=False)
        if fernet is None:
            raise ModelSecretError("模型密钥主密钥不存在")
        try:
            return fernet.decrypt(raw).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise ModelSecretError("模型 API Key 解密失败，请重新录入") from exc

    def _validate_profile(self, provider: str, base_url: str) -> ProviderName:
        if provider not in PROVIDERS:
            raise ModelSettingsError(f"不支持的模型供应商: {provider}")
        if provider in {"deepseek", "qwen", "openai_compatible"}:
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ModelSettingsError("OpenAI 兼容服务必须配置有效的 HTTP(S) API 地址")
        return cast(ProviderName, provider)

    def _public_profile(self, row: sqlite3.Row) -> dict:
        secret = self._decrypt_secret(row["api_key_encrypted"])
        return {
            "id": row["id"],
            "name": row["name"],
            "provider": row["provider"],
            "base_url": row["base_url"],
            "has_api_key": bool(secret),
            "api_key_masked": _mask_secret(secret),
            "chat_models": json.loads(row["chat_models_json"] or "[]"),
            "embedding_models": json.loads(row["embedding_models_json"] or "[]"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _get_profile_row(self, profile_id: str) -> sqlite3.Row | None:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM model_profiles WHERE id = ? AND tenant_id = ?",
                (profile_id, self._tenant_id()),
            ).fetchone()

    def create_profile(
        self,
        *,
        name: str,
        provider: ProviderName | str,
        base_url: str,
        api_key: str,
        chat_models: list[str],
        embedding_models: list[str],
    ) -> dict:
        clean_name = name.strip()
        if not clean_name:
            raise ModelSettingsError("模型服务名称不能为空")
        clean_url = base_url.strip().rstrip("/")
        clean_provider = self._validate_profile(str(provider), clean_url)
        profile_id = f"profile_{uuid4().hex[:12]}"
        now = _now()
        encrypted = self._encrypt_secret(api_key)
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO model_profiles (
                        id, tenant_id, name, provider, base_url, api_key_encrypted,
                        chat_models_json, embedding_models_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile_id,
                        self._tenant_id(),
                        clean_name,
                        clean_provider,
                        clean_url,
                        encrypted,
                        json.dumps(_normalize_models(chat_models), ensure_ascii=False),
                        json.dumps(_normalize_models(embedding_models), ensure_ascii=False),
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ModelSettingsError("模型服务名称已存在") from exc
        profile = self.get_public_profile(profile_id)
        if profile is None:
            raise ModelSettingsError("模型服务保存失败")
        return profile

    def update_profile(
        self,
        profile_id: str,
        *,
        name: str | None = None,
        provider: ProviderName | str | None = None,
        base_url: str | None = None,
        api_key: str = "",
        clear_api_key: bool = False,
        chat_models: list[str] | None = None,
        embedding_models: list[str] | None = None,
    ) -> dict:
        current = self._get_profile_row(profile_id)
        if current is None:
            raise ModelProfileNotFoundError("模型服务不存在")

        clean_name = current["name"] if name is None else name.strip()
        if not clean_name:
            raise ModelSettingsError("模型服务名称不能为空")
        clean_provider = str(current["provider"] if provider is None else provider)
        clean_url = str(current["base_url"] if base_url is None else base_url).strip().rstrip("/")
        clean_provider = self._validate_profile(clean_provider, clean_url)
        encrypted = current["api_key_encrypted"]
        if clear_api_key:
            encrypted = b""
        elif api_key.strip():
            encrypted = self._encrypt_secret(api_key)
        chats = (
            json.loads(current["chat_models_json"] or "[]")
            if chat_models is None
            else _normalize_models(chat_models)
        )
        embeddings = (
            json.loads(current["embedding_models_json"] or "[]")
            if embedding_models is None
            else _normalize_models(embedding_models)
        )
        try:
            with self._conn() as conn:
                if clean_provider == "anthropic":
                    embedding_route = conn.execute(
                        "SELECT 1 FROM model_routes WHERE tenant_id = ? AND purpose = 'embedding' AND profile_id = ?",
                        (self._tenant_id(), profile_id),
                    ).fetchone()
                    if embedding_route:
                        raise ProfileInUseError(
                            "正在用于嵌入模型的服务不能改为 Anthropic，请先切换模型分工"
                        )
                conn.execute(
                    """
                    UPDATE model_profiles
                    SET name = ?, provider = ?, base_url = ?, api_key_encrypted = ?,
                        chat_models_json = ?, embedding_models_json = ?, updated_at = ?
                    WHERE id = ? AND tenant_id = ?
                    """,
                    (
                        clean_name,
                        clean_provider,
                        clean_url,
                        encrypted,
                        json.dumps(chats, ensure_ascii=False),
                        json.dumps(embeddings, ensure_ascii=False),
                        _now(),
                        profile_id,
                        self._tenant_id(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ModelSettingsError("模型服务名称已存在") from exc
        profile = self.get_public_profile(profile_id)
        if profile is None:
            raise ModelProfileNotFoundError("模型服务不存在")
        return profile

    def list_profiles(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM model_profiles WHERE tenant_id = ? ORDER BY created_at, name",
                (self._tenant_id(),),
            ).fetchall()
        return [self._public_profile(row) for row in rows]

    def get_public_profile(self, profile_id: str) -> dict | None:
        row = self._get_profile_row(profile_id)
        return self._public_profile(row) if row is not None else None

    def get_profile_secret(self, profile_id: str) -> str:
        row = self._get_profile_row(profile_id)
        if row is None:
            raise ModelProfileNotFoundError("模型服务不存在")
        return self._decrypt_secret(row["api_key_encrypted"])

    def get_runtime_profile(self, profile_id: str) -> dict:
        profile = self.get_public_profile(profile_id)
        if profile is None:
            raise ModelProfileNotFoundError("模型服务不存在")
        return {**profile, "api_key": self.get_profile_secret(profile_id)}

    def get_runtime_secrets(self) -> list[str]:
        """Return decrypted credentials for in-process log redaction only."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT api_key_encrypted FROM model_profiles WHERE tenant_id = ? AND length(api_key_encrypted) > 0",
                (self._tenant_id(),),
            ).fetchall()
        return [secret for row in rows if (secret := self._decrypt_secret(row[0]))]

    def delete_profile(self, profile_id: str) -> bool:
        with self._conn() as conn:
            referenced = conn.execute(
                """
                SELECT 1 FROM model_routes
                WHERE tenant_id = ? AND (profile_id = ? OR fallback_profile_id = ?) LIMIT 1
                """,
                (self._tenant_id(), profile_id, profile_id),
            ).fetchone()
            if referenced:
                raise ProfileInUseError("模型服务正在被模型分工使用，请先切换路由")
            cursor = conn.execute(
                "DELETE FROM model_profiles WHERE id = ? AND tenant_id = ?",
                (profile_id, self._tenant_id()),
            )
            return cursor.rowcount > 0

    def save_routes(self, routes: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        if set(routes) != ROUTE_PURPOSES:
            raise InvalidModelRouteError("必须同时配置创作、分析和嵌入模型")

        normalized: dict[str, dict[str, str]] = {}
        with self._conn() as conn:
            for purpose in sorted(ROUTE_PURPOSES):
                target = routes[purpose]
                profile_id = str(target.get("profile_id", "")).strip()
                model_name = str(target.get("model_name", "")).strip()
                if not profile_id or not model_name:
                    raise InvalidModelRouteError(f"{purpose} 路由缺少服务或模型名称")
                profile = conn.execute(
                    "SELECT provider FROM model_profiles WHERE id = ? AND tenant_id = ?",
                    (profile_id, self._tenant_id()),
                ).fetchone()
                if profile is None:
                    raise InvalidModelRouteError(f"{purpose} 路由引用的模型服务不存在")
                if purpose == "embedding" and profile["provider"] == "anthropic":
                    raise InvalidModelRouteError("Anthropic 服务不能用于嵌入模型")
                fallback_profile_id = str(target.get("fallback_profile_id", "")).strip()
                fallback_model_name = str(target.get("fallback_model_name", "")).strip()
                if bool(fallback_profile_id) != bool(fallback_model_name):
                    raise InvalidModelRouteError(f"{purpose} 备用路由必须同时配置服务和模型名称")
                if purpose == "embedding" and fallback_profile_id:
                    raise InvalidModelRouteError("嵌入模型暂不支持备用路由")
                if fallback_profile_id:
                    fallback_profile = conn.execute(
                        "SELECT provider FROM model_profiles WHERE id = ? AND tenant_id = ?",
                        (fallback_profile_id, self._tenant_id()),
                    ).fetchone()
                    if fallback_profile is None:
                        raise InvalidModelRouteError(f"{purpose} 备用路由引用的模型服务不存在")
                normalized[purpose] = {
                    "profile_id": profile_id,
                    "model_name": model_name,
                    "fallback_profile_id": fallback_profile_id,
                    "fallback_model_name": fallback_model_name,
                }

            now = _now()
            for purpose, target in normalized.items():
                conn.execute(
                    """
                    INSERT INTO model_routes (
                        tenant_id, purpose, profile_id, model_name,
                        fallback_profile_id, fallback_model_name, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tenant_id, purpose) DO UPDATE SET
                        profile_id = excluded.profile_id,
                        model_name = excluded.model_name,
                        fallback_profile_id = excluded.fallback_profile_id,
                        fallback_model_name = excluded.fallback_model_name,
                        updated_at = excluded.updated_at
                    """,
                    (
                        self._tenant_id(),
                        purpose,
                        target["profile_id"],
                        target["model_name"],
                        target["fallback_profile_id"] or None,
                        target["fallback_model_name"] or None,
                        now,
                    ),
                )
        return self.get_routes()

    def get_routes(self) -> dict[str, dict[str, str]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT purpose, profile_id, model_name, fallback_profile_id, fallback_model_name
                FROM model_routes WHERE tenant_id = ? ORDER BY purpose
                """,
                (self._tenant_id(),),
            ).fetchall()
        routes: dict[str, dict[str, str]] = {}
        for row in rows:
            target = {"profile_id": row["profile_id"], "model_name": row["model_name"]}
            if row["fallback_profile_id"] and row["fallback_model_name"]:
                target.update({
                    "fallback_profile_id": row["fallback_profile_id"],
                    "fallback_model_name": row["fallback_model_name"],
                })
            routes[row["purpose"]] = target
        return routes

    def record_model_call(
        self,
        *,
        novel_id: str,
        agent: str,
        purpose: str,
        provider: str,
        model_name: str,
        attempt: int,
        fallback_used: bool,
        success: bool,
        duration_ms: int,
        input_tokens: int,
        output_tokens: int,
        usage_estimated: bool,
        error_type: str = "",
        call_id: str = "",
        trace_id: str = "",
        input_hash: str = "",
        output_hash: str = "",
        input_chars: int = 0,
        output_chars: int = 0,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO model_call_metrics (
                    tenant_id, novel_id, agent, purpose, provider, model_name, attempt,
                    fallback_used, success, duration_ms, input_tokens, output_tokens,
                    usage_estimated, error_type, call_id, trace_id, input_hash,
                    output_hash, input_chars, output_chars, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._tenant_for_novel(novel_id),
                    novel_id,
                    agent,
                    purpose,
                    provider,
                    model_name,
                    attempt,
                    int(fallback_used),
                    int(success),
                    max(duration_ms, 0),
                    max(input_tokens, 0),
                    max(output_tokens, 0),
                    int(usage_estimated),
                    error_type,
                    call_id,
                    trace_id,
                    input_hash,
                    output_hash,
                    max(int(input_chars), 0),
                    max(int(output_chars), 0),
                    _now(),
                ),
            )

    def list_model_traces(
        self,
        novel_id: str,
        *,
        limit: int = 100,
        agent: str = "",
    ) -> list[dict]:
        """返回最近模型调用轨迹,只包含哈希和统计元数据,不返回正文。"""
        safe_limit = min(max(int(limit), 1), 500)
        clauses = ["tenant_id = ?", "novel_id = ?"]
        params: list[object] = [self._tenant_for_novel(novel_id), novel_id]
        if agent.strip():
            clauses.append("agent = ?")
            params.append(agent.strip())
        params.append(safe_limit)
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT id, novel_id, agent, purpose, provider, model_name, attempt,
                       fallback_used, success, duration_ms, input_tokens, output_tokens,
                       usage_estimated, error_type, call_id, trace_id, input_hash,
                       output_hash, input_chars, output_chars, created_at
                FROM model_call_metrics
                WHERE {' AND '.join(clauses)}
                ORDER BY id DESC LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                **dict(row),
                "fallback_used": bool(row["fallback_used"]),
                "success": bool(row["success"]),
                "usage_estimated": bool(row["usage_estimated"]),
            }
            for row in rows
        ]

    def get_model_usage(self, novel_id: str) -> dict:
        with self._conn() as conn:
            total = conn.execute(
                """
                SELECT COUNT(*) AS attempts,
                       SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_calls,
                       SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_attempts,
                       SUM(CASE WHEN fallback_used = 1 THEN 1 ELSE 0 END) AS fallback_attempts,
                       COALESCE(SUM(duration_ms), 0) AS duration_ms,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       SUM(CASE WHEN usage_estimated = 1 THEN 1 ELSE 0 END) AS estimated_attempts
                FROM model_call_metrics WHERE tenant_id = ? AND novel_id = ?
                """,
                (self._tenant_for_novel(novel_id), novel_id),
            ).fetchone()
            rows = conn.execute(
                """
                SELECT agent, COUNT(*) AS attempts,
                       SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_calls,
                       SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_attempts,
                       COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
                       COALESCE(SUM(duration_ms), 0) AS duration_ms
                FROM model_call_metrics WHERE tenant_id = ? AND novel_id = ? GROUP BY agent ORDER BY agent
                """,
                (self._tenant_for_novel(novel_id), novel_id),
            ).fetchall()
        input_tokens = int(total["input_tokens"] or 0)
        output_tokens = int(total["output_tokens"] or 0)
        return {
            "attempts": int(total["attempts"] or 0),
            "successful_calls": int(total["successful_calls"] or 0),
            "failed_attempts": int(total["failed_attempts"] or 0),
            "fallback_attempts": int(total["fallback_attempts"] or 0),
            "duration_ms": int(total["duration_ms"] or 0),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "estimated_attempts": int(total["estimated_attempts"] or 0),
            "by_agent": [dict(row) for row in rows],
        }

    def delete_novel_metrics(self, novel_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM model_call_metrics WHERE novel_id = ?", (novel_id,))

    def get_public_settings(self) -> dict:
        routes = self.get_routes()
        if set(routes) == ROUTE_PURPOSES:
            source = "database"
        elif self.config.openai_api_key or self.config.anthropic_api_key:
            source = "environment"
        else:
            source = "unconfigured"
        return {
            "source": source,
            "templates": PROVIDER_TEMPLATES,
            "profiles": self.list_profiles(),
            "routes": routes,
        }
