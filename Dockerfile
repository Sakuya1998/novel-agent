# syntax=docker/dockerfile:1
# ---------- 构建阶段 ----------
FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- 运行阶段 ----------
FROM python:3.12-slim

# 非 root 运行
RUN useradd --create-home --uid 1000 novelist

WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
COPY static ./static

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NOVEL_AGENT_DATA_DIR=/app/data

RUN mkdir -p /app/data && chown -R novelist:novelist /app
USER novelist

EXPOSE 8000
VOLUME ["/app/data"]

# 容器内无 curl,用 Python 做健康探针
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"]

# 单 worker:内存锁/限流/互斥均为进程内实现,多实例需外层保证单写者(见 README)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
