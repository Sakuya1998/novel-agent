"""FastAPI 服务:小说管理、持久化图运行与人工审查恢复。"""

import asyncio
import difflib
import io
import json
import logging
import sqlite3
import time
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import uuid4
from weakref import WeakValueDictionary

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from agents.chapter_candidate import (
    ChapterCandidateAgent,
    chapter_candidate_matches_state,
    chapter_candidate_source_hash,
)
from agents.character_designer import validate_characters
from agents.plot_planner import validate_outline
from agents.quality_evaluator import QualityEvaluatorAgent
from agents.scene_planner import normalize_scene_plan
from api.model_settings import router as model_settings_router
from config import Config, validate_production_config
from graph.builder import build_graph
from graph.state import create_initial_state
from memory.canon import apply_canon_operation, empty_canon, ensure_canon
from memory.hierarchical import build_hierarchical_memory, hierarchical_memory_hash
from memory.sql_store import NovelStore
from memory.vector_store import NovelMemory
from models.creative_brief import normalize_creative_brief
from models.model_settings import ModelSettingsError, ModelSettingsStore
from models.resolver import ModelConfigurationError, ModelResolver, sanitize_provider_error
from models.runtime import model_call_context
from security import (
    LOCAL_TENANT_ID,
    LOCAL_USER_ID,
    Principal,
    expiry_iso,
    hash_password,
    new_session_token,
    reset_current_principal,
    set_current_principal,
    token_hash,
    verify_password,
)
from tools.analysis_tools import build_consistency_diagnostics
from tools.canon_conflicts import explain_consistency_issues
from tools.evaluation_benchmark import run_evaluation_benchmark
from tools.evaluation_tools import (
    DETERMINISTIC_SCHEMA_VERSION,
    JUDGE_RUBRIC_VERSION,
    combine_quality_scores,
    compare_evaluations,
    evaluate_chapter_deterministic,
)
from tools.export_tools import export_novel_bytes
from tools.import_tools import parse_import_bytes
from tools.memory_quality import (
    build_memory_eval_cases,
    build_memory_records,
    evaluate_memory_retrieval,
    rebuild_memory_index,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("api")
REVIEW_NODES = {"blueprint_review", "scene_review", "human_review"}
_CHECKPOINT_PREDECESSORS = {
    "blueprint_review": "plot_planner",
    "scene_review": "scene_planner",
    "human_review": "consistency_checker",
    "scene_rewriter": "human_review",
}


class RunJobLeaseLostError(RuntimeError):
    """当前 Worker 已不再拥有后台任务执行权。"""

cfg = Config()
cfg.ensure_dirs()
store = NovelStore(cfg)

# 持久检查点使图实例可共享;这里只保留同一作品的进程内执行互斥。
_novel_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


def _validate_production_config(config: Config) -> None:
    validate_production_config(config)


def get_novel_lock(novel_id: str) -> asyncio.Lock:
    """返回作品级锁;无活动请求后锁可被垃圾回收。"""
    lock = _novel_locks.get(novel_id)
    if lock is None:
        lock = asyncio.Lock()
        _novel_locks[novel_id] = lock
    return lock


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    _validate_production_config(cfg)
    cfg.ensure_dirs()
    worker_id = f"worker_{uuid4().hex}"
    async with AsyncSqliteSaver.from_conn_string(cfg.checkpoint_db_path) as checkpointer:
        await checkpointer.setup()
        recovered_jobs = store.recover_expired_run_jobs()
        if recovered_jobs:
            logger.warning("服务启动时恢复 %s 个租约已过期的任务", recovered_jobs)
        fastapi_app.state.config = cfg
        fastapi_app.state.worker_id = worker_id
        fastapi_app.state.checkpointer = checkpointer
        fastapi_app.state.graph = build_graph(checkpointer=checkpointer)
        fastapi_app.state.model_settings_store = ModelSettingsStore(cfg)
        fastapi_app.state.active_streams = 0
        fastapi_app.state.metrics = {
            "requests_total": 0,
            "requests_failed": 0,
            "requests_4xx": 0,
            "requests_5xx": 0,
            "request_duration_ms_sum": 0.0,
            "request_duration_ms_count": 0,
            "audit_write_failures": 0,
            "started_at": time.time(),
        }
        fastapi_app.state.run_job_tasks = {}
        fastapi_app.state.transfer_tasks = {}
        recovered_transfers = store.recover_transfer_jobs()
        if recovered_transfers:
            logger.warning("服务启动时中断 %s 个未完成传输任务", recovered_transfers)
        fastapi_app.state.shutting_down = False
        fastapi_app.state.lease_reaper_stop = asyncio.Event()
        fastapi_app.state.lease_reaper_task = asyncio.create_task(
            _reap_expired_run_jobs(fastapi_app.state.lease_reaper_stop),
            name=f"run-job-lease-reaper-{worker_id}",
        )
        logger.info(
            "Novel Agent API 启动,环境:%s,存储:%s,检查点:%s",
            cfg.app_environment,
            cfg.sqlite_db_path,
            cfg.checkpoint_db_path,
        )
        yield
        fastapi_app.state.shutting_down = True
        fastapi_app.state.lease_reaper_stop.set()
        fastapi_app.state.lease_reaper_task.cancel()
        with suppress(asyncio.CancelledError):
            await fastapi_app.state.lease_reaper_task
        tasks = list(fastapi_app.state.run_job_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        store.interrupt_run_jobs_by_owner(worker_id, "服务关闭，任务可从检查点继续")
        transfer_tasks = list(fastapi_app.state.transfer_tasks.values())
        for task in transfer_tasks:
            task.cancel()
        if transfer_tasks:
            await asyncio.gather(*transfer_tasks, return_exceptions=True)
        store.recover_transfer_jobs("服务关闭，传输任务可重新发起")


app = FastAPI(title="Multi-Agent 小说创作系统 API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in cfg.frontend_origins.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(model_settings_router)


def _local_principal() -> Principal:
    return Principal(
        user_id=LOCAL_USER_ID,
        tenant_id=LOCAL_TENANT_ID,
        username="local",
        role="owner",
        display_name="本地用户",
    )


def _auth_token(request: Request) -> str:
    value = request.headers.get("Authorization", "")
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def _request_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:120]
    return request.client.host if request.client else "unknown"


def _audit_request(
    request: Request,
    action: str,
    *,
    tenant_id: str | None = None,
    actor_user_id: str | None = None,
    resource_type: str = "",
    resource_id: str = "",
    metadata: dict | None = None,
) -> None:
    try:
        store.append_audit_log(
            action,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata,
            ip_address=_request_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        )
    except Exception:
        metrics = getattr(app.state, "metrics", None)
        if isinstance(metrics, dict):
            metrics["audit_write_failures"] = int(metrics.get("audit_write_failures", 0)) + 1
        logger.exception("写入审计日志失败: %s", action)


def _consume_rate_limit(
    request: Request,
    identifier: str,
    *,
    scope: str,
    window_seconds: int,
    max_attempts: int,
) -> int | None:
    key = token_hash(f"{scope}:{_request_ip(request)}:{identifier.strip().lower()[:200]}")
    try:
        return store.consume_auth_rate_limit(
            key,
            window_seconds=window_seconds,
            max_attempts=max_attempts,
        )
    except Exception as exc:
        logger.exception("共享限流存储不可用: %s", scope)
        raise HTTPException(503, "请求保护暂时不可用") from exc


def _check_auth_rate_limit(request: Request, identifier: str, *, scope: str) -> int | None:
    """按 IP + 标识在共享 SQLite 中原子限制认证尝试。"""
    return _consume_rate_limit(
        request,
        identifier,
        scope=scope,
        window_seconds=cfg.auth_rate_limit_window_seconds,
        max_attempts=cfg.auth_rate_limit_max_attempts,
    )


def _sensitive_scope(path: str, method: str) -> str:
    if method == "POST" and path == "/api/novels/import":
        return "sensitive:import"
    if path.startswith("/api/novels/") and path.endswith(("/export", "/export/jobs")):
        return "sensitive:export"
    if method == "POST" and path.startswith("/api/novels/") and "/jobs/" in path:
        return "sensitive:novel_job"
    if method == "POST" and path == "/api/evaluations/benchmarks":
        return "sensitive:evaluation"
    if method == "POST" and path.startswith("/api/novels/") and path.endswith(("/memory/evaluate", "/memory/rebuild")):
        return "sensitive:memory"
    return ""


def _observe_request(metrics: dict[str, object] | None, started: float, status_code: int) -> None:
    if not isinstance(metrics, dict):
        return
    metrics["request_duration_ms_sum"] = float(metrics.get("request_duration_ms_sum", 0.0)) + (
        time.perf_counter() - started
    ) * 1000
    metrics["request_duration_ms_count"] = int(metrics.get("request_duration_ms_count", 0)) + 1
    if 400 <= status_code < 500:
        metrics["requests_4xx"] = int(metrics.get("requests_4xx", 0)) + 1
    elif status_code >= 500:
        metrics["requests_5xx"] = int(metrics.get("requests_5xx", 0)) + 1


@app.middleware("http")
async def authenticate_request(request: Request, call_next):
    path = request.url.path
    public = path in {"/healthz", "/api/auth/register", "/api/auth/login"}
    started = time.perf_counter()
    metrics = getattr(app.state, "metrics", None)
    if isinstance(metrics, dict):
        metrics["requests_total"] = int(metrics.get("requests_total", 0)) + 1
    principal: Principal | None = None
    raw_token = _auth_token(request)
    if path.startswith("/api") and not public:
        if cfg.auth_enabled:
            if not raw_token:
                response = JSONResponse({"detail": "需要登录"}, status_code=401)
                _observe_request(metrics, started, response.status_code)
                return response
            principal = store.get_session_principal(token_hash(raw_token))
            if principal is None:
                response = JSONResponse({"detail": "会话无效或已过期"}, status_code=401)
                _observe_request(metrics, started, response.status_code)
                return response
        else:
            principal = _local_principal()
    elif path.startswith("/api"):
        principal = store.get_session_principal(token_hash(raw_token)) if raw_token else None
        if principal is None and not cfg.auth_enabled:
            principal = _local_principal()
    if principal is not None:
        request.state.principal = principal
        request.state.auth_token = raw_token
    token = set_current_principal(principal)
    try:
        if (
            cfg.auth_enabled
            and principal is not None
            and principal.role == "viewer"
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and not path.startswith("/api/auth/")
        ):
            response = JSONResponse({"detail": "当前角色只有只读权限"}, status_code=403)
            _observe_request(metrics, started, response.status_code)
            return response
        sensitive_scope = _sensitive_scope(path, request.method)
        if sensitive_scope and principal is not None:
            retry_after = _consume_rate_limit(
                request,
                principal.user_id,
                scope=sensitive_scope,
                window_seconds=cfg.sensitive_rate_limit_window_seconds,
                max_attempts=cfg.sensitive_rate_limit_max_attempts,
            )
            if retry_after is not None:
                _audit_request(
                    request,
                    "request.rate_limited",
                    metadata={"path": path, "retry_after": retry_after},
                )
                response = JSONResponse(
                    {"detail": "敏感操作过于频繁，请稍后再试"},
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                )
                _observe_request(metrics, started, response.status_code)
                return response
        response = await call_next(request)
        _observe_request(metrics, started, response.status_code)
        if isinstance(metrics, dict) and response.status_code >= 400:
            metrics["requests_failed"] = int(metrics.get("requests_failed", 0)) + 1
        if (
            path.startswith("/api/")
            and not path.startswith("/api/auth/")
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        ):
            _audit_request(
                request,
                f"http.{request.method.lower()}",
                metadata={"path": path, "status_code": response.status_code},
            )
        return response
    except Exception:
        _observe_request(metrics, started, 500)
        if isinstance(metrics, dict):
            metrics["requests_failed"] = int(metrics.get("requests_failed", 0)) + 1
        raise
    finally:
        reset_current_principal(token)


BriefItem = Annotated[str, Field(min_length=1, max_length=200)]


class CreativeIntensityRequest(BaseModel):
    romance: int = Field(default=2, ge=0, le=5)
    mystery: int = Field(default=2, ge=0, le=5)
    action: int = Field(default=2, ge=0, le=5)
    darkness: int = Field(default=2, ge=0, le=5)


class CreativeBriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str | None = Field(default=None, max_length=50)
    target_audience: str = Field(default="大众类型小说读者", min_length=1, max_length=200)
    age_rating: Literal["all_ages", "teen", "mature"] = "teen"
    point_of_view: Literal[
        "first_person",
        "third_limited",
        "third_omniscient",
        "multiple",
    ] = "third_limited"
    narrative_tense: Literal["past", "present", "mixed"] = "past"
    narrative_distance: Literal["close", "medium", "distant"] = "medium"
    ending_tone: Literal[
        "unspecified",
        "hopeful",
        "bittersweet",
        "tragic",
        "open",
    ] = "unspecified"
    themes: list[BriefItem] = Field(default_factory=list, max_length=8)
    must_include: list[BriefItem] = Field(default_factory=list, max_length=12)
    avoid_content: list[BriefItem] = Field(default_factory=list, max_length=12)
    intensity: CreativeIntensityRequest = Field(default_factory=CreativeIntensityRequest)
    notes: str = Field(default="", max_length=2000)


class CreativeBriefUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creative_brief: CreativeBriefRequest
    expected_version: int | None = Field(default=None, ge=1)
    change_summary: str = Field(default="", max_length=500)


class CreateNovelRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    genre: str = Field(default="武侠", max_length=20)
    inspiration: str = Field(min_length=1, max_length=2000)
    total_chapters: int = Field(default=3, ge=1, le=50)
    style: str = Field(default="jin_yong", max_length=30)
    planning_review_enabled: bool = False
    creative_brief: CreativeBriefRequest = Field(default_factory=CreativeBriefRequest)


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback: str = Field(default="approve", max_length=5000)
    scene_number: int | None = Field(default=None, ge=1, le=8)
    version_number: int | None = Field(default=None, ge=1)
    candidate_id: str | None = Field(default=None, min_length=1, max_length=80)
    review_type: Literal["blueprint_review", "scene_review", "human_review"] | None = None
    world_bible: str | None = Field(default=None, max_length=100000)
    characters: list[dict[str, Any]] | None = None
    outline: list[dict[str, Any]] | None = None
    scene_plan: list[dict[str, Any]] | None = None


class ChapterEvaluationRequest(BaseModel):
    include_judge: bool = False


class AuthRegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    email: str = Field(default="", max_length=200)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=100)
    tenant_name: str = Field(default="我的工作区", min_length=1, max_length=120)


class AuthLoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class AuthMemberCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    email: str = Field(default="", max_length=200)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=100)
    role: Literal["owner", "editor", "viewer"] = "viewer"


