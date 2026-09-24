# Frontend/Backend Separation and Productization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前 React 单页工作台与 FastAPI 后端演进为可独立发布的团队协作产品，同时保留现有作品生成能力、权限边界和可回滚迁移路径。

**Architecture:** 采用“契约先行、渐进拆分”的路线。后端先稳定 `/api/v1` 资源与异步任务契约，前端在独立仓库中消费版本化 OpenAPI 客户端；旧前端和旧接口在迁移窗口内继续可用。工作区资源、作品快照和 `owner/editor/viewer` 权限由后端作为唯一事实来源，前端只负责路由、展示和体验层门禁。

**Tech Stack:** FastAPI/Pydantic/SQLite（后续可迁移 PostgreSQL）、React 19 + Vite + TypeScript、OpenAPI 生成 TypeScript 客户端、Playwright、Vitest、Docker/Nginx、GitHub Actions。

**Spec:** 待用户确认本计划后，补充 `docs/superpowers/specs/2026-09-21-frontend-backend-separation-design.md`，再开始执行本计划。

## Global Constraints

- 当前 `tenant_id` 先作为工作区语义使用，不在第一阶段强制重命名数据库表。
- 后端是权限和租户隔离的唯一事实来源；前端不能通过隐藏按钮替代后端鉴权。
- 所有新增资源必须带 `workspace_id/tenant_id`、稳定 ID、创建/更新时间、状态和版本信息。
- 作品创建和生成任务必须记录资源版本快照，避免管理员修改资源后改变进行中的作品语义。
- API 采用向后兼容的加法迁移；旧 `/api/*` 在迁移期保留，新的独立前端只使用 `/api/v1/*`。
- 生产切换必须有旧前端镜像、数据库备份和可验证的回滚步骤。
- 不在本计划第一阶段引入完全通用的配置表；内容类型、风格、创作模板、质量策略分立建模。

---

### Task 1: 产品边界、领域词汇和架构决策

**Files:**
- Create: `docs/superpowers/specs/2026-09-21-frontend-backend-separation-design.md`
- Create: `docs/architecture/adr-001-workspace-identity.md`
- Create: `docs/architecture/adr-002-frontend-backend-contract.md`
- Create: `docs/architecture/adr-003-auth-topology.md`
- Create: `docs/architecture/adr-004-resource-version-snapshots.md`

**Interfaces:**
- Produces the terminology and decisions consumed by all later tasks.
- Defines `workspace`, `membership`, `novel`, `resource`, `resource_version`, `job`, and `audit_event`.

- [x] 明确工作区、用户、成员关系和作品归属；第一阶段保留现有 `tenant_id` 存储语义。
- [x] 明确认证拓扑：优先使用同一主域下的 `app.example.com` + `api.example.com`，或由反向代理继续提供单一 origin `/api`。
- [x] 明确前端独立仓库名称、默认分支、发布版本策略和兼容窗口。
- [x] 明确资源生命周期：`draft`、`published`、`disabled`、软删除、版本号和发布者。
- [x] 为每个决策写出被拒绝的替代方案和原因。

验收：产品边界、术语、认证方案、版本策略和回滚策略在设计文档中无未决冲突。

### Task 2: 后端 API 版本化和契约基线

**Files:**
- Modify: `src/novel_agent/api/server.py`
- Create: `src/novel_agent/api/v1/__init__.py`
- Create: `src/novel_agent/api/v1/routes.py`
- Create: `src/novel_agent/api/errors.py`
- Create: `src/novel_agent/api/pagination.py`
- Create: `tests/test_api_contract.py`
- Create: `openapi/novel-agent-v1.json`

**Interfaces:**
- Produces `/api/v1/*` routes, stable error envelope, pagination, request ID and OpenAPI artifact.
- Existing `/api/*` routes remain aliases until the final decommission task.

- [x] 为公开 API 增加 `/api/v1` 前缀，保留旧路由转发到同一 service 函数。
- [x] 统一成功/错误响应；错误至少包含 `code`、`message`、`request_id` 和可选 `details`。
- [x] 为列表接口定义 `limit`、`cursor`、`has_more`，禁止前端依赖未定义的全量返回。
- [x] 对会被重复提交的创建和启动任务支持 `Idempotency-Key`。
- [x] 对资源和作品编辑支持 `ETag`/`If-Match` 或等价的版本冲突检查。
- [x] 在 CI 中生成并校验 OpenAPI 文件，接口变更必须经过兼容性检查。

