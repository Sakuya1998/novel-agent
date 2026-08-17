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

# 2. 配置密钥
cp .env.example .env   # 填入 OPENAI_API_KEY 或 ANTHROPIC_API_KEY

# 3a. CLI 运行(--auto 自动通过人工审查)
python main.py --title "雾中剑" --genre 武侠 \
    --inspiration "一个失忆剑客在雾都寻找过去,却发现每个人都在说谎。" \
    --chapters 3 --style gu_long --auto

# CLI 在人工审查处退出后,可跨进程恢复
python main.py --resume novel_ab12cd34 --feedback approve

# 3b. Streamlit 人机协作界面
streamlit run ui/streamlit_app.py

# 3c. API 服务
uvicorn api.server:app --reload
```

## 项目结构

```
novel-agent/
├── main.py                # CLI 入口
├── config.py              # 配置 + STYLE_PROFILES 风格档案
├── models/llm.py          # LLM 实例管理(OpenAI / Anthropic)
├── agents/                # 7 个 Agent
├── graph/                 # LangGraph:state / nodes / edges / builder
├── memory/                # ChromaDB 向量记忆 + SQLite 章节/检查点存储
├── tools/                 # 5 个工具
├── prompts/               # 6 个 Prompt 模板 + PromptManager
├── ui/streamlit_app.py    # 人机协作界面
├── api/server.py          # FastAPI 服务(NDJSON 流式)
└── output/                # 导出产物
```

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/novels` | 创建小说(title/genre/inspiration/total_chapters/style) |
| GET | `/api/novels` | 小说列表 |
| GET | `/api/novels/{id}` | 小说详情 + 章节 |
| POST | `/api/novels/{id}/run` | 运行创作图(NDJSON 流:node_done/interrupt/end) |
| POST | `/api/novels/{id}/resume` | 恢复人工审查暂停(feedback=approve 或修改意见) |
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

检查点保存在 `CHECKPOINT_DB_PATH`。CLI、API 与 Streamlit 可顺序接管同一作品并跨进程恢复。
作品等待人工审查时重复调用 `/run` 返回 HTTP 409,必须改用 `/resume`。

旧版本创建且已有部分终稿、但没有 LangGraph 检查点的作品只能查看和导出。系统不会静默重建设定或覆盖旧章节。

## 配置说明

见 `.env.example`:LLM Provider/模型/温度、嵌入模型、章节数据库与检查点路径、章节字数与重写上限、默认风格。

同一部小说同一时刻只应由一个入口驱动。支持在 CLI、API、Streamlit 之间顺序交接,不支持多个进程同时修改同一作品。

## 测试与质量

```bash
ruff check agents graph memory tools prompts models api ui config.py main.py
pytest
```

## Docker 部署

```bash
docker build -t novel-agent .
docker run -p 8501:8501 -v $(pwd)/memory:/app/memory \
  -e OPENAI_API_KEY=sk-... novel-agent
```
