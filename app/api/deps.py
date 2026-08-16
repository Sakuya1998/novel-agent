"""通用依赖与流式响应工具。"""

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

from ..core.exceptions import NotFoundError
from ..core.runtime import RuntimeSettingsStore
from ..services.agent import NovelAgent
from ..services.llm import LLMOptions
from ..storage import Store


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_runtime_settings(request: Request) -> RuntimeSettingsStore:
    return request.app.state.runtime_settings


def get_agent(request: Request) -> NovelAgent:
    deploy = request.app.state.deploy
    settings = request.app.state.runtime_settings.load()
    options = LLMOptions(
        timeout=deploy.llm_timeout,
        max_retries=deploy.llm_max_retries,
        concurrency=deploy.llm_concurrency,
    )
    return NovelAgent(settings, options=options)


def project_or_404(store: Store, pid: str) -> dict[str, Any]:
    p = store.get_project(pid)
    if p is None:
        raise NotFoundError("项目不存在")
    return p


def ndjson(gen: AsyncIterator[dict[str, Any]]) -> StreamingResponse:
    """把事件流包装为 NDJSON StreamingResponse,兜底保证客户端总能收到错误事件。"""

    async def iterator():
        try:
            async for ev in gen:
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as e:  # noqa: BLE001 — 流式响应内异常无法走全局 handler
            yield json.dumps({"type": "error", "message": f"服务器错误:{e}"}, ensure_ascii=False) + "\n"

    return StreamingResponse(
        iterator(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
