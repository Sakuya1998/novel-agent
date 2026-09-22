# ADR-001：以 tenant_id 作为第一阶段 workspace 身份

## 状态

Accepted

## 决策

第一阶段将现有 \`tenant_id\` 作为工作区的持久化身份，API、前端路由和产品文档统一使用 \`workspace\`。新增的表和接口同时保留 \`tenant_id\` 字段名，避免一次性迁移全部旧表；通过 repository/service 边界隔离底层命名。

## 原因

- 当前认证、作品、模型设置和审计已经以 tenant 隔离。
- 直接重命名所有表会扩大迁移面，不能为前端拆仓提供实际收益。
- workspace 是产品概念，tenant_id 是当前存储实现，两者可以在边界处解耦。

## 影响

- 新 API 不向前端暴露 \`tenant_id\` 作为用户可修改字段。
- 后续迁移 PostgreSQL 或重命名字段时，只需替换 repository 映射。
- 需要确保所有新查询都使用当前 principal 的 workspace，而不是仅相信 URL 参数。

## 被拒绝方案

- 立即全面重命名为 \`workspace_id\`：风险大、收益小，推迟到独立数据库迁移窗口。
- 让前端自行维护 workspace header：会造成越权风险，拒绝。