验证命令：`uv run --locked pytest tests/test_api_contract.py -q`、OpenAPI diff 检查。

### Task 3: 工作区、成员和权限模型固化

**Files:**
- Modify: `src/novel_agent/security.py`
- Modify: `src/novel_agent/memory/sql_store.py`
- Modify: `src/novel_agent/api/server.py`
- Create: `src/novel_agent/api/workspaces.py`（包含工作区与成员路由）
- Create: `src/novel_agent/api/dependencies.py`
- Create: `tests/test_workspace_permissions.py`（包含跨租户隔离覆盖）

**Interfaces:**
- Produces `/api/v1/workspaces`、成员邀请/角色更新/移除接口及统一权限函数。
- Permission matrix: `owner` 管理工作区和资源，`editor` 编辑作品并使用资源，`viewer` 只读。

- [x] 将当前 principal 解析、工作区上下文和角色校验收敛到可复用依赖。
- [x] 为每个工作区资源和作品查询强制带租户条件，拒绝跨工作区 ID 访问。
- [x] 角色变更、邀请、移除和越权失败写入审计日志。
- [x] 明确 owner 最后一个成员保护、viewer 禁止写操作、editor 禁止管理成员和模型密钥。
- [x] 对每个角色建立 API 级正向/反向测试矩阵。

验证命令：`uv run --locked pytest tests/test_workspace_permissions.py tests/test_tenant_isolation.py -q`。

### Task 4: 工作区资源中心后端

**Files:**
- Create: `src/novel_agent/models/workspace_resources.py`
- Create: `src/novel_agent/api/resources.py`
- Modify: `src/novel_agent/memory/sql_store.py`
- Create: `tests/test_workspace_resources.py`

**Interfaces:**
- Produces version化资源 API：
  - `/api/v1/workspaces/{workspace_id}/content-types`
  - `/api/v1/workspaces/{workspace_id}/styles`
  - `/api/v1/workspaces/{workspace_id}/creative-templates`
  - `/api/v1/workspaces/{workspace_id}/quality-policies`
- Each resource exposes `id`, `workspace_id`, `key`, `name`, `description`, `status`, `version`, `is_system`, `created_by`, timestamps and payload.

- [x] 内容类型支持父子层级、别名和标签；作品保存 `primary_type_id` 与附加标签。
- [x] 风格库支持系统内置、工作区复制、编辑、发布和停用；不直接暴露不可控的任意 Prompt 注入能力。
- [x] 创作模板保存 CreativeBrief 的完整结构，而不是把每个枚举单独做成管理表。
- [x] 质量策略保存门槛和回归阈值；质量维度、评分协议和状态仍由系统控制。
- [x] 资源发布必须产生不可变版本；新版本发布不修改历史版本。
- [x] owner 可管理，editor 只能读取和使用，viewer 只能读取。

验证命令：`uv run --locked pytest tests/test_workspace_resources.py -q`。

### Task 5: 作品模型、快照和迁移兼容

**Files:**
- Modify: `src/novel_agent/memory/sql_store.py`
- Modify: `src/novel_agent/api/server.py`
- Modify: `src/novel_agent/graph/state.py`
- Modify: `src/novel_agent/models/creative_brief.py`
- Create: `scripts/migrate_resource_snapshots.py`
- Create: `tests/test_resource_snapshots.py`

**Interfaces:**
- `Novel` retains legacy `genre` and `style` for compatibility while adding resource IDs and snapshot metadata.
- Generation state carries `content_type_snapshot`, `style_snapshot`, `creative_template_snapshot`, and `quality_policy_snapshot`.

- [x] 新建作品时引用已发布资源；未传资源时使用系统默认资源并写入快照。
- [x] 生成任务启动时复制资源版本快照，任务中途不重新读取可变的工作区资源。
- [x] 旧作品通过 `genre/style/creative_brief` 回填兼容快照，不破坏已有 checkpoint。
- [x] 资源停用不影响历史作品，只影响新建作品的选择。
- [x] 增加数据迁移 dry-run、备份前置检查和失败回滚说明。

验证命令：`uv run --locked pytest tests/test_resource_snapshots.py tests/test_checkpoint_persistence.py -q`。

