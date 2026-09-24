# 前后端独立部署

前端和 API 是两个独立镜像、独立仓库和独立发布流水线：

- 前端镜像由 `novel-agent-frontend/Dockerfile` 构建，发布到 `ghcr.io/<owner>/novel-agent-frontend:<tag>`。
- API 镜像由后端 `Dockerfile` 构建，使用 `deploy/api-compose.yml` 部署；前端镜像不复制或依赖后端源码。
- 推荐使用 `app.<domain>` 与 `api.<domain>` 两个域名。若使用同源域名，前端 Nginx 代理 `/api`、`/healthz`、`/readyz` 到 API。

## 发布前检查

1. 为 API 配置独立的 `.env`，明确 `FRONTEND_ORIGINS`，生产环境开启 `AUTH_ENABLED`、Secure Cookie 和 CSRF 校验。
2. 为数据卷、模型密钥和备份目录执行迁移前备份，并确认 `/readyz` 通过。
3. 先启动新 API 镜像并等待健康检查，再滚动替换前端镜像；保留上一版本 tag 以便回滚。
4. 通过 `/login`、作品列表、viewer 只读、启动任务和导入导出 smoke test。

## 回滚

将 `API_IMAGE` 或前端镜像 tag 改回上一稳定版本，执行 `docker compose up -d --no-deps`，确认 `/healthz` 和 `/readyz`，再恢复流量。数据库迁移只能使用向后兼容字段，禁止把回滚建立在破坏性降级上。

## 安全边界

API、静态资源、数据库/向量存储、模型密钥和备份分别管理；反向代理只信任受控的 `X-Forwarded-*` 来源，并保留 request ID、审计日志和健康检查日志。
