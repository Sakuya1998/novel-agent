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

要求 Python 3.10+。

### 2. 启动服务

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

浏览器访问 <http://localhost:8000/>。

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
├── app/                # 后端 (FastAPI)
│   ├── main.py         # 路由:项目 CRUD + 生成接口(NDJSON 流式)
│   ├── agent.py        # Agent 核心:上下文构建 + 生成流水线
│   ├── prompts.py      # 中文长篇小说提示词(故事圣经/角色/大纲/正文/润色/摘要)
│   ├── llm.py          # LLM 统一接入:OpenAI 兼容 / Anthropic / mock
│   ├── storage.py      # 项目持久化(JSON 原子写入 + 异步锁)
│   └── config.py       # 配置(默认值 < data/config.json < 环境变量)
├── static/             # 前端(原生 JS 单页应用,无构建依赖)
│   ├── index.html
│   ├── style.css
│   └── app.js
├── data/               # 运行时数据(项目 + 配置,已 gitignore)
└── requirements.txt
```

## API 速览

所有生成接口返回 NDJSON 流,逐行 `{"type":"delta","text":"..."}`,末尾 `{"type":"done","project":{...}}`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/settings` | 读取配置 |
| PUT | `/api/settings` | 更新配置 |
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
| POST | `/api/projects/{pid}/chapters/{index}/write` | AI 写作(流式) |
| POST | `/api/projects/{pid}/chapters/{index}/continue` | AI 续写(流式) |
| POST | `/api/projects/{pid}/chapters/{index}/polish` | AI 润色(流式) |
| POST | `/api/projects/{pid}/chapters/{index}/summary` | 生成章节摘要 |

## 技术栈

- 后端:Python + FastAPI + uvicorn,LLM 通过 `openai` / `anthropic` SDK 流式调用
- 前端:原生 HTML/CSS/JS 单页应用,无构建依赖,Fetch + ReadableStream 解析 NDJSON 流
- 存储:文件系统 JSON,每项目一文件,`tmp.replace` 原子写入 + `asyncio.Lock` 并发保护

## License

MIT
