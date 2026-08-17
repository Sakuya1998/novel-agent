# Multi-Agent 小说创作系统 【墨笔】

基于 LangGraph 的多 Agent 协作长篇小说创作平台:一句灵感,经世界观构建、角色设计、情节规划、逐章写作、风格润色、一致性检查与人机审查七个环节,产出风格可控的长篇小说。

## 系统架构

```
                    ┌────────────────────┐
                    │   Orchestrator     │  主控调度(星型路由)
                    └─────────┬──────────┘
        ┌─────────┬───────────┼───────────┬──────────┐
        ▼         ▼           ▼           ▼          ▼
  WorldBuilder  Character  PlotPlanner  SceneWriter  ...
  (世界观)     (角色)      (大纲)      (正文写作)
                                                   │
                                                   ▼
                                             StyleEditor(风格润色)
                                                   │
                                                   ▼
                                        ConsistencyChecker(一致性检查)
                                                   │
                                          ┌────────┴────────┐
                                     high 问题        通过
                                          │                │
                                          ▼                ▼
                                    回写重写         HumanReview(人工审查)
                                                        │
                                              approve / 修改意见
                                                        │
                                                  下一章 ... → END
```

- **7 Agent**:Orchestrator(调度)+ WorldBuilder / CharacterDesigner / PlotPlanner / SceneWriter / StyleEditor / ConsistencyChecker
- **LangGraph 状态机**:条件边实现质检回写循环与人工审查 interrupt 暂停/恢复
- **三层记忆**:NovelState(运行状态)+ ChromaDB 终稿语义检索(长期)+ SQLite 章节与 LangGraph 检查点持久化
- **风格系统**:STYLE_PROFILES(金庸/古龙/村上春树/余华)六维风格档案注入写作与润色
- **工具集**:灵感语义搜索、时间线校验、角色行为验证、节奏分析、格式导出

## 快速开始

要求 **Python 3.14+**(全部依赖均为最新稳定版,见 requirements.txt)。

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 可选：复制环境变量作为首次启动回退
cp .env.example .env

# 3a. CLI 运行(--auto 自动通过人工审查)
python main.py --title "雾中剑" --genre 武侠 \
    --inspiration "一个失忆剑客在雾都寻找过去,却发现每个人都在说谎。" \
    --chapters 3 --style gu_long --auto

# CLI 在人工审查处退出后,可跨进程恢复
python main.py --resume novel_ab12cd34 --feedback approve

# 3b. API 服务(前后端分离模式)
uvicorn api.server:app --reload

# 3c. React + TypeScript 工作台(另开终端)
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173` 后，点击顶栏齿轮进入“模型设置”。首次使用请先新增模型服务，
再在“模型分工”中分别选择创作模型、分析模型和嵌入模型。工作台尚未保存模型分工时，系统继续
使用 `.env` 中的 `LLM_PROVIDER`、`MODEL_NAME`、API Key 与 `EMBEDDING_MODEL`。

## 项目结构

```
novel-agent/
├── main.py                # CLI 入口
├── config.py              # 配置 + STYLE_PROFILES 风格档案
├── models/                # 加密模型档案、三类模型路由与 LangChain 客户端
├── agents/                # 7 个 Agent
├── graph/                 # LangGraph:state / nodes / edges / builder
├── memory/                # ChromaDB 向量记忆 + SQLite 章节/检查点存储
├── tools/                 # 5 个工具
├── prompts/               # 6 个 Prompt 模板 + PromptManager
├── frontend/              # React + TypeScript 独立工作台
├── api/server.py          # FastAPI 服务(NDJSON 流式)
└── output/                # 导出产物
```

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/novels` | 创建小说(title/genre/inspiration/total_chapters/style) |
| GET | `/api/novels` | 小说列表 |
| GET | `/api/novels/{id}` | 小说详情 + 章节 |
| GET | `/api/novels/{id}/state` | 工作台创作状态摘要 |
| DELETE | `/api/novels/{id}` | 删除作品、章节、进度与检查点 |
| POST | `/api/novels/{id}/run` | 运行创作图(NDJSON 流:node_done/interrupt/end) |
| POST | `/api/novels/{id}/resume` | 恢复人工审查暂停(feedback=approve 或修改意见) |
| GET | `/api/model-settings` | 获取脱敏模型档案与模型分工 |
| POST/PUT/DELETE | `/api/model-settings/profiles` | 管理模型服务档案 |
| PUT | `/api/model-settings/routes` | 保存创作/分析/嵌入模型分工 |
| POST | `/api/model-settings/profiles/{id}/test` | 测试聊天或嵌入模型连接 |
| GET | `/healthz` | 健康检查 |

