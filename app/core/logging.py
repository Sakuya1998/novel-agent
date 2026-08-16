"""结构化日志:request_id 贯穿请求链路,支持 JSON 输出(容器/采集器友好)。"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_CONFIGURED = False


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """把日志序列化为一行 JSON,字段固定,便于采集解析。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_TEXT_FORMAT = "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"


def setup_logging(level: str = "INFO", json_mode: bool = False) -> None:
    """初始化根日志配置。幂等:重复调用只会刷新 handler。"""
    global _CONFIGURED
    root = logging.getLogger()

    if _CONFIGURED:
        root.setLevel(level)
        return

    handler = logging.StreamHandler(sys.stdout)
    if json_mode:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT))
    handler.addFilter(_RequestIdFilter())

    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    # uvicorn 自带 access log 与本应用访问日志重复,统一由 novel.access 记录
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # 降低第三方库噪音
    for noisy in ("httpx", "httpcore", "openai", "anthropic"):
        logging.getLogger(noisy).setLevel(max(level, "INFO") if level != "DEBUG" else "DEBUG")
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
