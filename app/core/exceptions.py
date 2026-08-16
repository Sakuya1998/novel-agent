"""统一业务异常与全局异常处理。

原则:面向客户端的错误返回可读的中文消息;面向运维的细节进日志,不泄漏堆栈。
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .logging import request_id_var

logger = logging.getLogger(__name__)


class AppError(Exception):
    """业务异常基类:携带 HTTP 状态码与用户可读消息。"""

    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class UpstreamError(AppError):
    """LLM 等上游服务错误。"""

    status_code = 502


class StorageError(AppError):
    """存储层数据错误(损坏、不可写等)。"""

    status_code = 500


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "request_id": request_id_var.get()},
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception):
        logger.exception("未处理异常 path=%s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "服务器内部错误,请稍后重试", "request_id": request_id_var.get()},
        )