## 人工审查协议(interrupt)

图运行至 `human_review` 节点时暂停,流返回:

```json
{"type": "interrupt", "chapter_number": 1, "title": "...", "content": "...", "issues": [...]}
```

恢复方式:
- **通过**:`feedback: "approve"` → 章节定稿(chapters append + SQLite 持久化),进入下一章
- **修改意见**:任意文本 → 作为 revision_notes 注入 SceneWriter 重写本章

一致性检查发现 `high` 严重问题时,自动回写重写(上限 `MAX_REVISION_ATTEMPTS` 次,超限转人工裁决)。

检查点保存在 `CHECKPOINT_DB_PATH`。CLI 与 API 可顺序接管同一作品并跨进程恢复。
作品等待人工审查时重复调用 `/run` 返回 HTTP 409,必须改用 `/resume`。

旧版本创建且已有部分终稿、但没有 LangGraph 检查点的作品只能查看和导出。系统不会静默重建设定或覆盖旧章节。

## 配置说明

### 工作台模型设置

“模型服务”可以同时保存 OpenAI、Anthropic、DeepSeek、通义千问和自定义 OpenAI Compatible
档案。内置地址与模型仅作为快捷值，API 地址和模型名称均可编辑。“模型分工”分别控制：

- **创作模型**：世界观、角色、正文写作和风格润色。
- **分析模型**：大纲规划和一致性检查。
- **嵌入模型**：Chroma 长期记忆的向量写入与检索。

API Key 使用 Fernet 加密写入 `SQLITE_DB_PATH`，读取接口只返回“已配置”和掩码。主密钥默认
保存在 `MODEL_SECRET_KEY_PATH=data/model-settings.key`。备份或迁移时必须同时保存
`memory/novels.db` 和 `data/model-settings.key`；丢失主密钥后原密文无法恢复，只能重新录入。

工作台未配置三类模型分工时使用 `.env.example` 中的环境配置回退。React 保存的全局路由也会
被 CLI 和 API 读取。小说创作运行期间模型设置保持只读，避免一次流程中途切换模型。

其余环境变量见 `.env.example`：温度、章节数据库与检查点路径、章节字数与重写上限、默认风格。

同一部小说同一时刻只应由一个入口驱动。支持在 CLI 与 React 工作台之间顺序交接,不支持多个进程同时修改同一作品。

## 前后端分离部署

React 工作台通过 FastAPI 的 `/api` 接口通信，开发环境由 Vite 代理到 `http://127.0.0.1:8000`，生产环境可使用 Docker Compose：

```bash
docker compose up --build
# 浏览器访问 http://localhost:5173
```

生产前端由 Nginx 托管静态资源，并将 `/api` 和 `/healthz` 反向代理到 FastAPI。FastAPI 的 `FRONTEND_ORIGINS` 控制允许的前端来源。

## 测试与质量

```bash
ruff check agents graph memory tools prompts models api config.py main.py tests
pytest
cd frontend && npm test && npm run typecheck && npm run build
```

## Docker 部署

```bash
docker build -t novel-agent .
docker run -p 8000:8000 \
  -v novel-agent-memory:/app/memory \
  -v novel-agent-secrets:/app/data novel-agent
```

Docker Compose 使用命名卷保存小说数据库、检查点和主密钥，避免宿主机新建目录的所有权导致非 root 容器无法写入。
