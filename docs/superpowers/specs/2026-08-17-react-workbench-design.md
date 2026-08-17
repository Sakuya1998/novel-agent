# React + TypeScript 小说工作台设计

## 目标

将现有 Streamlit 工作台迁移为独立的 React + TypeScript 前端，同时保留 FastAPI/LangGraph 作为唯一创作后端。前端可以独立开发、构建和部署，浏览器刷新或重新打开后仍能从后端检查点恢复作品状态。

## 架构

- `frontend/`：Vite + React + TypeScript 单页应用。
- `api/server.py`：FastAPI HTTP API，负责小说 CRUD、运行/恢复 NDJSON 流、状态查询和 CORS。
- LangGraph、SQLite、Chroma：继续只运行在后端，浏览器不直接访问数据库。
- 开发环境：Vite 将 `/api` 代理到 `http://127.0.0.1:8000`。
- 生产环境：前端构建产物由静态 Web 服务器托管，API 由 FastAPI 服务托管。

## 用户流程

1. 载入作品列表，选择已有作品或填写新建作品表单。
2. 创建作品后调用 `/run`，消费 `node_done`、`interrupt`、`end`、`error` NDJSON 事件。
3. `human_review` 状态展示章节正文、一致性问题和人工意见输入。
4. 通过或修改意见调用 `/resume`，继续消费流并更新前端状态。
5. 页面刷新时调用详情和 `/state`，恢复当前作品、章节和待审查信息。

## 前端界面

- 左栏：品牌、作品列表、新建作品入口和后端连接状态。
- 中栏：当前作品标题、创作阶段时间线、章节正文/已定稿章节。
- 右栏：人工审查卡片、问题列表、修改意见输入和通过按钮。
- 视觉：暖象牙纸张背景、墨蓝主色、朱砂强调色、编辑工作台密度；避免通用 SaaS 蓝紫渐变。
- 响应式：桌面三栏布局；窄屏变为顶部作品选择、主内容和底部审查面板。

## API 补充

新增 `GET /api/novels/{novel_id}/state`，返回只读的 UI 状态摘要：

- `status`: `idle | running | human_review | completed | error | legacy_read_only`
- `current_chapter`、`current_phase`、`chapters_done`、`total_chapters`
- `current_draft`、`issues`、`persistence_error`

现有 `/run` 和 `/resume` 的 NDJSON 字段保持兼容。CORS 默认允许本地 Vite 地址，也可以通过 `FRONTEND_ORIGINS` 配置。

## 验证

- 前端 `npm run build` 和 TypeScript 检查通过。
- FastAPI 现有测试继续通过，并新增状态/CORS 测试。
- 启动 FastAPI 与 Vite 后，用浏览器验证页面加载、创建作品、运行流、人工审查和刷新恢复。