class RoleUpdateRequest(BaseModel):
    role: Literal["owner", "editor", "viewer"]


class EvaluationBenchmarkRequest(BaseModel):
    include_judge: bool = False
    baseline_run_id: str | None = Field(default=None, max_length=80)
    gate_threshold: float = Field(default=70.0, ge=0, le=100)
    regression_threshold: float = Field(default=3.0, ge=0, le=100)


class CandidateGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(default=3, ge=2, le=4)
    instruction: str = Field(default="", max_length=5000)


class BookRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_number: int = Field(ge=1, le=50)
    feedback: str = Field(min_length=1, max_length=5000)


class CanonOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "upsert_fact",
        "deprecate_fact",
        "confirm_fact",
        "merge_alias",
        "update_character",
        "upsert_thread",
        "update_thread_status",
        "upsert_thread_beat",
    ]
    reason: str = Field(min_length=1, max_length=1000)
    target_type: Literal["world_fact", "fact"] | None = None
    target_id: str | None = Field(default=None, max_length=200)
    path: str | None = Field(default=None, max_length=300)
    subject: str | None = Field(default=None, max_length=300)
    kind: str | None = Field(default=None, max_length=100)
    value: str | None = Field(default=None, max_length=500)
    alias: str | None = Field(default=None, max_length=100)
    canonical_name: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=100)
    patch: dict[str, Any] | None = None
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    priority: Literal["major", "minor"] | None = None
    status: Literal["planned", "open", "resolved", "abandoned"] | None = None
    introduced_chapter: int | None = Field(default=None, ge=1, le=50)
    due_chapter: int | None = Field(default=None, ge=1, le=50)
    resolved_chapter: int | None = Field(default=None, ge=1, le=50)
    beat_id: str | None = Field(default=None, max_length=240)
    chapter: int | None = Field(default=None, ge=1, le=50)
    beat_action: Literal["setup", "develop", "resolve"] | None = None
    scene_number: int | None = Field(default=None, ge=1, le=8)


class MemoryQualityRequest(BaseModel):
    k: int = Field(default=5, ge=1, le=20)


class MemoryRebuildRequest(BaseModel):
    evaluate: bool = True
    k: int = Field(default=5, ge=1, le=20)


class TransferExportRequest(BaseModel):
    format: Literal["markdown", "txt", "docx", "epub", "backup"] = "backup"
    password: str = Field(default="", max_length=200)
    author: str = Field(default="", max_length=200)
    publisher: str = Field(default="", max_length=200)
    language: str = Field(default="zh-CN", max_length=30)


def _auth_response(user: dict, token: str, expires_at: str) -> dict:
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": {
            "id": user.get("id", ""),
            "tenant_id": user.get("tenant_id", ""),
            "username": user.get("username", ""),
            "email": user.get("email", ""),
            "display_name": user.get("display_name", ""),
            "role": user.get("role", "viewer"),
            "tenant_name": user.get("tenant_name", ""),
        },
    }


