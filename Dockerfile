# ---- 构建阶段:独立 venv 安装依赖(与运行环境隔离) ----
# 若未来依赖引入编译需求,构建工具只残留于此阶段,不进最终镜像
FROM python:3.14-slim AS builder

WORKDIR /build
COPY requirements.txt .

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ---- 运行阶段:仅保留 venv 产物 + 运行所需源码 ----
FROM python:3.14-slim

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 仅复制运行产物和维护脚本(tests/文档等不进镜像)
COPY config.py main.py security.py ./
COPY agents ./agents
COPY api ./api
COPY graph ./graph
COPY memory ./memory
COPY models ./models
COPY prompts ./prompts
COPY scripts ./scripts
COPY tools ./tools

# 非 root 运行(生产实践);memory/ 保存数据库,data/ 保存模型密钥主密钥
RUN useradd --create-home appuser \
    && mkdir -p /app/memory /app/data /app/output \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz', timeout=3)" || exit 1

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
