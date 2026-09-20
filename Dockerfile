# ---- 构建阶段:从锁文件创建独立 venv(与运行环境隔离) ----
FROM ghcr.io/astral-sh/uv:0.12.1 AS uv

FROM python:3.14-slim AS builder

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /build
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --locked --no-dev --no-editable

# ---- 运行阶段:仅保留 venv 产物 + 运行所需源码 ----
FROM python:3.14-slim

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 仅复制运行产物和维护脚本(tests/文档等不进镜像)
COPY src ./src
COPY scripts ./scripts

# 非 root 运行(生产实践);memory/ 保存数据库,data/ 保存模型密钥主密钥
RUN useradd --create-home appuser \
    && mkdir -p /app/memory /app/data /app/output \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
STOPSIGNAL SIGTERM

ENV PYTHONPATH="/app/src"

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz', timeout=3)" || exit 1

CMD ["uvicorn", "novel_agent.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