### Task 6: 异步任务、流式事件和错误契约稳定化

**Files:**
- Modify: `src/novel_agent/api/server.py`
- Modify: `frontend/src/api.ts`（迁移窗口内只做兼容适配）
- Create: `src/novel_agent/api/jobs.py`
- Create: `tests/test_jobs_contract.py`
- Create: `openapi/job-events-v1.md`

**Interfaces:**
- Job lifecycle: `queued`、`running`、`completed`、`failed`、`cancelled`、`interrupted`。
- Event envelope: `job_id`, `sequence`, `type`, `payload`, `created_at`。

- [x] 统一轮询事件格式和序号，客户端可以从 `after_sequence` 续传；原 SSE 兼容流暂保留。
- [x] 任务启动、取消、恢复支持幂等和权限校验。
- [x] 通过持久化任务查询和事件游标，网络断开、页面刷新和重新登录后可恢复状态。
- [x] 错误事件复用 provider 错误脱敏，job 查询按作品工作区隔离。

验证命令：`uv run --locked pytest tests/test_jobs_contract.py tests/test_api.py -q`。

### Task 7: 独立前端仓库和契约客户端

**Files（新仓库 `novel-agent-web`）：**
- Create: `package.json`
- Create: `src/api/generated/`
- Create: `src/api/client.ts`
- Create: `src/auth/SessionProvider.tsx`
- Create: `src/workspaces/WorkspaceProvider.tsx`
- Create: `src/permissions/permissions.ts`
- Create: `src/app/router.tsx`
- Create: `.github/workflows/ci.yml`
- Create: `Dockerfile`

**Interfaces:**
- Consumes the published OpenAPI artifact from Task 2.
- Produces typed API hooks and an application shell independent of backend source files.

- [x] 将现有前端迁移到用户提供的独立 `novel-agent-frontend` 仓库；按要求不保留旧 Git 历史，后端仓库不再跟踪前端源码。
- [x] 用 `VITE_API_BASE`、运行时配置或反向代理配置 API 地址，禁止硬编码生产地址。
- [x] OpenAPI artifact 已迁移并由 `openapi-typescript` 生成完整版本化类型；215 个 operation 已接入统一 typed client，包含超时、CSRF、幂等键和 request ID 错误上下文。
- [x] 认证状态、工作区上下文和 owner/editor/viewer 权限矩阵由独立基础层提供；页面级加载/错误/空状态继续由现有工作台逐步迁移。
- [x] 独立前端仓库具备自身 CI（依赖、契约、类型、单测、构建和依赖审计）；后端仓库 CI/Compose 已收敛为 API 职责。

### Task 8: 前端正式应用壳层和路由拆分

**Files（新仓库）：**
- Create: `src/pages/auth/LoginPage.tsx`
- Create: `src/pages/auth/RegisterPage.tsx`
- Create: `src/pages/workspaces/WorkspaceOverviewPage.tsx`
- Create: `src/pages/workspaces/NovelListPage.tsx`
- Create: `src/pages/novels/NovelOverviewPage.tsx`
- Create: `src/pages/novels/NovelWritePage.tsx`
- Create: `src/pages/novels/NovelPlanPage.tsx`
- Create: `src/pages/novels/NovelKnowledgePage.tsx`
- Create: `src/pages/novels/NovelQualityPage.tsx`
- Create: `src/pages/settings/MembersPage.tsx`
- Create: `src/pages/settings/ModelsPage.tsx`
- Create: `src/pages/settings/ResourcesPage.tsx`
- Create: `src/pages/settings/AuditPage.tsx`
- Modify: `src/App.tsx`（最终只保留应用装配）

**Interfaces:**
- Routes: `/login`、`/register`、`/app/workspaces/:workspaceId/overview`、`/novels`、`/novels/:novelId/{overview,write,plan,knowledge,quality}`、`/settings/{members,models,resources,audit}`。

- [x] 已加入 `/login`、`/register`、`/app/workspaces/:workspaceId/overview` 路由页面；主工作台状态和其余页面仍需拆分。
- [x] 模型设置、运行与审计、导入导出已提供 `/settings/models`、`/settings/audit`、`/settings/resources` 页面级入口；保留原组件作为页面内操作面板。
- [x] 工作区概览已提供切换入口；作品工作台支持 `/novels/:novelId/{overview,write,plan,knowledge,quality}` 深链接、刷新及作品/视图切换。
- [x] viewer 进入写作、计划、设定编辑界面时只读；后端拒绝作为最终保护。
- [x] 处理首次加载、权限不足、资源停用、版本冲突、任务运行中、断线重连和空数据状态：路由/工作台保留加载与错误重试，viewer 写操作门禁，运行中控件禁用，导入导出无作品时提供空状态，后端继续作为最终权限与状态校验。

