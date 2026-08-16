# 墨笔 · 小说创作 Agent

> 一句灵感,Agent 自动完成:故事圣经 → 角色卡 → 分章大纲 → 逐章写作-续写-润色。

基于 **FastAPI + 原生 JS 单页应用** 的小说创作 Agent,全程流式输出,带上下文记忆与自动摘要,支持多项目管理。接入 OpenAI 兼容 API(DeepSeek / Qwen / GLM / OpenAI …)或 Anthropic Claude,也可用 mock 模式离线体验。

## 核心特性

- **创作向导**:填一句灵感,勾选「完成后自动写出第 1 章」,Agent 链式完成 故事圣经 → 角色卡 → 分章大纲 → 开篇章节,一键开篇。
- **四步工作台**:故事设定 / 角色卡 / 章节大纲 / 章节写作,均可手动编辑后保存。
- **逐章写作上下文管理**:写第 N 章时自动注入 故事圣经 + 角色卡 + 全书大纲 + 最近 6 章摘要,保证人设与情节一致;每章写完自动生成摘要供后续章节记忆。
- **章节操作**:AI 写作 / AI 续写(取正文结尾 1200 字无缝接续)/ AI 润色 / 手动生成摘要,替换类操作支持一键撤销;每轮可附加创作要求(如「加强打斗场面细节」)。
- **多项目管理**:每个小说项目独立 JSON 文件存储,原子写入 + 异步锁,支持多部长篇并行。
- **全程流式输出**,边生成边显示;进度自动落盘。
- **LLM 接入**:OpenAI 兼容 / Anthropic Claude / mock 离线模式,Provider 与模型可在 Web 设置页热切换。

## 截图

| 创作向导 | 章节写作 |
| --- | --- |
| 填写灵感 → 链式生成 | 逐章 AI 写作/续写/润色 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

要求 Python 3.10+。开发环境(测试/Lint):`pip install -r requirements-dev.txt`。

### 2. 启动服务

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

浏览器访问 <http://localhost:8000/>。

开发模式(开启 /docs 交互式文档):

```bash
NOVEL_AGENT_ENV=dev python -m uvicorn app.main:app --port 8000
```

### 3. 配置模型

首次使用先点右上角 **⚙ 设置**:

| 字段 | 说明 |
| --- | --- |
| Provider | `OpenAI 兼容`(DeepSeek/Qwen/GLM/OpenAI…)/ `Anthropic Claude` / `mock`(离线演示) |
| 模型名 | 如 `deepseek-chat`、`gpt-4o-mini`、`claude-sonnet-4-20250514` |
| Base URL | OpenAI 兼容服务地址,如 `https://api.deepseek.com/v1`;Anthropic 可留空 |
| API Key | 留空则使用环境变量 |

也可用环境变量配置(优先级高于设置页):

```bash
export NOVEL_AGENT_PROVIDER=openai        # openai | anthropic | mock
export NOVEL_AGENT_MODEL=deepseek-chat
export NOVEL_AGENT_BASE_URL=https://api.deepseek.com/v1
export NOVEL_AGENT_API_KEY=sk-...
export NOVEL_AGENT_CHAPTER_WORDS=2500    # 单章目标字数
export NOVEL_AGENT_TEMPERATURE=0.8       # 0~1.2
```

OpenAI / Anthropic 的通用环境变量同样适用:`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`。

### 4. 开始创作

1. 点 **＋ 新建小说**,填一句灵感,勾选「完成后自动写出第 1 章」,点「✨ 开始创作」。
2. 向导自动跑完 5 步,进入章节写作页,第 1 章正文已就绪。
3. 后续逐章点「✍ AI 写作」,Agent 会基于全书设定与上文摘要续写下一章。

## 创作流程

```
一句灵感
   │
   ▼
① 故事圣经   书名/类型/世界观/核心冲突/主线梗概/文风
   │
   ▼
② 角色卡     姓名/定位/外貌/性格/背景/目标/弧线/关系
   │
   ▼
③ 分章大纲   每章 标题/情节概要/关键事件,含伏笔与递进
   │
   ▼
④ 章节写作   写作/续写/润色 → 自动摘要 → 写下一章
   │           ▲                          │
   └─── 上下文:圣经+角色+大纲+最近6章摘要 ◄┘
```

