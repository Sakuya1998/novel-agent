# 前端切换演练 Runbook

## 1. 预检与备份

在副本数据库上运行 `python -m scripts.migration_preflight --database <copy> --backup <backup>`。预检必须确认数据库表、资源快照列和备份文件存在；先用 `scripts.runtime_backup verify` 校验 checksum，再执行资源快照迁移 dry-run。

## 2. 灰度 smoke test

将新前端以独立域名或 `/next` 路径部署，执行：登录/注册、作品列表、已发布资源读取、创建作品、viewer 只读打开、启动任务、刷新后 SSE/job 恢复、导入导出。所有写操作使用 editor/owner 账号，viewer 账号不得出现写控件。

## 3. 切换前门禁

运行 `python -m scripts.migration_verify --base-url <api-url> --database <db>`，确认 `/healthz`、`/readyz`、资源快照列和备份均通过；同时人工核对 Cookie Secure/HttpOnly/SameSite、CSRF、CORS allowlist、request_id/job_id 和导入导出。

## 4. 故障恢复

旧前端和旧 API 入口已下线，不再提供仓库内回滚入口。发生故障时停止写流量，按发布系统保留的 API/前端镜像 tag 和已验证数据库备份执行恢复；数据库只允许使用向后兼容字段，恢复后重新执行 `/readyz` 和只读 smoke test。

## 5. 稳定窗口

稳定窗口已完成，登录、资源、任务、SSE 重连、导入导出和权限矩阵均通过验证；旧前端构建与旧 API 别名现已移除。