### Task 9: 资源管理前端

**Files（新仓库）：**
- Create: `src/features/resources/ContentTypeManager.tsx`
- Create: `src/features/resources/StyleLibrary.tsx`
- Create: `src/features/resources/CreativeTemplateManager.tsx`
- Create: `src/features/resources/QualityPolicyManager.tsx`
- Create: `src/features/resources/resourceSchemas.ts`
- Create: `src/features/resources/*.test.tsx`

- [x] 提供列表、搜索、状态筛选、创建、编辑、复制（风格）、发布、停用和版本历史入口；资源页面按内容类型、风格、创作模板、质量策略拆分。
- [x] 所有写操作根据权限展示；viewer 只能查看资源列表。
- [x] 发布前显示影响范围：仅新作品、生效版本、不会改变历史快照；模板资源可查看当前 payload 摘要。
- [x] 作品创建器读取当前工作区已发布的内容类型、风格、创作模板和质量策略资源，并提交对应资源 ID；无资源时保留兼容默认值。
- [x] 模板/策略选择提供资源摘要入口，创建器提交模板与质量策略 ID，后端负责生成最终快照。
- [ ] 发布前显示影响范围：仅新作品、生效版本、不会改变历史快照。

### Task 10: 前端工作流和旧功能迁移

**Files（新仓库）：**
- Move/refactor: `components/WritingWorkspace.tsx`
- Move/refactor: `components/PlanningWorkspace.tsx`
- Move/refactor: `components/KnowledgeWorkspace.tsx`
- Move/refactor: `components/QualityWorkspace.tsx`
- Move/refactor: `hooks/useRunJob.ts`
- Move/refactor: `hooks/useReviewWorkflow.ts`
- Create: `src/features/jobs/useJobRecovery.ts`
- Create: `src/features/novels/novelQueries.ts`

- [x] 保留已有写作、规划、设定、质量、评测、版本、导入导出和模型路由能力；旧工作台组件继续由应用壳层装配。
- [x] 把当前长流程弹窗功能迁移为页面级导航，保留必要的短流程确认弹窗。
- [x] `/novels/:novelId/tools/{brief,canon,traces,benchmarks,memory}` 深链接使用嵌入式页面布局，直接访问时加载所需数据。
- [x] 任务流统一使用 job API，支持刷新恢复、取消、失败重试和权限变化；新增 `useJobRecovery` 并保留 `useRunJob` 的断线重连。
- [x] 所有作品查询和变更都绑定当前 workspace context：工作台在 workspace 切换时清理旧作品状态并重新加载，新增 `novelQueries` 统一拒绝无 workspace 的查询。

### Task 11: 独立部署、CI/CD 和环境配置

**Files（后端仓库）：**
- Modify: `docker-compose.yml`
- Modify: `frontend/nginx.conf`（迁移期兼容）
- Create: `deploy/api-compose.yml`
- Create: `docs/deployment/frontend-backend-split.md`

**Files（新前端仓库）：**
- Create: `Dockerfile`
- Create: `nginx.conf`
- Create: `.env.example`
- Create: `.github/workflows/release.yml`

- [ ] 前后端分别构建、打标签和发布镜像，禁止前端镜像依赖后端仓库源码。
- [ ] 生产域名建议为 `app.<domain>` 和 `api.<domain>`；若保留单域名，统一由 Nginx 代理 `/api`。
- [ ] 配置严格 CORS allowlist、Secure/HttpOnly/SameSite Cookie、CSRF 校验和可信代理头。
- [ ] API、前端静态资源、数据库/向量存储、模型密钥和备份分别管理。
- [ ] 部署脚本包含迁移前备份、健康检查、就绪检查、日志、滚动替换和回滚。
- [ ] CI 分为前端、后端、契约、镜像安全扫描和部署 smoke test。

### Task 12: 迁移演练、灰度和切换