写每一章时,Agent 会自动把「故事圣经 + 角色卡 + 全书大纲 + 最近 6 章摘要」拼进上下文,保证人设、情节、时间线一致,避免长篇后人物失真或剧情断线。每章写完自动生成摘要,作为写下一章时的「前文记忆」。

## 项目结构

```
.
├── app/                    # 后端 (FastAPI)
│   ├── main.py             # 应用工厂:中间件/异常处理/生命周期
│   ├── core/               # 基础设施层
│   │   ├── config.py       # 部署配置(pydantic-settings,环境变量/.env)
│   │   ├── runtime.py      # 运行时设置(data/config.json,Web 热改)+ API Key 脱敏
│   │   ├── logging.py      # 结构化日志(request_id 贯穿,支持 JSON 输出)
│   │   ├── security.py     # API Key 鉴权、每 IP 滑动窗口限流、安全响应头
│   │   └── exceptions.py   # 统一业务异常 + 全局异常处理器
│   ├── api/                # 路由层
│   │   ├── deps.py         # 依赖注入 + NDJSON 流式响应工具
│   │   ├── routes_health.py     # /healthz /readyz /api/stats
│   │   ├── routes_settings.py   # 设置(读取自动脱敏)
│   │   ├── routes_projects.py   # 项目 CRUD + 圣经/角色/大纲生成
│   │   └── routes_chapters.py   # 章节 CRUD + 写作/续写/润色/摘要
│   ├── services/           # 服务层
│   │   ├── agent.py        # Agent 核心:上下文构建 + 生成流水线
│   │   ├── llm.py          # LLM 接入:超时/重试/并发限流/客户端复用
│   │   └── generation.py   # 生成互斥(同章节防并行写)+ 运行指标
│   ├── schemas.py          # Pydantic 请求模型(输入长度/范围校验)
│   ├── prompts.py          # 中文长篇小说提示词
│   └── storage.py          # 项目持久化(原子写 + 锁 + 损坏隔离)
├── static/                 # 前端(原生 JS 单页应用,无构建依赖)
├── tests/                  # pytest 测试套件(52 项:单元 + 集成)
├── data/                   # 运行时数据(已 gitignore)
├── Dockerfile / docker-compose.yml / .env.example
└── .github/workflows/ci.yml  # CI:Lint + 测试 + 镜像构建(Python 3.10/3.12)
```

## API 速览

