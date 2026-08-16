"""墨笔 · 小说创作 Agent — FastAPI 应用工厂。

启动:uvicorn app.main:app --host 0.0.0.0 --port 8000
测试/自定义部署:from app.main import create_app; app = create_app(DeploySettings(...))
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import routes_chapters, routes_health, routes_projects, routes_settings  # noqa: F401 — 路由注册
from .core.config import DeploySettings, load_deploy_settings
from .core.exceptions import install_exception_handlers
from .core.logging import setup_logging
from .core.runtime import RuntimeSettingsStore
from .core.security import RequestContextMiddleware, SlidingWindowRateLimiter
from .services.generation import metrics
from .services.llm import close_all_clients
from .storage import Store

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

logger = logging.getLogger("novel.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "服务启动 env=%s data_dir=%s auth=%s",
        app.state.deploy.env,
        app.state.deploy.data_dir,
        "on" if app.state.deploy.auth_key else "off",
    )
    yield
    await close_all_clients()
    logger.info("服务已优雅关闭")


def create_app(deploy: DeploySettings | None = None) -> FastAPI:
    """构建 FastAPI 应用。deploy 为空时从环境变量读取。"""
    deploy = deploy or load_deploy_settings()
    setup_logging(level=deploy.log_level, json_mode=deploy.log_json)

    app = FastAPI(
        title="墨笔 · 小说创作 Agent",
        lifespan=lifespan,
        docs_url="/docs" if deploy.env == "dev" else None,  # 生产环境关闭交互式文档
        redoc_url=None,
        openapi_url="/openapi.json" if deploy.env == "dev" else None,
    )

    # ---- 应用状态(依赖注入源) ----
    app.state.deploy = deploy
    app.state.store = Store(deploy.data_dir)
    app.state.runtime_settings = RuntimeSettingsStore(deploy.data_dir / "config.json")

    # ---- 路由 ----
    app.include_router(routes_health.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_projects.router)
    app.include_router(routes_chapters.router)

    # ---- 中间件(注册顺序即洋葱层,后注册者在外层) ----
    rate_limit = deploy.parse_rate_limit()
    limiter = SlidingWindowRateLimiter(rate_limit[0], rate_limit[1]) if rate_limit else None
    app.add_middleware(RequestContextMiddleware, settings=deploy, rate_limiter=limiter, metrics=metrics)
    if deploy.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=deploy.cors_origin_list,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ---- 全局异常处理 ----
    install_exception_handlers(app)

    # ---- 静态前端(最后挂载,避免吞掉 /api 路由) ----
    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app


app = create_app()