**Files:**
- Create: `scripts/migration_preflight.py`
- Create: `scripts/migration_verify.py`
- Create: `docs/migrations/frontend-cutover-runbook.md`
- Create: `frontend-legacy/README.md`（旧入口保留说明）

- [ ] 在副本数据库上演练资源回填、快照生成、索引升级和恢复。
- [ ] 新前端先以独立域名或 `/next` 路径部署，完成只读 smoke test。
- [ ] 灰度开启作品列表、登录、资源读取、创建作品、启动任务和 viewer 只读链路。
- [ ] 切换前验证备份、API 兼容、Cookie/CSRF、SSE 续传、导入导出和权限矩阵。
- [ ] 切换失败时恢复旧前端镜像和旧路由；数据库迁移必须可前滚或使用兼容字段。
- [ ] 连续一个稳定窗口后再删除旧前端构建和旧 API 别名。

### Task 13: 安全、可观测性和发布门槛

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `deploy/prometheus.yml`
- Modify: `deploy/novel-agent-alerts.yml`
- Create: `tests/test_security_contract.py`
- Create: `docs/operations/release-checklist.md`

- [ ] 增加跨工作区访问、CSRF、CORS、Cookie 属性、文件上传、审计和速率限制测试。
- [ ] 监控 API 延迟、5xx、任务积压、任务失败、模型调用失败、SSE 重连和数据库备份状态。
- [ ] 发布前必须通过后端测试、前端测试、OpenAPI 兼容检查、镜像构建、依赖审计和浏览器 E2E。
- [ ] 为每次请求和异步任务贯穿 `request_id`/`job_id`，日志禁止输出密钥和完整 Prompt。

### Task 14: 旧入口下线和仓库职责收敛

**Files:**
- Modify: `README.md`
- Modify: `docker-compose.yml`
- Delete only after migration: `frontend/`
- Modify: `.github/workflows/ci.yml`

- [ ] 确认新前端已覆盖旧前端的功能和关键用户路径。
- [ ] 旧 API 别名进入弃用期，返回文档化的弃用响应头和迁移指引。
- [ ] 完成最后一次数据备份和回滚演练后，移除后端仓库中的前端构建。
- [ ] 后端仓库只保留 API、Agent、任务、数据和部署契约；前端仓库负责页面、客户端和前端发布。
- [ ] 更新本地开发、生产部署、贡献指南和故障排查文档。

## Milestones and Release Gates

1. **M0 设计冻结：** 领域模型、认证拓扑、API 版本和资源快照方案获批准。
2. **M1 契约可用：** `/api/v1`、OpenAPI、权限矩阵和错误/任务契约通过测试。
3. **M2 前端独立可启动：** 新仓库能独立安装、类型检查、测试、构建，并能登录读取作品。
4. **M3 资源中心可用：** owner 管理资源、editor 使用资源、viewer 只读，作品产生快照。
5. **M4 工作流 parity：** 写作、规划、知识、质量、任务恢复、导入导出和模型设置全部迁移。
6. **M5 灰度切换：** 新旧前端可切换，迁移和回滚演练通过。
7. **M6 旧入口下线：** 稳定窗口结束后移除旧前端构建和兼容别名。

## Main Risks and Mitigations

- **认证跨域风险：** 首选同主域子域名或反向代理单 origin；不把会话令牌放进 localStorage。
- **API 漂移风险：** OpenAPI artifact、生成客户端和兼容性检查进入 CI。
- **资源修改影响进行中任务：** 所有作品和 job 使用不可变快照。
- **SQLite 并发与扩容风险：** 先保留当前存储，抽象 repository 边界并为 PostgreSQL 迁移保留 schema 版本。
- **前端大规模迁移回归：** 新旧前端并行、按用户路径灰度、每个里程碑有可回滚镜像。
- **权限只做前端隐藏：** 每个写 API 都使用后端角色依赖和跨租户测试。

## Plan Self-Review

- 覆盖了前端拆仓、API 契约、认证、权限、资源中心、作品快照、异步任务、部署、迁移、回滚和旧入口下线。
- 未在计划中实现业务代码；所有实现任务都有明确文件边界和测试门槛。
- 资源中心采用分立模型，避免以通用配置表掩盖不同领域的校验和生命周期。
- 在开始 Task 2 之前必须先完成 Task 1 的设计确认；在开始 Task 7 之前必须完成 Task 2 的 OpenAPI 基线。