@app.post("/api/auth/register", status_code=201)
async def register_auth_user(req: AuthRegisterRequest, request: Request) -> dict:
    retry_after = _check_auth_rate_limit(request, req.username, scope="register")
    if retry_after is not None:
        _audit_request(request, "auth.register_rate_limited", metadata={"retry_after": retry_after})
        raise HTTPException(429, "认证请求过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
    user_id = f"user_{uuid4().hex}"
    tenant_id = f"tenant_{uuid4().hex}"
    email = req.email.strip().lower() or f"{req.username.lower()}@local.invalid"
    try:
        user = store.create_user_with_tenant(
            user_id=user_id,
            tenant_id=tenant_id,
            username=req.username.strip(),
            email=email,
            display_name=req.display_name.strip() or req.username.strip(),
            password_hash=hash_password(req.password),
            tenant_name=req.tenant_name.strip(),
        )
    except sqlite3.IntegrityError as exc:
        _audit_request(request, "auth.register_failed", metadata={"reason": "duplicate"})
        raise HTTPException(409, "用户名或邮箱已存在") from exc
    token = new_session_token()
    expires_at = expiry_iso(cfg.auth_session_hours)
    store.create_session(f"session_{uuid4().hex}", user_id, token_hash(token), expires_at)
    _audit_request(
        request,
        "auth.registered",
        tenant_id=tenant_id,
        actor_user_id=user_id,
        resource_type="user",
        resource_id=user_id,
    )
    return _auth_response(user, token, expires_at)


@app.post("/api/auth/login")
async def login_auth_user(req: AuthLoginRequest, request: Request) -> dict:
    retry_after = _check_auth_rate_limit(request, req.identifier, scope="login")
    if retry_after is not None:
        _audit_request(request, "auth.login_rate_limited", metadata={"retry_after": retry_after})
        raise HTTPException(429, "认证请求过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
    user = store.get_user_by_login(req.identifier.strip())
    if not user or not verify_password(req.password, str(user.get("password_hash", ""))):
        _audit_request(request, "auth.login_failed", metadata={"reason": "invalid_credentials"})
        raise HTTPException(401, "用户名或密码错误")
    token = new_session_token()
    expires_at = expiry_iso(cfg.auth_session_hours)
    store.create_session(f"session_{uuid4().hex}", str(user["id"]), token_hash(token), expires_at)
    _audit_request(
        request,
        "auth.logged_in",
        tenant_id=str(user["tenant_id"]),
        actor_user_id=str(user["id"]),
        resource_type="session",
    )
    return _auth_response(user, token, expires_at)


@app.get("/api/auth/me")
async def get_auth_me(request: Request) -> dict:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(401, "需要登录")
    user = store.get_user(principal.user_id)
    if user is None:
        raise HTTPException(401, "用户不存在")
    return {"user": user}


@app.post("/api/auth/logout")
async def logout_auth_user(request: Request) -> dict:
    raw_token = getattr(request.state, "auth_token", "")
    if raw_token:
        store.revoke_session(token_hash(raw_token))
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        _audit_request(request, "auth.logged_out", resource_type="session")
    return {"logged_out": True}


@app.post("/api/auth/users", status_code=201)
async def create_auth_member(req: AuthMemberCreateRequest, request: Request) -> dict:
    principal = getattr(request.state, "principal", None)
    if principal is None or principal.role != "owner":
        raise HTTPException(403, "只有工作区所有者可以添加成员")
    user_id = f"user_{uuid4().hex}"
    email = req.email.strip().lower() or f"{req.username.lower()}@local.invalid"
    try:
        user = store.create_user_in_tenant(
            user_id=user_id,
            tenant_id=principal.tenant_id,
            username=req.username.strip(),
            email=email,
            display_name=req.display_name.strip() or req.username.strip(),
            password_hash=hash_password(req.password),
            role=req.role,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "用户名或邮箱已存在") from exc
    _audit_request(
        request,
        "auth.member_created",
        resource_type="user",
        resource_id=user_id,
        metadata={"role": req.role},
    )
    return {"user": user}


@app.get("/api/auth/users")
async def list_auth_members(request: Request) -> dict:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(401, "需要登录")
    return {"users": store.list_users(principal.tenant_id)}


@app.get("/api/audit/logs")
async def list_audit_logs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    action: str = Query(default="", max_length=120),
) -> dict:
    """返回当前租户的操作审计记录；不会跨租户读取。"""
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(401, "需要登录")
    return {"logs": store.list_audit_logs(principal.tenant_id, limit=limit, action=action)}


@app.get("/api/monitoring/summary")
async def monitoring_summary(request: Request) -> dict:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(401, "需要登录")
    return store.get_monitoring_summary(principal.tenant_id)


@app.put("/api/auth/users/{user_id}/role")
async def update_auth_user_role(user_id: str, req: RoleUpdateRequest, request: Request) -> dict:
    principal = getattr(request.state, "principal", None)
    if principal is None or principal.role != "owner":
        raise HTTPException(403, "只有工作区所有者可以管理成员")
    target = store.get_user(user_id)
    if target is None or target.get("tenant_id") != principal.tenant_id:
        raise HTTPException(404, "成员不存在")
    if user_id == principal.user_id and req.role != "owner":
        raise HTTPException(409, "不能降级当前唯一所有者")
    updated = store.update_user_role(user_id, principal.tenant_id, req.role)
    _audit_request(
        request,
        "auth.role_updated",
        resource_type="user",
        resource_id=user_id,
        metadata={"role": req.role},
    )
    return {"user": updated}


@app.post("/api/novels")
async def create_novel(req: CreateNovelRequest) -> dict:
    novel_id = f"novel_{uuid4().hex[:8]}"
    return store.create_novel(
        novel_id,
        req.title,
        req.genre,
        req.style,
        req.total_chapters,
        req.inspiration,
        req.planning_review_enabled,
        normalize_creative_brief(req.creative_brief.model_dump()),
    )


@app.get("/api/novels")
async def list_novels() -> list[dict]:
    return store.list_novels()


async def _persist_imported_payload(
    parsed: dict[str, Any],
    *,
    title: str = "",
    source_format: str = "",
) -> dict:
    """持久化已解析的导入载荷，供同步 API 和后台传输任务共用。"""
    source_novel = parsed.get("novel") or {}
    chapters: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in parsed.get("chapters") or []:
        if not isinstance(item, dict):
            continue
        number = int(item.get("chapter_number", item.get("chapter", 0)) or 0)
        content = str(item.get("content", "")).strip()
        if number < 1 or not content or number in seen:
            continue
        seen.add(number)
        chapters.append({
            "chapter_number": number,
            "title": str(item.get("title", ""))[:200],
            "content": content,
            "summary": str(item.get("summary", content[:500]))[:500],
            "status": "final",
        })
    chapters.sort(key=lambda item: item["chapter_number"])
    if not chapters:
        raise HTTPException(422, "导入文件没有可用章节")
    novel_id = f"novel_{uuid4().hex[:12]}"
    last_chapter = max(int(item["chapter_number"]) for item in chapters)
    total_chapters = max(int(source_novel.get("total_chapters", 0) or 0), last_chapter, 1)
    default_next_chapter = last_chapter + 1
    default_phase = "completed" if last_chapter >= total_chapters else "writing"
    created = store.create_novel(
        novel_id=novel_id,
        title=(title.strip() or str(source_novel.get("title", "导入作品")))[:100],
        genre=str(source_novel.get("genre", ""))[:20],
        style=str(source_novel.get("style", ""))[:30],
        total_chapters=total_chapters,
        inspiration=str(source_novel.get("inspiration", "导入作品"))[:2000],
        planning_review_enabled=bool(source_novel.get("planning_review_enabled", False)),
        creative_brief=source_novel.get("creative_brief"),
    )
    try:
        for chapter in chapters:
            store.save_chapter(
                novel_id=novel_id,
                chapter_number=chapter["chapter_number"],
                title=chapter["title"],
                content=chapter["content"],
                summary=chapter["summary"],
                status="final",
            )
        source_progress = parsed.get("progress") or {}
        checkpoint = parsed.get("checkpoint") or {}
        checkpoint_state = checkpoint.get("state") if isinstance(checkpoint, dict) else {}
        source_state = checkpoint_state or (
            source_progress.get("state") if isinstance(source_progress, dict) else {}
        )
        state = dict(source_state) if isinstance(source_state, dict) else {}
        state.update({
            "novel_id": novel_id,
            "chapters": chapters,
            "total_chapters": total_chapters,
        })
        if not checkpoint_state:
            state.update({
                "current_chapter": default_next_chapter,
                "current_phase": default_phase,
            })
        else:
            state.setdefault("current_chapter", default_next_chapter)
            state.setdefault("current_phase", default_phase)
        store.save_progress(novel_id, int(state["current_chapter"]), str(state["current_phase"]), state)
        for snapshot in parsed.get("memory_snapshots") or []:
            if isinstance(snapshot, dict) and isinstance(snapshot.get("payload"), dict):
                store.save_memory_snapshot(
                    novel_id,
                    schema_version=str(snapshot.get("schema_version", "")),
                    content_hash=str(snapshot.get("content_hash", "")),
                    payload=snapshot["payload"],
                )
        for run in parsed.get("memory_quality_runs") or []:
            if isinstance(run, dict) and isinstance(run.get("report"), dict):
                store.save_memory_quality_run(
                    novel_id,
                    mode=str(run.get("mode", "imported")),
                    index_hash=str(run.get("index_hash", "")),
                    report=run["report"],
                )
        await _restore_imported_checkpoint(novel_id, state, checkpoint)
        records = build_memory_records(
            novel_id=novel_id,
            world_bible=str(state.get("world_bible", "")),
            characters=state.get("characters") or [],
            outline=state.get("outline") or [],
            chapters=chapters,
            canon=state.get("canon") or {},
            memory_index=state.get("memory_index") or {},
        )
        memory_rebuild = {"status": "skipped", "record_count": 0}
        try:
            memory_rebuild = {
                "status": "completed",
                **rebuild_memory_index(NovelMemory(novel_id), records),
            }
        except Exception as exc:
            memory_rebuild = {
                "status": "failed",
                "error": type(exc).__name__,
                "record_count": len(records),
            }
            logger.warning("导入后记忆重建失败(%s)", type(exc).__name__)
    except Exception:
        checkpointer = getattr(app.state, "checkpointer", None)
        if checkpointer is not None:
            with suppress(Exception):
                await checkpointer.adelete_thread(novel_id)
        store.delete_novel(novel_id)
        raise
    return {
        "novel": {**created, "chapters": chapters},
        "imported_chapters": len(chapters),
        "source_format": source_format,
        "memory_rebuild": memory_rebuild,
    }


def _transfer_output_dir(job_id: str) -> Path:
    base = Path(cfg.transfer_dir).resolve()
    target = (base / job_id).resolve()
    if not target.is_relative_to(base):
        raise ValueError("传输任务路径无效")
    target.mkdir(parents=True, exist_ok=True)
    return target


async def _execute_transfer_job(job_id: str, password: str = "") -> None:
    """后台执行导入/导出，密码只存在于当前进程内存。"""
    job = store.get_transfer_job(job_id)
    if job is None:
        return
    try:
        store.update_transfer_job(job_id, status="running", error="")
        request = job.get("request") or {}
        if job.get("kind") == "export":
            novel_id = str(job.get("novel_id") or request.get("novel_id") or "")
            novel = store.get_novel(novel_id)
            if not novel:
                raise ValueError("小说不存在")
            checkpoint = {}
            snapshot = await _graph().aget_state({"configurable": {"thread_id": novel_id}})
            if snapshot.values:
                checkpoint = {
                    "schema_version": "langgraph-checkpoint-v1",
                    "state": snapshot.values,
                    "next": list(snapshot.next or ()),
                    "metadata": snapshot.metadata or {},
                }
            chapters, progress, memory_snapshots, quality_runs = await asyncio.to_thread(
                lambda: (
                    store.get_all_chapters(novel_id),
                    store.get_progress(novel_id),
                    store.list_memory_snapshots(novel_id),
                    store.list_memory_quality_runs(novel_id),
                )
            )
            filename, media_type, payload = await asyncio.to_thread(
                export_novel_bytes,
                novel,
                chapters,
                str(request.get("format", "backup")),
                progress=progress,
                memory_snapshots=memory_snapshots,
                memory_quality_runs=quality_runs,
                checkpoint=checkpoint,
                password=password,
                metadata=request.get("metadata") or {},
            )
            output_path = _transfer_output_dir(job_id) / filename
            await asyncio.to_thread(output_path.write_bytes, payload)
            store.update_transfer_job(
                job_id,
                status="completed",
                output_path=str(output_path),
                result={
                    "filename": filename,
                    "media_type": media_type,
                    "size": len(payload),
                    "novel_id": novel_id,
                },
            )
        elif job.get("kind") == "import":
            input_path = Path(str(job.get("input_path") or "")).resolve()
            transfer_root = Path(cfg.transfer_dir).resolve()
            if not input_path.is_relative_to(transfer_root) or not input_path.is_file():
                raise ValueError("导入暂存文件不存在")
            data = await asyncio.to_thread(input_path.read_bytes)
            if len(data) > max(int(cfg.max_import_bytes), 1):
                raise ValueError("导入文件超过大小限制")
            parsed = await asyncio.to_thread(
                parse_import_bytes,
                data,
                str(request.get("filename", "import.txt")),
                str(request.get("format", "")),
                password,
            )
            result = await _persist_imported_payload(
                parsed,
                title=str(request.get("title", "")),
                source_format=str(request.get("format") or request.get("filename") or ""),
            )
            store.update_transfer_job(job_id, status="completed", result=result)
        else:
            raise ValueError("未知传输任务类型")
    except asyncio.CancelledError:
        store.update_transfer_job(job_id, status="interrupted", error="传输任务被中断")
        raise
    except Exception as exc:
        message = sanitize_provider_error(exc, _configured_model_secrets())
        logger.error("传输任务失败(%s, %s): %s", job_id, type(exc).__name__, message)
        store.update_transfer_job(job_id, status="failed", error=message)
    finally:
        input_path = str(job.get("input_path") or "")
        if input_path:
            with suppress(OSError):
                Path(input_path).unlink()
        tasks = getattr(app.state, "transfer_tasks", {})
        tasks.pop(job_id, None)


def _schedule_transfer_job(job: dict, password: str = "") -> None:
    tasks = getattr(app.state, "transfer_tasks", None)
    if tasks is None:
        app.state.transfer_tasks = {}
        tasks = app.state.transfer_tasks
    task = asyncio.create_task(
        _execute_transfer_job(str(job["id"]), password),
        name=f"transfer-{job['id']}",
    )
    tasks[str(job["id"])] = task


def _transfer_job_allowed(job: dict | None, request: Request) -> bool:
    if job is None:
        return False
    principal = getattr(request.state, "principal", None)
    return not cfg.auth_enabled or principal is not None and job.get("tenant_id") == principal.tenant_id


@app.post("/api/novels/import")
async def import_novel(
    file: UploadFile = File(...),
    title: str = Query(default="", max_length=100),
    format: str = Query(default="", max_length=20),
    password: str = Form(default="", max_length=200),
) -> dict:
    """导入文本、DOCX、EPUB 或 Novel Agent ZIP 备份为当前工作区的新作品。"""
    data = await file.read()
    if not data:
        raise HTTPException(422, "导入文件为空")
    if len(data) > max(int(cfg.max_import_bytes), 1):
        raise HTTPException(413, "导入文件超过大小限制")
    if len(data) >= max(int(cfg.background_transfer_bytes), 1):
        job_id = f"transfer_{uuid4().hex[:12]}"
        input_dir = _transfer_output_dir(job_id)
        input_path = input_dir / "input.bin"
        input_path.write_bytes(data)
        job = store.create_transfer_job(
            job_id,
            "import",
            {
                "filename": file.filename or "import.txt",
                "format": format,
                "title": title,
            },
            input_path=str(input_path),
        )
        _schedule_transfer_job(job, password)
        return JSONResponse(status_code=202, content={"job": job})
    try:
        parsed = parse_import_bytes(data, file.filename or "import.txt", format, password)
    except (ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise HTTPException(422, f"导入文件解析失败:{exc}") from exc
    return await _persist_imported_payload(
        parsed,
        title=title,
        source_format=format or file.filename or "",
    )


@app.delete("/api/novels/{novel_id}")
async def delete_novel(novel_id: str, request: Request) -> dict:
    """删除作品及其持久化现场;向量记忆清理失败不阻断主数据删除。"""
    principal = getattr(request.state, "principal", None)
    if cfg.auth_enabled and (principal is None or principal.role != "owner"):
        raise HTTPException(403, "只有工作区所有者可以删除作品")
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")

    lock = get_novel_lock(novel_id)
    await lock.acquire()
    try:
        checkpointer = getattr(app.state, "checkpointer", None)
        if checkpointer is not None:
            await checkpointer.adelete_thread(novel_id)
        if not store.delete_novel(novel_id):
            raise HTTPException(404, "小说不存在")
        settings_store = getattr(app.state, "model_settings_store", None)
        if settings_store is not None:
            try:
                settings_store.delete_novel_metrics(novel_id)
            except Exception as exc:
                logger.warning("作品模型用量清理失败(%s, %s)", novel_id, type(exc).__name__)
        try:
            NovelMemory(novel_id).clear()
        except Exception as exc:
            logger.warning("作品向量记忆清理失败(%s, %s)", novel_id, type(exc).__name__)
        return {"deleted": True, "novel_id": novel_id}
    finally:
        lock.release()


@app.get("/api/novels/{novel_id}")
async def get_novel(novel_id: str) -> dict:
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    novel["chapters"] = store.get_all_chapters(novel_id)
    return novel


@app.get("/api/novels/{novel_id}/export")
async def export_novel(
    novel_id: str,
    format: str = Query(default="markdown", max_length=20),
    password: str = Header(default="", alias="X-Backup-Password", max_length=200),
    background: bool = Query(default=False),
    author: str = Query(default="", max_length=200),
    publisher: str = Query(default="", max_length=200),
    language: str = Query(default="zh-CN", max_length=30),
) -> Any:
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    chapters = store.get_all_chapters(novel_id)
    estimated_size = sum(len(str(item.get("content", "")).encode("utf-8")) for item in chapters)
    if background or estimated_size >= max(int(cfg.background_transfer_bytes), 1):
        job = store.create_transfer_job(
            f"transfer_{uuid4().hex[:12]}",
            "export",
            {
                "novel_id": novel_id,
                "format": format,
                "metadata": {"author": author, "publisher": publisher, "language": language},
            },
            novel_id=novel_id,
        )
        _schedule_transfer_job(job, password)
        return JSONResponse(status_code=202, content={"job": job})
    try:
        checkpoint = {}
        snapshot = await _graph().aget_state({"configurable": {"thread_id": novel_id}})
        if snapshot.values:
            checkpoint = {
                "schema_version": "langgraph-checkpoint-v1",
                "state": snapshot.values,
                "next": list(snapshot.next or ()),
                "metadata": snapshot.metadata or {},
            }
        filename, media_type, payload = export_novel_bytes(
            novel,
            chapters,
            format,
            progress=store.get_progress(novel_id),
            memory_snapshots=store.list_memory_snapshots(novel_id),
            memory_quality_runs=store.list_memory_quality_runs(novel_id),
            checkpoint=checkpoint,
            password=password,
            metadata={"author": author, "publisher": publisher, "language": language},
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(io.BytesIO(payload), media_type=media_type, headers=headers)


@app.post("/api/novels/{novel_id}/export/jobs")
async def create_export_transfer_job(
    novel_id: str,
    req: TransferExportRequest,
) -> dict:
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    job = store.create_transfer_job(
        f"transfer_{uuid4().hex[:12]}",
        "export",
        {
            "novel_id": novel_id,
            "format": req.format,
            "metadata": {
                "author": req.author,
                "publisher": req.publisher,
                "language": req.language,
            },
        },
        novel_id=novel_id,
    )
    _schedule_transfer_job(job, req.password)
    return {"job": job}


@app.get("/api/transfers/{job_id}")
async def get_transfer_job(job_id: str, request: Request) -> dict:
    job = store.get_transfer_job(job_id)
    if not _transfer_job_allowed(job, request):
        raise HTTPException(404, "传输任务不存在")
    return job


@app.post("/api/transfers/{job_id}/cancel")
async def cancel_transfer_job(job_id: str, request: Request) -> dict:
    job = store.get_transfer_job(job_id)
    if not _transfer_job_allowed(job, request):
        raise HTTPException(404, "传输任务不存在")
    if job.get("status") not in {"queued", "running"}:
        raise HTTPException(409, "传输任务已结束，无法取消")
    task = getattr(app.state, "transfer_tasks", {}).get(job_id)
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    store.update_transfer_job(job_id, status="cancelled", error="传输任务已取消")
    return store.get_transfer_job(job_id)


@app.get("/api/transfers/{job_id}/download")
async def download_transfer_job(job_id: str, request: Request) -> FileResponse:
    job = store.get_transfer_job(job_id)
    if not _transfer_job_allowed(job, request):
        raise HTTPException(404, "传输任务不存在")
    if job.get("status") != "completed" or job.get("kind") != "export":
        raise HTTPException(409, "传输文件尚未准备好")
    output_path = Path(str(job.get("output_path") or "")).resolve()
    transfer_root = Path(cfg.transfer_dir).resolve()
    if not output_path.is_relative_to(transfer_root) or not output_path.is_file():
        raise HTTPException(404, "传输文件不存在")
    result = job.get("result") or {}
    return FileResponse(
        output_path,
        media_type=str(result.get("media_type") or "application/octet-stream"),
        filename=str(result.get("filename") or output_path.name),
    )


@app.get("/api/novels/{novel_id}/creative-brief/versions")
async def list_creative_brief_versions(novel_id: str) -> list[dict]:
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    return store.list_creative_brief_versions(novel_id)


@app.put("/api/novels/{novel_id}/creative-brief")
async def update_novel_creative_brief(
    novel_id: str,
    req: CreativeBriefUpdateRequest,
) -> dict:
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    active_job = store.get_active_run_job(novel_id)
    if active_job:
        raise HTTPException(409, "作品正在运行，暂时不能修改创作约束")

    lock = get_novel_lock(novel_id)
    await lock.acquire()
    try:
        novel = store.get_novel(novel_id)
        if not novel:
            raise HTTPException(404, "小说不存在")
        current_version = int(novel.get("creative_brief_version", 1) or 1)
        if req.expected_version is not None and req.expected_version != current_version:
            raise HTTPException(
                409,
                f"创作约束已更新，当前版本为 v{current_version}",
            )
        normalized = normalize_creative_brief(req.creative_brief.model_dump())
        changed = normalized != normalize_creative_brief(novel.get("creative_brief"))
        if changed:
            updated = store.update_creative_brief(
                novel_id,
                normalized,
                change_summary=req.change_summary,
            )
            if updated is None:
                raise HTTPException(404, "小说不存在")
            stale_candidates = store.invalidate_chapter_candidates(novel_id)
            snapshot = await _ensure_checkpoint_creative_brief(novel_id, updated)
        else:
            updated = novel
            stale_candidates = 0
            snapshot = await _ensure_checkpoint_creative_brief(novel_id, updated)
        values = snapshot.values or {}
        return {
            **updated,
            "changed": changed,
            "stale_candidate_count": stale_candidates,
            "requires_revalidation": bool(
                values.get("creative_brief_review_required", False)
            ),
        }
    finally:
        lock.release()


@app.get("/api/novels/{novel_id}/state")
async def get_novel_state(novel_id: str) -> dict:
    """返回前端恢复工作台所需的只读状态摘要。"""
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")

    graph_config = {"configurable": {"thread_id": novel_id}}
    snapshot = await _graph().aget_state(graph_config)
    values = snapshot.values or {}
    if not values:
        values = (store.get_progress(novel_id) or {}).get("state") or {}
    canon = values.get("canon") or {}
    chapters = store.get_all_chapters(novel_id)
    total = int(novel.get("total_chapters") or 0)
    next_nodes = list(snapshot.next or ())
    review_node = next((node for node in next_nodes if node in REVIEW_NODES), "")

    run_job = store.get_latest_run_job(novel_id)
    if run_job and run_job.get("status") in {"queued", "running"}:
        status = "running"
    elif review_node:
        status = review_node
    elif next_nodes:
        status = "error" if run_job and run_job.get("status") == "failed" else "interrupted"
    elif values:
        status = "completed" if len(values.get("chapters") or []) >= total else "error"
    elif chapters:
        status = "completed" if len(chapters) >= total else "legacy_read_only"
    else:
        status = "idle"

    settings_store = getattr(app.state, "model_settings_store", None)
    empty_usage = {
        "attempts": 0,
        "successful_calls": 0,
        "failed_attempts": 0,
        "fallback_attempts": 0,
        "duration_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_attempts": 0,
        "by_agent": [],
    }
    try:
        model_usage = settings_store.get_model_usage(novel_id) if settings_store else empty_usage
    except Exception as exc:
        logger.warning("作品模型用量读取失败(%s, %s)", novel_id, type(exc).__name__)
        model_usage = empty_usage

    current_chapter = int(values.get("current_chapter", len(chapters) + 1))
    memory_index = values.get("memory_index") or {}
    if not memory_index:
        try:
            memory_snapshot = store.get_latest_memory_snapshot(novel_id)
            memory_index = (memory_snapshot or {}).get("payload") or {}
        except Exception as exc:
            logger.warning("分层记忆读取失败(%s, %s)", novel_id, type(exc).__name__)
    if not memory_index and chapters:
        memory_index = build_hierarchical_memory(chapters, total_chapters=total)
    book_audit = values.get("book_audit") or {}
    if not book_audit:
        try:
            stored_audit = store.get_latest_book_audit(novel_id)
            book_audit = (stored_audit or {}).get("report") or {}
        except Exception as exc:
            logger.warning("全书审计读取失败(%s, %s)", novel_id, type(exc).__name__)
    planning_versions: list[dict] = []
    chapter_candidates: list[dict] = []
    try:
        if review_node == "blueprint_review":
            planning_versions = store.list_planning_versions(novel_id, "blueprint", 0)
        elif review_node == "scene_review":
            planning_versions = store.list_planning_versions(
                novel_id,
                "scene",
                current_chapter,
            )
        elif review_node == "human_review":
            chapter_candidates = store.list_chapter_candidates(
                novel_id,
                current_chapter,
            )
    except Exception as exc:
        logger.warning("规划版本历史读取失败(%s, %s)", novel_id, type(exc).__name__)
    return {
        "novel_id": novel_id,
        "status": status,
        "current_chapter": current_chapter,
        "current_phase": values.get("current_phase", "idle"),
        "chapters_done": len(values.get("chapters") or chapters),
        "total_chapters": total,
        "next": next_nodes,
        "review_node": review_node,
        "planning_review_enabled": bool(
            values.get("planning_review_enabled", novel.get("planning_review_enabled", False))
        ),
        "creative_brief": normalize_creative_brief(novel.get("creative_brief")),
        "creative_brief_version": int(novel.get("creative_brief_version", 1) or 1),
        "creative_brief_review_required": bool(
            values.get("creative_brief_review_required", False)
        ),
        "world_bible": values.get("world_bible", ""),
        "characters": values.get("characters") or [],
        "outline": values.get("outline") or [],
        "replan_proposal": values.get("replan_proposal") or {},
        "chapter_plan": values.get("chapter_plan") or {},
        "scene_plan": values.get("scene_plan") or [],
        "planning_versions": planning_versions,
        "chapter_candidates": chapter_candidates,
        "current_draft": values.get("current_draft") or {},
        "issues": values.get("issues") or [],
        "quality_report": values.get("quality_report") or None,
        "book_audit": book_audit or None,
        "persistence_error": values.get("persistence_error", ""),
        "versions": store.list_chapter_versions(
            novel_id,
            current_chapter,
        ),
        "evaluations": store.list_chapter_evaluations(novel_id, current_chapter),
        "run_job": run_job,
        "model_usage": model_usage,
        "memory": {
            "schema_version": memory_index.get("schema_version", ""),
            "chapters": int(memory_index.get("completed_chapters", 0) or 0),
            "arcs": len(memory_index.get("arcs") or []),
        },
        "canon": {
            "version": canon.get("version", 0),
            "world_facts": sum(
                item.get("status", "active") == "active"
                for item in (canon.get("world_facts") or [])
            ),
            "characters": len(canon.get("characters") or {}),
            "timeline_entries": len(canon.get("timeline") or []),
            "confirmed_facts": sum(
                item.get("status", "active") == "active"
                for item in (canon.get("facts") or [])
            ),
            "deprecated_facts": sum(
                item.get("status") == "deprecated"
                for item in [
                    *(canon.get("world_facts") or []),
                    *(canon.get("facts") or []),
                ]
            ),
            "aliases": len(canon.get("aliases") or {}),
            "audit_entries": len(canon.get("audit") or []),
            "narrative_threads": len(canon.get("narrative_threads") or []),
            "open_threads": sum(
                item.get("status", "planned") in {"planned", "open"}
                for item in (canon.get("narrative_threads") or [])
            ),
            "resolved_threads": sum(
                item.get("status") == "resolved"
                for item in (canon.get("narrative_threads") or [])
            ),
            "overdue_threads": sum(
                item.get("status", "planned") in {"planned", "open"}
                and int(item.get("due_chapter", 0) or 0) > 0
                and int(item.get("due_chapter", 0) or 0)
                < int(values.get("current_chapter", len(chapters) + 1) or 0)
                for item in (canon.get("narrative_threads") or [])
            ),
        },
    }


@app.get("/api/novels/{novel_id}/book-audits")
async def list_book_audits(novel_id: str) -> list[dict]:
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    return store.list_book_audits(novel_id)


@app.get("/api/novels/{novel_id}/chapters/{chapter_number}/candidates")
async def list_chapter_candidates(novel_id: str, chapter_number: int) -> list[dict]:
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    return store.list_chapter_candidates(novel_id, chapter_number)


async def _memory_sources(novel_id: str, novel: dict) -> dict[str, Any]:
    snapshot = await _graph().aget_state({"configurable": {"thread_id": novel_id}})
    values = snapshot.values or {}
    if not values:
        values = (store.get_progress(novel_id) or {}).get("state") or {}
    chapters = [dict(item) for item in (values.get("chapters") or store.get_all_chapters(novel_id))]
    total = int(values.get("total_chapters", novel.get("total_chapters", len(chapters))) or len(chapters))
    canon = ensure_canon(
        values.get("canon"),
        world_bible=str(values.get("world_bible", "")),
        characters=values.get("characters") or [],
        outline=values.get("outline") or [],
        chapters=chapters,
    )
    memory_index = build_hierarchical_memory(chapters, total_chapters=total)
    return {
        "values": values,
        "chapters": chapters,
        "world_bible": str(values.get("world_bible", "")),
        "characters": values.get("characters") or [],
        "outline": values.get("outline") or [],
        "canon": canon,
        "memory_index": memory_index,
        "total_chapters": total,
    }


@app.get("/api/novels/{novel_id}/memory")
async def get_novel_memory(novel_id: str) -> dict:
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    return (await _memory_sources(novel_id, novel))["memory_index"]


@app.get("/api/novels/{novel_id}/memory/quality")
async def list_memory_quality(
    novel_id: str,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    runs = store.list_memory_quality_runs(novel_id, limit)
    return {"latest": runs[0] if runs else None, "runs": runs}


@app.post("/api/novels/{novel_id}/memory/evaluate")
async def evaluate_novel_memory(novel_id: str, req: MemoryQualityRequest) -> dict:
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    sources = await _memory_sources(novel_id, novel)
    cases = build_memory_eval_cases(
        novel_id=novel_id,
        world_bible=sources["world_bible"],
        characters=sources["characters"],
        outline=sources["outline"],
        chapters=sources["chapters"],
        canon=sources["canon"],
    )
    try:
        memory = NovelMemory(novel_id)
        report = evaluate_memory_retrieval(memory=memory, cases=cases, k=req.k)
    except Exception as exc:
        report = {
            "schema_version": "memory-quality-v1",
            "k": req.k,
            "case_count": len(cases),
            "passed_cases": 0,
            "index_record_count": 0,
            "index_hash": "",
            "recall_at_k": 0.0,
            "precision_at_k": 0.0,
            "mrr": 0.0,
            "stale_fact_hit_rate": 0.0,
            "canon_vector_conflict_rate": 0.0,
            "category_metrics": {},
            "cases": [],
            "errors": [f"向量记忆不可用:{type(exc).__name__}"],
            "status": "unavailable",
        }
    report["novel_id"] = novel_id
    saved = store.save_memory_quality_run(
        novel_id,
        mode="evaluate",
        index_hash=str(report.get("index_hash", "")),
        report=report,
    )
    return saved


@app.post("/api/novels/{novel_id}/memory/rebuild")
async def rebuild_novel_memory(novel_id: str, req: MemoryRebuildRequest) -> dict:
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    if store.get_active_run_job(novel_id):
        raise HTTPException(409, "作品已有活动任务，请等待任务结束后重建记忆")
    lock = get_novel_lock(novel_id)
    await lock.acquire()
    try:
        sources = await _memory_sources(novel_id, novel)
        records = build_memory_records(
            novel_id=novel_id,
            world_bible=sources["world_bible"],
            characters=sources["characters"],
            outline=sources["outline"],
            chapters=sources["chapters"],
            canon=sources["canon"],
            memory_index=sources["memory_index"],
        )
        try:
            memory = NovelMemory(novel_id)
            rebuild = rebuild_memory_index(memory, records)
        except Exception as exc:
            raise HTTPException(503, f"向量记忆重建失败:{type(exc).__name__}") from exc
        try:
            store.save_memory_snapshot(
                novel_id,
                schema_version=str(sources["memory_index"].get("schema_version", "")),
                content_hash=hierarchical_memory_hash(sources["memory_index"]),
                payload=sources["memory_index"],
            )
        except Exception as exc:
            logger.warning("记忆重建后快照写入失败(%s)", type(exc).__name__)
        quality = None
        if req.evaluate:
            cases = build_memory_eval_cases(
                novel_id=novel_id,
                world_bible=sources["world_bible"],
                characters=sources["characters"],
                outline=sources["outline"],
                chapters=sources["chapters"],
                canon=sources["canon"],
            )
            quality = evaluate_memory_retrieval(memory=memory, cases=cases, k=req.k)
        report = {"novel_id": novel_id, "rebuild": rebuild, "quality": quality}
        saved = store.save_memory_quality_run(
            novel_id,
            mode="rebuild",
            index_hash=str(rebuild.get("index_hash", "")),
            report=report,
        )
        return {"run": saved, "memory": sources["memory_index"], "rebuild": rebuild, "quality": quality}
    finally:
        lock.release()


@app.get("/api/novels/{novel_id}/canon")
async def get_novel_canon(novel_id: str) -> dict:
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    snapshot = await _graph().aget_state({"configurable": {"thread_id": novel_id}})
    values = snapshot.values or {}
    if not values:
        values = (store.get_progress(novel_id) or {}).get("state") or {}
    if not values:
        return empty_canon()
    return ensure_canon(
        values.get("canon"),
        world_bible=str(values.get("world_bible", "")),
        characters=values.get("characters") or [],
        outline=values.get("outline") or [],
        chapters=values.get("chapters") or [],
    )


@app.get("/api/novels/{novel_id}/conflicts")
async def get_novel_conflicts(
    novel_id: str,
    chapter_number: int | None = Query(default=None, ge=1, le=50),
) -> dict:
    """返回当前章节的一致性冲突解释；只读，不改变 Canon 或检查点。"""
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    snapshot = await _graph().aget_state({"configurable": {"thread_id": novel_id}})
    values = snapshot.values or {}
    stored_chapters = values.get("chapters") or store.get_all_chapters(novel_id)
    draft = dict(values.get("current_draft") or {})
    selected_number = int(
        chapter_number
        or draft.get("chapter_number", values.get("current_chapter", 0))
        or 0
    )
    if selected_number < 1:
        return {"chapter_number": 0, "issues": [], "report": "", "canon_version": 0}
    chapter = next(
        (
            dict(item)
            for item in [draft, *stored_chapters]
            if int(item.get("chapter_number", item.get("chapter", 0)) or 0) == selected_number
            and (item.get("content") is not None or item is draft)
        ),
        draft if int(draft.get("chapter_number", 0) or 0) == selected_number else None,
    )
    if chapter is None:
        return {"chapter_number": selected_number, "issues": [], "report": "", "canon_version": 0}
    previous_chapters = [
        dict(item)
        for item in stored_chapters
        if int(item.get("chapter_number", item.get("chapter", 0)) or 0) < selected_number
    ]
    canon = ensure_canon(
        values.get("canon"),
        world_bible=str(values.get("world_bible", "")),
        characters=values.get("characters") or [],
        outline=values.get("outline") or [],
        chapters=stored_chapters,
    )
    issues, report = build_consistency_diagnostics(
        chapter=chapter,
        characters=values.get("characters") or [],
        outline=values.get("outline") or [],
        previous_chapters=previous_chapters,
        max_chapter_words=int(values.get("max_chapter_words", cfg.max_chapter_words) or 0),
        canon=canon,
        total_chapters=int(values.get("total_chapters", novel.get("total_chapters", 0)) or 0) or None,
        creative_brief=values.get("creative_brief") or novel.get("creative_brief"),
    )
    return {
        "chapter_number": selected_number,
        "issues": explain_consistency_issues(
            issues=issues,
            chapter=chapter,
            previous_chapters=previous_chapters,
            canon=canon,
            outline=values.get("outline") or [],
        ),
        "report": report,
        "canon_version": canon.get("version", 0),
    }


@app.post("/api/novels/{novel_id}/canon")
async def update_novel_canon(
    novel_id: str,
    req: CanonOperationRequest,
) -> StreamingResponse:
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")

    lock = get_novel_lock(novel_id)
    await lock.acquire()
    try:
        snapshot = await _ensure_checkpoint_creative_brief(novel_id, novel)
        if not snapshot.next or "human_review" not in snapshot.next:
            raise HTTPException(409, "Canon 仅可在人工审查阶段修改")
        values = snapshot.values or {}
        operation = req.model_dump(exclude_unset=True)
        try:
            apply_canon_operation(
                ensure_canon(
                    values.get("canon"),
                    world_bible=str(values.get("world_bible", "")),
                    characters=values.get("characters") or [],
                    outline=values.get("outline") or [],
                    chapters=values.get("chapters") or [],
                ),
                operation,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        _validate_model_runtime()
        app.state.active_streams += 1
        return StreamingResponse(
            _stream_graph(
                novel_id,
                Command(resume={"action": "canon_update", "operation": operation}),
                lock,
            ),
            media_type="application/x-ndjson",
        )
    except Exception:
        if lock.locked():
            lock.release()
        raise


@app.get("/api/novels/{novel_id}/usage")
async def get_novel_usage(novel_id: str) -> dict:
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    return app.state.model_settings_store.get_model_usage(novel_id)


@app.get("/api/novels/{novel_id}/traces")
async def list_novel_traces(
    novel_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    agent: str = Query(default="", max_length=120),
) -> list[dict]:
    """返回最近模型调用轨迹;仅包含哈希和统计元数据,不返回 Prompt/正文。"""
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    return app.state.model_settings_store.list_model_traces(
        novel_id,
        limit=limit,
        agent=agent,
    )


@app.get("/api/evaluations/benchmarks")
async def list_evaluation_benchmarks(
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    return store.list_evaluation_benchmarks(limit)


@app.get("/api/evaluations/benchmarks/{run_id}")
async def get_evaluation_benchmark(run_id: str) -> dict:
    record = store.get_evaluation_benchmark(run_id)
    if record is None:
        raise HTTPException(404, "评测运行不存在")
    return record


@app.post("/api/evaluations/benchmarks")
async def create_evaluation_benchmark(req: EvaluationBenchmarkRequest) -> dict:
    baseline = None
    if req.baseline_run_id:
        baseline = store.get_evaluation_benchmark(req.baseline_run_id)
        if baseline is None:
            raise HTTPException(404, "评测基准不存在")

    judge_case = None
    model_provider = ""
    model_name = ""
    judge_setup_error = ""
    if req.include_judge:
        try:
            resolver = ModelResolver(config=cfg, store=app.state.model_settings_store)
            resolved = resolver.resolve_chat_candidates("analysis")[0]
            model_provider = resolved.provider
            model_name = resolved.model_name
            evaluator = QualityEvaluatorAgent(
                llm=resolver.chat("analysis", temperature=0.0, streaming=False)
            )

            async def judge_case(sample: dict, deterministic: dict) -> dict:
                with model_call_context("evaluation_benchmark", "quality_evaluator"):
                    return await evaluator.evaluate(
                        novel={
                            "title": "固定质量评测样本",
                            "genre": "悬疑武侠",
                            "style": "克制、清晰、推进有力",
                            "inspiration": sample.get("title", ""),
                        },
                        chapter=sample["chapter"],
                        previous_chapters=sample.get("previous_chapters") or [],
                        deterministic_report=deterministic,
                    )
        except Exception as exc:
            judge_setup_error = sanitize_provider_error(exc, _configured_model_secrets())
            logger.warning("评测基准模型评审不可用，继续规则评测(%s)", type(exc).__name__)

    report = await run_evaluation_benchmark(
        baseline=baseline,
        include_judge=req.include_judge,
        judge_case=judge_case,
        model_provider=model_provider,
        model_name=model_name,
        judge_setup_error=judge_setup_error,
        gate_threshold=req.gate_threshold,
        regression_threshold=req.regression_threshold,
    )
    return store.save_evaluation_benchmark(report)


@app.get("/api/novels/{novel_id}/chapters/{chapter_number}/versions")
async def list_chapter_versions(novel_id: str, chapter_number: int) -> list[dict]:
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    return store.list_chapter_versions(novel_id, chapter_number)


@app.get("/api/novels/{novel_id}/chapters/{chapter_number}/versions/diff")
async def diff_chapter_versions(
    novel_id: str,
    chapter_number: int,
    from_version: int,
    to_version: int,
) -> dict:
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    before = store.get_chapter_version(novel_id, chapter_number, from_version)
    after = store.get_chapter_version(novel_id, chapter_number, to_version)
    if before is None or after is None:
        raise HTTPException(404, "章节版本不存在")
    diff = "".join(difflib.unified_diff(
        str(before["content"]).splitlines(keepends=True),
        str(after["content"]).splitlines(keepends=True),
        fromfile=f"v{from_version}",
        tofile=f"v{to_version}",
    ))
    return {"from_version": from_version, "to_version": to_version, "diff": diff}


def _planning_chapter_number(artifact_type: str, chapter_number: int) -> int:
    if artifact_type == "blueprint":
        return 0
    if chapter_number < 1:
        raise HTTPException(422, "scene 版本必须指定有效 chapter_number")
    return chapter_number


@app.get("/api/novels/{novel_id}/planning/{artifact_type}/versions")
async def list_planning_versions(
    novel_id: str,
    artifact_type: Literal["blueprint", "scene"],
    chapter_number: int = 0,
) -> list[dict]:
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    chapter = _planning_chapter_number(artifact_type, chapter_number)
    return store.list_planning_versions(novel_id, artifact_type, chapter)


@app.get("/api/novels/{novel_id}/planning/{artifact_type}/versions/diff")
async def diff_planning_versions(
    novel_id: str,
    artifact_type: Literal["blueprint", "scene"],
    from_version: int,
    to_version: int,
    chapter_number: int = 0,
) -> dict:
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    chapter = _planning_chapter_number(artifact_type, chapter_number)
    before = store.get_planning_version(
        novel_id,
        artifact_type,
        chapter,
        from_version,
    )
    after = store.get_planning_version(
        novel_id,
        artifact_type,
        chapter,
        to_version,
    )
    if before is None or after is None:
        raise HTTPException(404, "规划版本不存在")
    before_text = json.dumps(before["payload"], ensure_ascii=False, indent=2, sort_keys=True)
    after_text = json.dumps(after["payload"], ensure_ascii=False, indent=2, sort_keys=True)
    diff = "".join(difflib.unified_diff(
        before_text.splitlines(keepends=True),
        after_text.splitlines(keepends=True),
        fromfile=f"v{from_version}",
        tofile=f"v{to_version}",
    ))
    return {
        "artifact_type": artifact_type,
        "chapter_number": chapter,
        "from_version": from_version,
        "to_version": to_version,
        "diff": diff,
    }


@app.get("/api/novels/{novel_id}/planning/{artifact_type}/versions/{version_number}")
async def get_planning_version(
    novel_id: str,
    artifact_type: Literal["blueprint", "scene"],
    version_number: int,
    chapter_number: int = 0,
) -> dict:
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    chapter = _planning_chapter_number(artifact_type, chapter_number)
    version = store.get_planning_version(
        novel_id,
        artifact_type,
        chapter,
        version_number,
    )
    if version is None:
        raise HTTPException(404, "规划版本不存在")
    return version


async def _chapter_evaluation_context(
    novel_id: str,
    chapter_number: int,
    version: dict,
) -> tuple[dict, list[dict], list[dict]]:
    """构造规则检查和模型评审上下文；旧作品无检查点时也可评测。"""
    stored_chapters = store.get_all_chapters(novel_id)
    previous_chapters = [
        item for item in stored_chapters
        if int(item.get("chapter_number", 0) or 0) < chapter_number
    ]
    values: dict[str, Any] = {}
    try:
        snapshot = await _graph().aget_state({"configurable": {"thread_id": novel_id}})
        values = snapshot.values or {}
    except Exception as exc:
        logger.warning("评测上下文检查点读取失败(%s, %s)", novel_id, type(exc).__name__)
    chapter = {**version, "chapter_number": chapter_number}
    deterministic_issues, _ = build_consistency_diagnostics(
        chapter=chapter,
        characters=values.get("characters") or [],
        outline=values.get("outline") or [],
        previous_chapters=previous_chapters,
        max_chapter_words=int(values.get("max_chapter_words", cfg.max_chapter_words) or 0),
        canon=values.get("canon") or {},
        total_chapters=int(values.get("total_chapters", 0) or 0) or None,
        creative_brief=values.get("creative_brief") or store.get_novel(novel_id).get("creative_brief"),
    )
    return chapter, previous_chapters, deterministic_issues


@app.post(
    "/api/novels/{novel_id}/chapters/{chapter_number}/versions/{version_number}/evaluations"
)
async def evaluate_chapter_version(
    novel_id: str,
    chapter_number: int,
    version_number: int,
    req: ChapterEvaluationRequest,
) -> dict:
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    version = store.get_chapter_version(novel_id, chapter_number, version_number)
    if version is None:
        raise HTTPException(404, "章节版本不存在")

    chapter, previous_chapters, issues = await _chapter_evaluation_context(
        novel_id,
        chapter_number,
        version,
    )
    deterministic = evaluate_chapter_deterministic(chapter, issues=issues)
    findings = [*deterministic["findings"]]
    findings.extend({
        "dimension": "consistency",
        "score": None,
        "message": str(issue.get("description", "")),
        "severity": issue.get("severity", "low"),
        "source": "deterministic_issue",
    } for issue in issues)

    judge_scores: dict[str, float] = {}
    judge_error = ""
    model_provider = ""
    model_name = ""
    if req.include_judge:
        try:
            resolver = ModelResolver(config=cfg, store=app.state.model_settings_store)
            resolved = resolver.resolve_chat_candidates("analysis")[0]
            model_provider = resolved.provider
            model_name = resolved.model_name
            evaluator = QualityEvaluatorAgent(
                llm=resolver.chat("analysis", temperature=0.0, streaming=False)
            )
            with model_call_context(novel_id, "quality_evaluator"):
                judged = await evaluator.evaluate(
                    novel=novel,
                    chapter=chapter,
                    previous_chapters=previous_chapters,
                    deterministic_report=deterministic,
                )
            judge_scores = judged["scores"]
            findings.extend({
                "dimension": "judge",
                "score": None,
                "message": message,
                "source": "model_judge",
            } for message in judged["findings"])
        except Exception as exc:
            judge_error = sanitize_provider_error(exc, _configured_model_secrets())
            logger.warning(
                "章节模型评审失败，保留规则评测(%s/%s/v%s, %s)",
                novel_id,
                chapter_number,
                version_number,
                type(exc).__name__,
            )

    return store.save_chapter_evaluation(
        novel_id,
        chapter_number,
        version_number,
        content_hash=str(version["content_hash"]),
        evaluator_version=DETERMINISTIC_SCHEMA_VERSION,
        rubric_version=JUDGE_RUBRIC_VERSION if req.include_judge else "",
        deterministic_scores=deterministic["scores"],
        judge_scores=judge_scores,
        overall_score=combine_quality_scores(deterministic["scores"], judge_scores),
        findings=findings,
        model_provider=model_provider,
        model_name=model_name,
        judge_error=judge_error,
    )


@app.get("/api/novels/{novel_id}/chapters/{chapter_number}/evaluations")
async def list_chapter_evaluations(
    novel_id: str,
    chapter_number: int,
    version_number: int | None = None,
) -> list[dict]:
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    return store.list_chapter_evaluations(novel_id, chapter_number, version_number)


@app.put(
    "/api/novels/{novel_id}/chapters/{chapter_number}/evaluations/{evaluation_id}/baseline"
)
async def set_chapter_evaluation_baseline(
    novel_id: str,
    chapter_number: int,
    evaluation_id: int,
) -> dict:
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    evaluation = store.set_chapter_evaluation_baseline(
        novel_id,
        chapter_number,
        evaluation_id,
    )
    if evaluation is None:
        raise HTTPException(404, "章节评测不存在")
    return evaluation


@app.get("/api/novels/{novel_id}/chapters/{chapter_number}/evaluations/compare")
async def compare_chapter_evaluations(
    novel_id: str,
    chapter_number: int,
    from_version: int,
    to_version: int,
    regression_threshold: float = 3.0,
) -> dict:
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")
    selected_baseline = store.get_chapter_evaluation_baseline(novel_id, chapter_number)
    before = (
        selected_baseline
        if selected_baseline
        and int(selected_baseline.get("version_number", 0)) == from_version
        else store.get_latest_chapter_evaluation(novel_id, chapter_number, from_version)
    )
    after = store.get_latest_chapter_evaluation(novel_id, chapter_number, to_version)
    if before is None or after is None:
        raise HTTPException(404, "比较版本尚未完成评测")
    return compare_evaluations(
        before,
        after,
        regression_threshold=regression_threshold,
    )


def _graph():
    graph = getattr(app.state, "graph", None)
    if graph is None:
        raise RuntimeError("API lifespan 尚未初始化 LangGraph")
    return graph


async def _restore_imported_checkpoint(
    novel_id: str,
    state: dict[str, Any],
    checkpoint: dict[str, Any] | None,
) -> None:
    """Recreate a portable LangGraph checkpoint from a backup payload.

    The checkpoint database is intentionally not copied into the ZIP.  Instead,
    values are written through LangGraph's public state API and review nodes are
    executed once so their real interrupt payload is rebuilt for the new ID.
    """
    if not checkpoint or not isinstance(checkpoint, dict) or not checkpoint.get("state"):
        return
    graph = _graph()
    graph_config = {"configurable": {"thread_id": novel_id}}
    next_nodes = [str(item) for item in checkpoint.get("next") or () if item]
    review_node = next((item for item in next_nodes if item in REVIEW_NODES), "")
    as_node = _CHECKPOINT_PREDECESSORS.get(review_node)
    if not as_node:
        target = next_nodes[0] if next_nodes else ""
        if target in {
            "world_builder", "character_designer", "plot_planner", "scene_planner",
            "scene_writer", "style_editor", "consistency_checker", "book_auditor",
        }:
            as_node = "orchestrator"
            state.setdefault("next_agent", target)
        elif target == "scene_rewriter" or target == "orchestrator":
            as_node = "human_review"
    if not as_node:
        # A completed snapshot has no pending node and needs no graph entry.
        return
    await graph.aupdate_state(graph_config, state, as_node=as_node)
    if review_node:
        async for _ in graph.astream(None, graph_config, stream_mode="updates"):
            pass


async def _ensure_checkpoint_creative_brief(novel_id: str, novel: dict):
    """Make the SQLite brief authoritative for existing LangGraph checkpoints."""
    graph = _graph()
    graph_config = {"configurable": {"thread_id": novel_id}}
    snapshot = await graph.aget_state(graph_config)
    values = snapshot.values or {}
    if not values:
        return snapshot
    stored_brief = normalize_creative_brief(novel.get("creative_brief"))
    stored_version = max(int(novel.get("creative_brief_version", 1) or 1), 1)
    state_brief = normalize_creative_brief(values.get("creative_brief"))
    state_version = max(int(values.get("creative_brief_version", 1) or 1), 1)
    stale = state_brief != stored_brief or state_version != stored_version
    if not stale:
        return snapshot
    review_required = bool(values.get("creative_brief_review_required", False))
    if _review_node(snapshot) == "human_review" and (values.get("current_draft") or {}).get("content"):
        review_required = True
    await graph.aupdate_state(
        graph_config,
        {
            "creative_brief": stored_brief,
            "creative_brief_version": stored_version,
            "creative_brief_review_required": review_required,
            "candidate_source_hash": "",
            "issues": [] if review_required else values.get("issues") or [],
            "quality_report": {} if review_required else values.get("quality_report") or {},
        },
    )
    return await graph.aget_state(graph_config)


def _validate_model_runtime() -> None:
    try:
        ModelResolver(config=cfg, store=app.state.model_settings_store).validate_runtime()
    except ModelConfigurationError as exc:
        raise HTTPException(409, str(exc)) from exc


def _configured_model_secrets() -> list[str]:
    secrets = [cfg.openai_api_key, cfg.anthropic_api_key]
    settings_store = getattr(app.state, "model_settings_store", None)
    if settings_store is not None:
        with suppress(ModelSettingsError):
            secrets.extend(settings_store.get_runtime_secrets())
    return [secret for secret in secrets if secret]


def _line(event: dict) -> str:
    return json.dumps(event, ensure_ascii=False) + "\n"


async def _single_event(event: dict) -> AsyncIterator[str]:
    yield _line(event)


def _end_event(values: dict, chapters_done: int | None = None) -> dict:
    chapters = values.get("chapters") or []
    return {
        "type": "end",
        "chapters_done": len(chapters) if chapters_done is None else chapters_done,
        "current_chapter": values.get("current_chapter"),
    }


def _review_node(snapshot) -> str:
    return next((node for node in (snapshot.next or ()) if node in REVIEW_NODES), "")


def _review_event(snapshot) -> dict:
    """将任一人工审批 interrupt 载荷转换为持久任务事件。"""
    info: dict = {}
    for task in getattr(snapshot, "tasks", ()):
        interrupts = getattr(task, "interrupts", ())
        if interrupts:
            value = getattr(interrupts[0], "value", None)
            if isinstance(value, dict):
                info = value
                break
    node = _review_node(snapshot) or str(info.get("type", "human_review"))
    if node != "human_review":
        return {**info, "type": "interrupt", "node": node}
    draft = snapshot.values.get("current_draft") or {}
    event = {
        "type": "interrupt",
        "node": "human_review",
        "chapter_number": info.get("chapter_number", draft.get("chapter_number")),
        "title": info.get("title", draft.get("title", "")),
        "content": info.get("content", draft.get("content", "")),
        "scene_plan": info.get("scene_plan", draft.get("scene_plan") or []),
        "issues": info.get("issues", snapshot.values.get("issues") or []),
        "instruction": info.get(
            "instruction", "POST /api/novels/{id}/resume feedback=approve 或修改意见"
        ),
    }
    if info.get("persistence_error"):
        event["persistence_error"] = info["persistence_error"]
    return event


def _run_job_lease_seconds() -> int:
    return max(int(cfg.run_job_lease_seconds), 5)


def _run_job_worker_id() -> str:
    return str(getattr(app.state, "worker_id", ""))


def _run_job_heartbeat_seconds() -> int:
    return min(
        max(int(cfg.run_job_heartbeat_seconds), 1),
        max(_run_job_lease_seconds() // 2, 1),
    )


async def _heartbeat_run_job(
    job_id: str,
    lease_owner: str,
    executor: asyncio.Task,
    stop: asyncio.Event,
    lease_lost: asyncio.Event,
) -> None:
    """定期续租；一旦失去租约就取消旧执行协程，避免双 Worker 同时推进图。"""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=_run_job_heartbeat_seconds())
            return
        except TimeoutError:
            pass
        try:
            renewed = store.renew_run_job_lease(
                job_id,
                lease_owner,
                _run_job_lease_seconds(),
            )
        except Exception as exc:
            logger.error("任务租约续期失败(%s): %s", job_id, type(exc).__name__)
            renewed = False
        if not renewed:
            lease_lost.set()
            if not executor.done():
                executor.cancel()
            return


async def _reap_expired_run_jobs(stop: asyncio.Event) -> None:
    """持续清理已失去 Worker 心跳的活动任务，使作品可以从 checkpoint 继续。"""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=_run_job_heartbeat_seconds())
            return
        except TimeoutError:
            pass
        try:
            recovered = store.recover_expired_run_jobs()
        except Exception as exc:
            logger.error("过期任务租约巡检失败:%s", type(exc).__name__)
            continue
        if recovered:
            logger.warning("租约巡检中断 %s 个失去心跳的后台任务", recovered)


def _renew_run_job_or_raise(job_id: str, lease_owner: str) -> None:
    if not store.renew_run_job_lease(job_id, lease_owner, _run_job_lease_seconds()):
        raise RunJobLeaseLostError("任务执行租约已丢失")


async def _execute_run_job(
    job_id: str,
    novel_id: str,
    payload: object,
) -> None:
    """在独立协程中执行图，并将进度事件写入 SQLite。"""
    lock = get_novel_lock(novel_id)
    acquired = False
    lease_owner = _run_job_worker_id()
    heartbeat_stop = asyncio.Event()
    lease_lost = asyncio.Event()
    heartbeat_task: asyncio.Task | None = None
    try:
        await lock.acquire()
        acquired = True
        current = store.claim_run_job(job_id, lease_owner, _run_job_lease_seconds())
        if current is None:
            logger.info("后台任务 %s 已由其他 Worker 领取", job_id)
            return
        executor = asyncio.current_task()
        if executor is None:
            raise RuntimeError("无法获取后台任务执行协程")
        heartbeat_task = asyncio.create_task(
            _heartbeat_run_job(
                job_id,
                lease_owner,
                executor,
                heartbeat_stop,
                lease_lost,
            ),
            name=f"lease-heartbeat-{job_id}",
        )
        if current.get("cancel_requested"):
            heartbeat_stop.set()
            store.append_run_job_event(job_id, {"type": "cancelled", "message": "任务已取消"})
            store.update_run_job(job_id, status="cancelled", lease_owner=lease_owner)
            return
        store.update_run_job(job_id, error="", lease_owner=lease_owner)
        store.append_run_job_event(job_id, {
            "type": "job_started",
            "job_id": job_id,
            "attempt": current.get("attempt_count", 1),
        })

        graph = _graph()
        graph_config = {"configurable": {"thread_id": novel_id}}
        async for update in graph.astream(payload, graph_config, stream_mode="updates"):
            _renew_run_job_or_raise(job_id, lease_owner)
            for node in (update or {}):
                if node.startswith("__"):
                    continue
                event = {"type": "node_done", "node": node}
                store.append_run_job_event(job_id, event)
                store.update_run_job(
                    job_id,
                    current_node=node,
                    lease_owner=lease_owner,
                )
            current = store.get_run_job(job_id)
            if current and current.get("cancel_requested"):
                raise asyncio.CancelledError

        _renew_run_job_or_raise(job_id, lease_owner)
        heartbeat_stop.set()
        snapshot = await graph.aget_state(graph_config)
        review_node = _review_node(snapshot)
        if review_node:
            event = _review_event(snapshot)
            store.append_run_job_event(job_id, event)
            store.update_run_job(
                job_id,
                status="waiting_review",
                current_node=review_node,
                lease_owner=lease_owner,
            )
        else:
            event = _end_event(snapshot.values or {})
            store.append_run_job_event(job_id, event)
            store.update_run_job(
                job_id,
                status="completed",
                current_node="",
                lease_owner=lease_owner,
            )
    except asyncio.CancelledError:
        heartbeat_stop.set()
        if lease_lost.is_set():
            logger.warning("后台任务 %s 因租约丢失停止旧执行协程", job_id)
            return
        interrupted = bool(getattr(app.state, "shutting_down", False))
        status = "interrupted" if interrupted else "cancelled"
        message = "服务关闭，任务可从检查点继续" if interrupted else "任务已由用户取消"
        with suppress(Exception):
            store.append_run_job_event(job_id, {"type": status, "message": message})
        with suppress(Exception):
            store.update_run_job(
                job_id,
                status=status,
                error=message,
                lease_owner=lease_owner,
            )
    except RunJobLeaseLostError:
        heartbeat_stop.set()
        logger.warning("后台任务 %s 在提交进度前失去租约", job_id)
    except Exception as exc:
        heartbeat_stop.set()
        message = sanitize_provider_error(exc, _configured_model_secrets())
        logger.error("后台图任务失败(%s, %s): %s", job_id, type(exc).__name__, message)
        try:
            _renew_run_job_or_raise(job_id, lease_owner)
            store.append_run_job_event(job_id, {"type": "error", "message": message})
            store.update_run_job(
                job_id,
                status="failed",
                error=message,
                lease_owner=lease_owner,
            )
        except Exception:
            logger.warning("后台任务 %s 失败后未能提交终态", job_id)
    finally:
        heartbeat_stop.set()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
        with suppress(Exception):
            store.release_run_job_lease(job_id, lease_owner)
        if acquired and lock.locked():
            lock.release()


async def _execute_candidate_job(
    job_id: str,
    novel_id: str,
    *,
    chapter_number: int,
    count: int,
    instruction: str,
    expected_source_hash: str,
) -> None:
    """Generate persisted alternatives without advancing the LangGraph checkpoint."""
    lock = get_novel_lock(novel_id)
    acquired = False
    lease_owner = _run_job_worker_id()
    heartbeat_stop = asyncio.Event()
    lease_lost = asyncio.Event()
    heartbeat_task: asyncio.Task | None = None
    try:
        await lock.acquire()
        acquired = True
        current_job = store.claim_run_job(job_id, lease_owner, _run_job_lease_seconds())
        if current_job is None:
            logger.info("候选稿任务 %s 已由其他 Worker 领取", job_id)
            return
        executor = asyncio.current_task()
        if executor is None:
            raise RuntimeError("无法获取候选稿任务执行协程")
        heartbeat_task = asyncio.create_task(
            _heartbeat_run_job(
                job_id,
                lease_owner,
                executor,
                heartbeat_stop,
                lease_lost,
            ),
            name=f"lease-heartbeat-{job_id}",
        )
        if current_job.get("cancel_requested"):
            heartbeat_stop.set()
            store.append_run_job_event(
                job_id,
                {"type": "cancelled", "message": "任务已取消"},
            )
            store.update_run_job(job_id, status="cancelled", lease_owner=lease_owner)
            return
        store.update_run_job(job_id, error="", lease_owner=lease_owner)
        store.append_run_job_event(job_id, {
            "type": "job_started",
            "job_id": job_id,
            "attempt": current_job.get("attempt_count", 1),
        })

        snapshot = await _graph().aget_state({"configurable": {"thread_id": novel_id}})
        if _review_node(snapshot) != "human_review":
            raise ValueError("作品已不在章节人工审查阶段")
        values = snapshot.values or {}
        draft = values.get("current_draft") or {}
        current_number = int(
            draft.get("chapter_number", values.get("current_chapter", 0)) or 0
        )
        if current_number != chapter_number:
            raise ValueError("当前待审章节已经变化")
        if chapter_candidate_source_hash(values) != expected_source_hash:
            raise ValueError("当前审查上下文已经变化")

        agent = ChapterCandidateAgent(novel_id)
        for candidate_number in range(1, count + 1):
            current_job = store.get_run_job(job_id)
            if current_job and current_job.get("cancel_requested"):
                raise asyncio.CancelledError
            candidate = await agent.generate(
                values,
                candidate_number=candidate_number,
                total_candidates=count,
                instruction=instruction,
            )
            _renew_run_job_or_raise(job_id, lease_owner)
            saved = store.save_chapter_candidate(
                novel_id,
                chapter_number,
                generation_id=job_id,
                candidate_number=candidate_number,
                source_hash=expected_source_hash,
                instruction=instruction,
                title=str(candidate.get("title", "")),
                content=str(candidate.get("content", "")),
                summary=str(candidate.get("summary", "")),
                scene_plan=candidate.get("scene_plan") or [],
                scene_drafts=candidate.get("scene_drafts") or [],
                scores=candidate.get("scores") or {},
                overall_score=float(candidate.get("overall_score", 0.0)),
                evaluation_schema_version=str(
                    candidate.get("evaluation_schema_version", "")
                ),
            )
            store.append_run_job_event(
                job_id,
                {
                    "type": "candidate_ready",
                    "candidate_id": saved["id"],
                    "candidate_number": candidate_number,
                    "overall_score": saved["overall_score"],
                },
            )
            store.update_run_job(
                job_id,
                current_node="chapter_candidate",
                lease_owner=lease_owner,
            )

        _renew_run_job_or_raise(job_id, lease_owner)
        heartbeat_stop.set()
        store.append_run_job_event(
            job_id,
            {
                "type": "candidates_ready",
                "chapter_number": chapter_number,
                "count": count,
            },
        )
        store.update_run_job(
            job_id,
            status="completed",
            current_node="chapter_candidate",
            lease_owner=lease_owner,
        )
    except asyncio.CancelledError:
        heartbeat_stop.set()
        if lease_lost.is_set():
            logger.warning("候选稿任务 %s 因租约丢失停止旧执行协程", job_id)
            return
        interrupted = bool(getattr(app.state, "shutting_down", False))
        status = "interrupted" if interrupted else "cancelled"
        message = "服务关闭，候选稿任务可重新发起" if interrupted else "任务已由用户取消"
        with suppress(Exception):
            store.append_run_job_event(job_id, {"type": status, "message": message})
        with suppress(Exception):
            store.update_run_job(
                job_id,
                status=status,
                error=message,
                lease_owner=lease_owner,
            )
    except RunJobLeaseLostError:
        heartbeat_stop.set()
        logger.warning("候选稿任务 %s 在提交进度前失去租约", job_id)
    except Exception as exc:
        heartbeat_stop.set()
        message = sanitize_provider_error(exc, _configured_model_secrets())
        logger.error("候选稿任务失败(%s, %s): %s", job_id, type(exc).__name__, message)
        try:
            _renew_run_job_or_raise(job_id, lease_owner)
            store.append_run_job_event(job_id, {"type": "error", "message": message})
            store.update_run_job(
                job_id,
                status="failed",
                error=message,
                lease_owner=lease_owner,
            )
        except Exception:
            logger.warning("候选稿任务 %s 失败后未能提交终态", job_id)
    finally:
        heartbeat_stop.set()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
        with suppress(Exception):
            store.release_run_job_lease(job_id, lease_owner)
        if acquired and lock.locked():
            lock.release()


def _schedule_run_job(job: dict, payload: object) -> None:
    tasks: dict[str, asyncio.Task] = app.state.run_job_tasks
    job_id = str(job["id"])
    app.state.active_streams += 1
    task = asyncio.create_task(
        _execute_run_job(job_id, str(job["novel_id"]), payload),
        name=f"novel-run-{job_id}",
    )
    tasks[job_id] = task

    def discard(completed: asyncio.Task) -> None:
        app.state.active_streams = max(
            0,
            int(getattr(app.state, "active_streams", 1)) - 1,
        )
        if tasks.get(job_id) is completed:
            tasks.pop(job_id, None)

    task.add_done_callback(discard)


def _schedule_candidate_job(
    job: dict,
    *,
    chapter_number: int,
    count: int,
    instruction: str,
    source_hash: str,
) -> None:
    tasks: dict[str, asyncio.Task] = app.state.run_job_tasks
    job_id = str(job["id"])
    app.state.active_streams += 1
    task = asyncio.create_task(
        _execute_candidate_job(
            job_id,
            str(job["novel_id"]),
            chapter_number=chapter_number,
            count=count,
            instruction=instruction,
            expected_source_hash=source_hash,
        ),
        name=f"novel-candidates-{job_id}",
    )
    tasks[job_id] = task

    def discard(completed: asyncio.Task) -> None:
        app.state.active_streams = max(
            0,
            int(getattr(app.state, "active_streams", 1)) - 1,
        )
        if tasks.get(job_id) is completed:
            tasks.pop(job_id, None)

    task.add_done_callback(discard)


async def _prepare_run_job(novel_id: str) -> object:
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    snapshot = await _ensure_checkpoint_creative_brief(novel_id, novel)
    if snapshot.values:
        if _review_node(snapshot):
            raise HTTPException(409, "图正在等待人工审查,请提交审查结果")
        if not snapshot.next:
            raise HTTPException(409, "作品已经完成")
        return None

    chapters = store.get_all_chapters(novel_id)
    total = int(novel["total_chapters"] or 3)
    if chapters:
        if len(chapters) >= total:
            raise HTTPException(409, "作品已经完成")
        raise HTTPException(409, "旧作品缺少 LangGraph 检查点,仅支持查看和导出")
    return create_initial_state(
        novel_id=novel_id,
        title=novel["title"],
        genre=novel["genre"] or "武侠",
        inspiration=novel.get("inspiration", ""),
        total_chapters=total,
        style=novel["style"] or "jin_yong",
        planning_review_enabled=bool(novel.get("planning_review_enabled", False)),
        creative_brief=novel.get("creative_brief"),
        creative_brief_version=int(novel.get("creative_brief_version", 1) or 1),
        config=cfg,
    )


async def _prepare_resume_job(novel_id: str, req: ResumeRequest) -> object:
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    snapshot = await _ensure_checkpoint_creative_brief(novel_id, novel)
    review_node = _review_node(snapshot)
    if not review_node:
        raise HTTPException(409, "图不在人工审查暂停状态,无法恢复")
    if req.review_type is not None and req.review_type != review_node:
        raise HTTPException(409, f"当前等待 {review_node},提交类型为 {req.review_type}")

    values = snapshot.values or {}
    if review_node == "blueprint_review":
        world_bible = str(
            req.world_bible if req.world_bible is not None else values.get("world_bible", "")
        ).strip()
        characters = req.characters if req.characters is not None else values.get("characters") or []
        outline = req.outline if req.outline is not None else values.get("outline") or []
        try:
            if not world_bible:
                raise ValueError("世界观圣经不能为空")
            validate_characters(characters)
            validate_outline(outline, int(values.get("total_chapters", 0) or 0))
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return Command(resume={
            "world_bible": world_bible,
            "characters": characters,
            "outline": outline,
        })

    if review_node == "scene_review":
        scene_plan = req.scene_plan if req.scene_plan is not None else values.get("scene_plan") or []
        try:
            normalize_scene_plan(
                scene_plan,
                values.get("chapter_plan") or {},
                int(values.get("max_chapter_words") or 6000),
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return Command(resume={"scene_plan": scene_plan})

    feedback_key = req.feedback.strip().casefold()
    if values.get("creative_brief_review_required"):
        if feedback_key in {"recheck", "重新质检"}:
            if any(value is not None for value in (req.scene_number, req.version_number, req.candidate_id)):
                raise HTTPException(422, "重新质检不能同时执行场景、版本或候选稿操作")
            return Command(resume={"action": "creative_brief_update"})
        if feedback_key in {"", "approve", "通过", "y", "yes"}:
            raise HTTPException(409, "创作约束已更新，必须先按新约束重新质检")

    exclusive_actions = sum(
        value is not None
        for value in (req.scene_number, req.version_number, req.candidate_id)
    )
    if exclusive_actions > 1:
        raise HTTPException(422, "场景重写、版本恢复与候选稿选择不能同时执行")

    resume_value: str | dict = req.feedback
    draft = snapshot.values.get("current_draft") or {}
    if req.candidate_id is not None:
        chapter_number = int(
            draft.get("chapter_number", snapshot.values.get("current_chapter", 0))
        )
        candidate = store.get_chapter_candidate(novel_id, req.candidate_id)
        if candidate is None or int(candidate.get("chapter_number", 0) or 0) != chapter_number:
            raise HTTPException(422, "章节候选稿不存在或不属于当前章节")
        if not chapter_candidate_matches_state(candidate, values):
            raise HTTPException(409, "当前审查上下文已变化，请重新生成候选稿")
        resume_value = {
            "action": "restore_candidate",
            "candidate_id": req.candidate_id,
        }
    elif req.version_number is not None:
        chapter_number = int(draft.get("chapter_number", snapshot.values.get("current_chapter", 0)))
        version = store.get_chapter_version(novel_id, chapter_number, req.version_number)
        if version is None:
            raise HTTPException(422, f"章节版本 v{req.version_number} 不存在")
        resume_value = {"action": "restore_version", "version_number": req.version_number}
    elif req.scene_number is not None:
        feedback = req.feedback.strip()
        if not feedback or feedback.lower() in {"approve", "通过", "y", "yes"}:
            raise HTTPException(422, "场景局部重写必须提供明确的修改意见")
        scene_numbers = {
            int(item.get("scene_number", 0))
            for item in (draft.get("scene_plan") or snapshot.values.get("scene_plan") or [])
        }
        if req.scene_number not in scene_numbers:
            raise HTTPException(422, f"场景 {req.scene_number} 不存在")
        resume_value = {"feedback": feedback, "scene_number": req.scene_number}
    return Command(resume=resume_value)


async def _prepare_canon_job(novel_id: str, req: CanonOperationRequest) -> object:
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    snapshot = await _ensure_checkpoint_creative_brief(novel_id, novel)
    if not snapshot.next or "human_review" not in snapshot.next:
        raise HTTPException(409, "Canon 仅可在人工审查阶段修改")
    values = snapshot.values or {}
    operation = req.model_dump(exclude_unset=True)
    try:
        apply_canon_operation(
            ensure_canon(
                values.get("canon"),
                world_bible=str(values.get("world_bible", "")),
                characters=values.get("characters") or [],
                outline=values.get("outline") or [],
                chapters=values.get("chapters") or [],
            ),
            operation,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Command(resume={"action": "canon_update", "operation": operation})


def _create_and_schedule_job(
    novel_id: str,
    action: str,
    request: dict,
    payload: object,
) -> dict:
    _validate_model_runtime()
    try:
        job = store.create_run_job(
            f"job_{uuid4().hex[:12]}",
            novel_id,
            action,
            request,
            lease_owner=_run_job_worker_id(),
            lease_seconds=_run_job_lease_seconds(),
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    _schedule_run_job(job, payload)
    return job


@app.post("/api/novels/{novel_id}/jobs/run", status_code=202)
async def create_run_job(novel_id: str) -> dict:
    payload = await _prepare_run_job(novel_id)
    return _create_and_schedule_job(novel_id, "run", {}, payload)


@app.post("/api/novels/{novel_id}/jobs/resume", status_code=202)
async def create_resume_job(novel_id: str, req: ResumeRequest) -> dict:
    payload = await _prepare_resume_job(novel_id, req)
    return _create_and_schedule_job(
        novel_id,
        "resume",
        req.model_dump(exclude_none=True),
        payload,
    )


@app.post("/api/novels/{novel_id}/jobs/candidates", status_code=202)
async def create_candidate_generation_job(
    novel_id: str,
    req: CandidateGenerationRequest,
) -> dict:
    """Generate chapter alternatives while leaving the review checkpoint untouched."""
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")
    snapshot = await _ensure_checkpoint_creative_brief(novel_id, novel)
    if _review_node(snapshot) != "human_review":
        raise HTTPException(409, "候选稿仅可在章节人工审查阶段生成")
    values = snapshot.values or {}
    if values.get("creative_brief_review_required"):
        raise HTTPException(409, "创作约束已更新，请先重新质检当前稿")
    draft = values.get("current_draft") or {}
    chapter_number = int(
        draft.get("chapter_number", values.get("current_chapter", 0)) or 0
    )
    if chapter_number < 1 or not str(draft.get("content", "")).strip():
        raise HTTPException(409, "当前没有可用于生成候选稿的待审正文")

    _validate_model_runtime()
    request = {
        **req.model_dump(),
        "chapter_number": chapter_number,
    }
    try:
        job = store.create_run_job(
            f"job_{uuid4().hex[:12]}",
            novel_id,
            "candidate_generation",
            request,
            lease_owner=_run_job_worker_id(),
            lease_seconds=_run_job_lease_seconds(),
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    _schedule_candidate_job(
        job,
        chapter_number=chapter_number,
        count=req.count,
        instruction=req.instruction.strip(),
        source_hash=chapter_candidate_source_hash(values),
    )
    return job


@app.post("/api/novels/{novel_id}/jobs/canon", status_code=202)
async def create_canon_job(novel_id: str, req: CanonOperationRequest) -> dict:
    payload = await _prepare_canon_job(novel_id, req)
    operation = req.model_dump(exclude_unset=True)
    return _create_and_schedule_job(novel_id, "canon_update", operation, payload)


@app.post("/api/novels/{novel_id}/jobs/book-revision", status_code=202)
async def create_book_revision_job(novel_id: str, req: BookRevisionRequest) -> dict:
    """从已完成检查点重开指定终稿章，批准后重新运行全书终审。"""
    _validate_model_runtime()
    lock = get_novel_lock(novel_id)
    await lock.acquire()
    job: dict | None = None
    try:
        novel = store.get_novel(novel_id)
        if not novel:
            raise HTTPException(404, "小说不存在")
        if store.get_active_run_job(novel_id):
            raise HTTPException(409, "作品已有活动任务")

        graph = _graph()
        graph_config = {"configurable": {"thread_id": novel_id}}
        snapshot = await graph.aget_state(graph_config)
        values = snapshot.values or {}
        if not values:
            raise HTTPException(409, "旧作品缺少可返修的 LangGraph 检查点")
        if snapshot.next:
            raise HTTPException(409, "作品尚未完成当前创作或审查流程")
        if not values.get("book_audit_completed"):
            raise HTTPException(409, "作品尚未完成全书终审")

        chapter = next(
            (
                dict(item)
                for item in values.get("chapters") or []
                if int(item.get("chapter_number", item.get("chapter", 0)) or 0)
                == req.chapter_number
            ),
            None,
        )
        if chapter is None:
            raise HTTPException(422, f"第 {req.chapter_number} 章终稿不存在")
        plan = next(
            (
                dict(item)
                for item in values.get("outline") or []
                if int(item.get("chapter", item.get("chapter_number", 0)) or 0)
                == req.chapter_number
            ),
            {
                "chapter": req.chapter_number,
                "title": chapter.get("title", f"第{req.chapter_number}章"),
                "summary": chapter.get("summary", ""),
            },
        )
        audit = values.get("book_audit") or {}
        job = store.create_run_job(
            f"job_{uuid4().hex[:12]}",
            novel_id,
            "book_revision",
            req.model_dump(),
            lease_owner=_run_job_worker_id(),
            lease_seconds=_run_job_lease_seconds(),
        )
        try:
            await graph.aupdate_state(
                graph_config,
                {
                    "current_chapter": req.chapter_number,
                    "current_phase": "writing",
                    "chapter_plan": plan,
                    "scene_plan": chapter.get("scene_plan") or [],
                    "current_draft": chapter,
                    "revision_notes": req.feedback.strip(),
                    "revision_scene_number": 0,
                    "revision_count": 0,
                    "issues": [],
                    "quality_report": {},
                    "persistence_error": "",
                    "book_revision_mode": True,
                    "book_revision_origin_hash": str(audit.get("manuscript_hash", "")),
                    "book_audit_completed": False,
                    "candidate_source_hash": "",
                    "next_agent": "scene_writer",
                },
                as_node="orchestrator",
            )
        except Exception as exc:
            store.update_run_job(
                job["id"],
                status="failed",
                error=f"返修检查点创建失败:{type(exc).__name__}",
            )
            raise
    finally:
        lock.release()

    _schedule_run_job(job, None)
    return job


@app.get("/api/jobs/{job_id}")
async def get_run_job(job_id: str) -> dict:
    job = store.get_run_job(job_id)
    if job is None or store.get_novel(str(job.get("novel_id", ""))) is None:
        raise HTTPException(404, "运行任务不存在")
    return job


@app.get("/api/jobs/{job_id}/events")
async def get_run_job_events(
    job_id: str,
    after_sequence: int = 0,
    limit: int = 200,
) -> dict:
    job = store.get_run_job(job_id)
    if job is None or store.get_novel(str(job.get("novel_id", ""))) is None:
        raise HTTPException(404, "运行任务不存在")
    return {
        "job": job,
        "events": store.list_run_job_events(job_id, after_sequence, limit),
    }


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_run_job(job_id: str) -> dict:
    job = store.get_run_job(job_id)
    if job is None or store.get_novel(str(job.get("novel_id", ""))) is None:
        raise HTTPException(404, "运行任务不存在")
    if job.get("status") not in {"queued", "running"}:
        raise HTTPException(409, "运行任务已结束，无法取消")
    store.request_run_job_cancel(job_id)
    task = app.state.run_job_tasks.get(job_id)
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    current = store.get_run_job(job_id)
    worker_id = _run_job_worker_id()
    if (
        task is not None
        and current
        and current.get("status") in {"queued", "running"}
        and current.get("lease_owner") == worker_id
    ):
        store.append_run_job_event(job_id, {"type": "cancelled", "message": "任务已取消"})
        store.update_run_job(
            job_id,
            status="cancelled",
            error="任务已取消",
            lease_owner=worker_id,
        )
    return store.get_run_job(job_id)


async def _stream_graph(
    novel_id: str,
    payload: object,
    lock: asyncio.Lock,
) -> AsyncIterator[str]:
    """在已持有作品锁的前提下驱动图,结束时负责释放锁。"""
    graph = _graph()
    graph_config = {"configurable": {"thread_id": novel_id}}
    try:
        try:
            async for update in graph.astream(payload, graph_config, stream_mode="updates"):
                for node in (update or {}):
                    if not node.startswith("__"):
                        yield _line({"type": "node_done", "node": node})
        except Exception as exc:
            message = sanitize_provider_error(exc, _configured_model_secrets())
            logger.error("图执行失败(%s): %s", type(exc).__name__, message)
            yield _line({"type": "error", "message": message})
            return

        snapshot = await graph.aget_state(graph_config)
        if _review_node(snapshot):
            yield _line(_review_event(snapshot))
        else:
            yield _line(_end_event(snapshot.values or {}))
    finally:
        app.state.active_streams = max(0, int(getattr(app.state, "active_streams", 1)) - 1)
        lock.release()


@app.post("/api/novels/{novel_id}/run")
async def run_novel(novel_id: str) -> StreamingResponse:
    """开始或从非人工中断检查点继续创作图。"""
    novel = store.get_novel(novel_id)
    if not novel:
        raise HTTPException(404, "小说不存在")

    lock = get_novel_lock(novel_id)
    await lock.acquire()
    try:
        snapshot = await _ensure_checkpoint_creative_brief(novel_id, novel)

        if snapshot.values:
            if _review_node(snapshot):
                raise HTTPException(409, "图正在等待人工审查,请调用 /resume")
            if not snapshot.next:
                lock.release()
                return StreamingResponse(
                    _single_event(_end_event(snapshot.values or {})),
                    media_type="application/x-ndjson",
                )
            payload: object = None
        else:
            chapters = store.get_all_chapters(novel_id)
            total = int(novel["total_chapters"] or 3)
            if chapters:
                if len(chapters) >= total:
                    lock.release()
                    return StreamingResponse(
                        _single_event({
                            "type": "end",
                            "chapters_done": len(chapters),
                            "current_chapter": len(chapters) + 1,
                        }),
                        media_type="application/x-ndjson",
                    )
                raise HTTPException(409, "旧作品缺少 LangGraph 检查点,仅支持查看和导出")

            payload = create_initial_state(
                novel_id=novel_id,
                title=novel["title"],
                genre=novel["genre"] or "武侠",
                inspiration=novel.get("inspiration", ""),
                total_chapters=total,
                style=novel["style"] or "jin_yong",
                planning_review_enabled=bool(novel.get("planning_review_enabled", False)),
                creative_brief=novel.get("creative_brief"),
                creative_brief_version=int(novel.get("creative_brief_version", 1) or 1),
                config=cfg,
            )

        _validate_model_runtime()
        app.state.active_streams += 1
        return StreamingResponse(
            _stream_graph(novel_id, payload, lock),
            media_type="application/x-ndjson",
        )
    except Exception:
        if lock.locked():
            lock.release()
        raise


@app.post("/api/novels/{novel_id}/resume")
async def resume_novel(novel_id: str, req: ResumeRequest) -> StreamingResponse:
    """恢复等待人工审查的图。"""
    if not store.get_novel(novel_id):
        raise HTTPException(404, "小说不存在")

    lock = get_novel_lock(novel_id)
    await lock.acquire()
    try:
        payload = await _prepare_resume_job(novel_id, req)
        _validate_model_runtime()
        app.state.active_streams += 1
        return StreamingResponse(
            _stream_graph(novel_id, payload, lock),
            media_type="application/x-ndjson",
        )
    except Exception:
        if lock.locked():
            lock.release()
        raise


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> JSONResponse:
    """区分进程存活与关键依赖是否可用。"""
    checks: dict[str, dict[str, object]] = {}
    try:
        with store._conn() as conn:
            conn.execute("SELECT 1").fetchone()
        checks["sqlite"] = {"status": "ok"}
    except Exception as exc:
        checks["sqlite"] = {"status": "error", "detail": type(exc).__name__}
    checkpoint_path = Path(cfg.checkpoint_db_path)
    checks["checkpoint"] = {"status": "ok" if checkpoint_path.exists() else "missing"}
    chroma_path = Path(cfg.chroma_persist_dir)
    checks["chroma"] = {"status": "ok" if chroma_path.exists() else "missing"}
    model_configured = bool(cfg.openai_api_key or cfg.anthropic_api_key)
    checks["model"] = {"status": "configured" if model_configured else "fallback"}
    try:
        versions = store.get_schema_versions()
        expected = {
            NovelStore.SCHEMA_COMPONENT: NovelStore.SCHEMA_VERSION,
            ModelSettingsStore.SCHEMA_COMPONENT: ModelSettingsStore.SCHEMA_VERSION,
        }
        schema_ok = all(versions.get(component, 0) >= version for component, version in expected.items())
        checks["schema"] = {
            "status": "ok" if schema_ok else "outdated",
            "versions": versions,
        }
    except Exception as exc:
        checks["schema"] = {"status": "error", "detail": type(exc).__name__}
    healthy = all(item["status"] in {"ok", "configured", "fallback"} for item in checks.values())
    payload = {"status": "ready" if healthy else "not_ready", "checks": checks}
    return JSONResponse(payload, status_code=200 if healthy else 503)


@app.get("/metrics", response_class=StreamingResponse)
async def metrics() -> StreamingResponse:
    """输出轻量 Prometheus 风格运行指标。"""
    state = getattr(app.state, "metrics", {})
    lines = [
        "# TYPE novel_agent_requests_total counter",
        f"novel_agent_requests_total {int(state.get('requests_total', 0))}",
        "# TYPE novel_agent_requests_failed counter",
        f"novel_agent_requests_failed {int(state.get('requests_failed', 0))}",
        "# TYPE novel_agent_requests_4xx counter",
        f"novel_agent_requests_4xx {int(state.get('requests_4xx', 0))}",
        "# TYPE novel_agent_requests_5xx counter",
        f"novel_agent_requests_5xx {int(state.get('requests_5xx', 0))}",
        "# TYPE novel_agent_request_duration_ms summary",
        f"novel_agent_request_duration_ms_sum {float(state.get('request_duration_ms_sum', 0.0)):.3f}",
        f"novel_agent_request_duration_ms_count {int(state.get('request_duration_ms_count', 0))}",
        "# TYPE novel_agent_active_streams gauge",
        f"novel_agent_active_streams {int(getattr(app.state, 'active_streams', 0))}",
        "# TYPE novel_agent_audit_write_failures counter",
        f"novel_agent_audit_write_failures {int(state.get('audit_write_failures', 0))}",
    ]
    return StreamingResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
