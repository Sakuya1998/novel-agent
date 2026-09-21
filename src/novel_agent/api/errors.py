"""Stable error helpers for the versioned API."""

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def error_response(request: Request, *, code: str, message: str, status_code: int, details: Any = None) -> JSONResponse:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": getattr(request.state, "request_id", ""),
    }
    if details is not None:
        body["details"] = details
    return JSONResponse(body, status_code=status_code)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if getattr(request.state, "api_version", "legacy") != "v1":
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    detail = exc.detail if isinstance(exc.detail, str) else "请求失败"
    code = "not_found" if exc.status_code == 404 else "request_failed"
    return error_response(request, code=code, message=detail, status_code=exc.status_code)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    if getattr(request.state, "api_version", "legacy") != "v1":
        return JSONResponse({"detail": exc.errors()}, status_code=422)
    return error_response(request, code="validation_error", message="请求参数无效", status_code=422, details=exc.errors())
