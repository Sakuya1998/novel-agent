"""访问安全:API Key 鉴权、每 IP 滑动窗口限流、请求上下文(request_id + 访问日志)。

鉴权策略:
- 部署配置 NOVEL_AGENT_AUTH_KEY 非空时,所有 /api/* 请求必须携带 X-API-Key 且恒时比较;
- 静态页面与 /healthz、/readyz 不鉴权(健康探针与页面入口);
- 限流仅统计 /api/*,基于内存滑动窗口,适用于单实例部署。
"""

import hmac
import logging
import time
import uuid
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import DeploySettings
from .logging import request_id_var

logger = logging.getLogger("novel.access")

# 无需鉴权的路径前缀(健康探针、静态页面)
_PUBLIC_PATHS = ("/healthz", "/readyz")

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}


class SlidingWindowRateLimiter:
    """每 IP 滑动窗口限流。单实例内存实现,事件循环内单线程访问无需加锁。"""

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        q = self._hits[key]
        cutoff = now - self.window
        while q and q[0] <= cutoff:
            q.popleft()
        if len(q) >= self.max_requests:
            return False
        q.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """request_id 注入 + API Key 鉴权 + 限流 + 访问日志 + 安全响应头。

    metrics:可选的进程级计数器字典({"requests_total": int, "requests_errors": int}),
    由应用层注入,core 层不反向依赖业务模块。
    """

    def __init__(
        self,
        app,
        settings: DeploySettings,
        rate_limiter: SlidingWindowRateLimiter | None = None,
        metrics: dict | None = None,
    ):
        super().__init__(app)
        self.settings = settings
        self.rate_limiter = rate_limiter
        self.metrics = metrics

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        start = time.monotonic()
        path = request.url.path
        try:
            if path.startswith("/api/"):
                if self.settings.auth_key:
                    provided = request.headers.get("X-API-Key", "")
                    if not provided or not hmac.compare_digest(provided, self.settings.auth_key):
                        logger.warning("鉴权失败 path=%s", path)
                        return self._deny(401, "未授权:请携带正确的 X-API-Key 请求头")
                if self.rate_limiter:
                    client_ip = request.client.host if request.client else "unknown"
                    if not self.rate_limiter.allow(client_ip):
                        logger.warning("限流命中 ip=%s path=%s", client_ip, path)
                        return self._deny(429, "请求过于频繁,请稍后再试")
                # 拦截声明超长的请求体(chunked 无声明的场景由 Pydantic 字段校验兜底)
                content_length = request.headers.get("Content-Length")
                if content_length and content_length.isdigit() and int(content_length) > self.settings.max_body_bytes:
                    logger.warning("请求体过大 path=%s declared=%s", path, content_length)
                    return self._deny(413, f"请求体超过上限({self.settings.max_body_mb}MB)")
            response = await call_next(request)
        except Exception:
            logger.exception("请求处理异常 path=%s", path)
            raise
        finally:
            request_id_var.reset(token)

        duration_ms = (time.monotonic() - start) * 1000
        if path.startswith("/api/"):
            if self.metrics is not None:
                self.metrics["requests_total"] += 1
                if response.status_code >= 500:
                    self.metrics["requests_errors"] += 1
            logger.info(
                "%s %s -> %s %.1fms ip=%s",
                request.method,
                path,
                response.status_code,
                duration_ms,
                request.client.host if request.client else "-",
            )
        response.headers["X-Request-ID"] = rid
        for k, v in _SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    @staticmethod
    def _deny(status: int, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={"detail": message},
        )
