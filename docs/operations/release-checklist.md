# 发布门槛清单

发布前必须全部满足：

- 后端 `ruff`、pytest、OpenAPI artifact 校验和评测回归通过。
- 前端 `npm run check`、浏览器 E2E 和依赖审计通过。
- API 与前端镜像分别构建、扫描并固定 tag；不得从对方仓库复制源码。
- Compose/部署配置通过离线检查，`/healthz` 与 `/readyz` 均可用。
- CORS 只允许显式来源；生产 Cookie 为 Secure/HttpOnly/SameSite，Cookie 会话写操作有 CSRF 校验。
- 跨工作区访问、viewer 权限、文件上传路径、审计日志和速率限制测试通过。
- 备份 checksum 已验证；SSE/job 恢复、导入导出、回滚 tag 和旧入口均已演练。
- 日志包含 request_id/job_id，不输出模型密钥、Cookie、完整 Prompt 或正文。

## 观测项与告警映射

Prometheus 已采集并告警：API 可用性、5xx、平均请求延迟、活跃 SSE 流和审计写入失败；对应规则位于 `deploy/novel-agent-alerts.yml`。

任务积压/失败、模型调用失败和数据库备份状态目前通过管理端的脱敏 monitoring summary、备份 checksum 校验和发布演练检查，不伪造不存在的 Prometheus 指标。需要将这些摘要接入统一指标后，再增加自动告警规则。

发布后在稳定窗口持续观察上述告警，以及任务/模型/备份摘要；任何告警未恢复前不得结束稳定窗口。
