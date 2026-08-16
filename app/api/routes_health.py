"""健康检查与运行统计。"""

import time

from fastapi import APIRouter, Request

from ..services.generation import generation_registry, metrics
from ..services.llm import stats as llm_stats

router = APIRouter(tags=["ops"])


@router.get("/healthz", summary="存活探针")
def healthz():
    return {"status": "ok"}


@router.get("/readyz", summary="就绪探针(数据目录可写)")
def readyz(request: Request):
    store = request.app.state.store
    ready = store.healthcheck()
    return {"status": "ok" if ready else "degraded", "data_dir_writable": ready}


@router.get("/api/stats", summary="运行统计")
async def stats(request: Request):
    # 必须是 async 路由:与全部写入方(metrics/stats 的 +=)同处事件循环线程,
    # 避免 sync 路由经线程池读取造成的跨线程访问。见 services/llm.py 线程模型注释。
    return {
        "uptime_seconds": round(time.time() - metrics["started_at"], 1),
        "requests_total": metrics["requests_total"],
        "requests_errors": metrics["requests_errors"],
        "generations_total": metrics["generations_total"],
        "active_generations": generation_registry.active_count,
        "active_tasks": generation_registry.snapshot(),
        "llm": llm_stats,
    }