所有生成接口返回 NDJSON 流,逐行 `{"type":"delta","text":"..."}`,末尾 `{"type":"done","project":{...}}`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/healthz` | 存活探针(免鉴权) |
| GET | `/readyz` | 就绪探针(数据目录可写,免鉴权) |
| GET | `/api/stats` | 运行统计(请求量/生成量/活跃任务/LLM 指标) |
| GET | `/api/settings` | 读取配置(API Key 自动脱敏) |
| PUT | `/api/settings` | 更新配置(回传脱敏值不会覆盖真实 Key) |
| GET | `/api/projects` | 项目列表 |
| POST | `/api/projects` | 新建项目 |
| GET | `/api/projects/{pid}` | 读取项目 |
| PATCH | `/api/projects/{pid}` | 更新项目字段 |
| DELETE | `/api/projects/{pid}` | 删除项目 |
| POST | `/api/projects/{pid}/generate/premise` | 生成故事圣经(流式) |
| POST | `/api/projects/{pid}/generate/characters` | 生成角色卡(流式) |
| POST | `/api/projects/{pid}/generate/outline` | 生成大纲(流式) |
| POST | `/api/projects/{pid}/chapters` | 新增章节 |
| PUT | `/api/projects/{pid}/chapters/{index}` | 更新章节内容 |
| DELETE | `/api/projects/{pid}/chapters/{index}` | 删除章节 |
| POST | `/api/projects/{pid}/chapters/{index}/write` | AI 写作(流式,同章节互斥) |
| POST | `/api/projects/{pid}/chapters/{index}/continue` | AI 续写(流式,同章节互斥) |
| POST | `/api/projects/{pid}/chapters/{index}/polish` | AI 润色(流式,同章节互斥) |
| POST | `/api/projects/{pid}/chapters/{index}/summary` | 生成章节摘要 |

## 技术栈

- 后端:Python + FastAPI + uvicorn,LLM 通过 `openai` / `anthropic` SDK 流式调用
- 前端:原生 HTML/CSS/JS 单页应用,无构建依赖,Fetch + ReadableStream 解析 NDJSON 流
- 存储:文件系统 JSON,每项目一文件,唯一临时名 + `replace` 原子写入 + `asyncio.Lock` 并发保护

## 生产部署

### Docker(推荐)

```bash
cp .env.example .env       # 按需修改,至少设置 NOVEL_AGENT_AUTH_KEY
docker compose up -d       # 构建并启动,数据持久化在 ./data
```

镜像特性:非 root 运行、内置 HEALTHCHECK、多阶段构建、仅单 worker(锁与限流为进程内实现)。

### 部署级配置(环境变量 / .env)

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `NOVEL_AGENT_ENV` | `prod` | `dev` 时开启 `/docs`;生产关闭交互式文档 |
| `NOVEL_AGENT_DATA_DIR` | `./data` | 数据目录(兼容旧变量 `NOVEL_AGENT_DATA`) |
| `NOVEL_AGENT_AUTH_KEY` | 空 | **设置后所有 `/api/*` 需携带 `X-API-Key`**(恒时比较;前端会自动提示输入) |
| `NOVEL_AGENT_CORS_ORIGINS` | 空 | 允许跨域的来源,逗号分隔 |
| `NOVEL_AGENT_RATE_LIMIT` | `240/60` | 每 IP 滑动窗口限流(请求数/窗口秒),置空禁用 |
| `NOVEL_AGENT_MAX_BODY_MB` | `2` | 请求体大小上限(MB),超限返回 413 |
| `NOVEL_AGENT_LOG_LEVEL` | `INFO` | 日志级别 |
| `NOVEL_AGENT_LOG_JSON` | `false` | `true` 输出 JSON 日志(采集器友好) |
| `NOVEL_AGENT_LLM_CONCURRENCY` | `4` | 全局并发生成上限 |
| `NOVEL_AGENT_LLM_TIMEOUT` | `300` | 单次 LLM 调用超时(秒) |
| `NOVEL_AGENT_LLM_MAX_RETRIES` | `2` | 连接失败 SDK 内部重试次数 |

### 可靠性设计

- **输入校验**:全部请求体经 Pydantic 长度/范围校验(422 拒绝),pid 白名单防路径穿越
- **生成互斥**:同一章节同时只允许一个 AI 任务,并发请求收到可读错误事件,不会互相覆盖正文
- **LLM 治理**:全局并发信号量、超时、SDK 重试、客户端按配置指纹复用(连接池)
- **数据安全**:唯一临时文件名原子写入;损坏文件自动隔离到 `data/corrupt/` 并显式报错,绝不误报「不存在」
- **密钥安全**:设置接口返回的 API Key 一律脱敏(`***abc…xyz`),回传脱敏值不覆盖真实 Key
- **可观测**:每条请求带 request_id(响应头 `X-Request-ID` 同步返回),`/api/stats` 暴露请求/生成/LLM 指标
- **优雅关闭**:退出时关闭全部 LLM 连接;生成中断自动保存已生成部分

> **单实例说明**:锁、限流、统计为进程内实现,请以单 worker/单实例部署(Docker 默认如此);水平扩展需前置网关保证同一项目单写者。

## 开发

```bash
pip install -r requirements-dev.txt
ruff check app tests && ruff format --check app tests  # Lint
pytest                                                 # 52 项测试(单元 + 集成,mock provider 全链路)
```

CI(GitHub Actions):Python 3.10/3.12 矩阵跑 Lint + 测试,通过后构建 Docker 镜像冒烟。

## License

MIT
