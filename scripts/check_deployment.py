"""离线生产发布检查，不需要 Docker daemon 或外部网络。"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from config import Config, validate_production_config

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    nginx = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    prometheus = yaml.safe_load((ROOT / "deploy" / "prometheus.yml").read_text(encoding="utf-8"))
    alerts = yaml.safe_load((ROOT / "deploy" / "novel-agent-alerts.yml").read_text(encoding="utf-8"))

    require((ROOT / "security.py").is_file(), "Docker 运行所需的 security.py 不存在")
    require("COPY config.py main.py security.py ./" in dockerfile, "Dockerfile 未复制顶层运行模块")
    require("COPY scripts ./scripts" in dockerfile, "Dockerfile 未复制运行时维护脚本")
    require("USER appuser" in dockerfile, "API 镜像必须使用非 root 用户")
    require("/readyz" in dockerfile, "API healthcheck 必须检查 /readyz")

    services = compose.get("services", {})
    api = services.get("api", {})
    frontend = services.get("frontend", {})
    require(api and frontend, "Compose 必须包含 api 和 frontend 服务")
    require(api.get("read_only") is True, "API 根文件系统必须只读")
    require("ALL" in api.get("cap_drop", []), "API 必须删除全部 Linux capabilities")
    require("no-new-privileges:true" in api.get("security_opt", []), "API 必须启用 no-new-privileges")
    require(api.get("restart") == "unless-stopped", "API 必须配置自动重启")
    require(
        frontend.get("depends_on", {}).get("api", {}).get("condition") == "service_healthy", "前端必须等待 API 就绪"
    )
    for service_name, service in (("api", api), ("frontend", frontend)):
        options = service.get("logging", {}).get("options", {})
        require(options.get("max-size") and options.get("max-file"), f"{service_name} 缺少 Docker 日志轮转")

    for marker in (
        "X-Content-Type-Options",
        "Content-Security-Policy",
        "X-Forwarded-For",
        "location /readyz",
    ):
        require(marker in nginx, f"Nginx 缺少安全/就绪配置: {marker}")

    require("novel-agent" in str(prometheus.get("scrape_configs", [])), "Prometheus 未配置 Novel Agent 抓取任务")
    alert_names = {
        rule.get("alert")
        for group in alerts.get("groups", [])
        for rule in group.get("rules", [])
        if isinstance(rule, dict)
    }
    require(
        {"NovelAgentApiDown", "NovelAgentHighHttp5xx", "NovelAgentAuditWriteFailures"} <= alert_names, "告警规则不完整"
    )

    production = Config(_env_file=ROOT / ".env.production.example")
    validate_production_config(production)
    print("deployment checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"deployment check failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
