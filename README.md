# Multi-Agent 小说创作系统 【墨笔】

基于 LangGraph 的多 Agent 协作长篇小说创作平台:一句灵感,经世界观构建、角色设计、情节规划、场景规划、逐章写作、风格润色、一致性检查、人机审查、终稿事实提炼与全书终审,产出风格可控的长篇小说。

## 系统架构

```
                    ┌────────────────────┐
                    │   Orchestrator     │  主控调度(星型路由)
                    └─────────┬──────────┘
        ┌─────────┬───────────┼───────────┬──────────┐
        ▼         ▼           ▼           ▼          ▼
  WorldBuilder  Character  PlotPlanner  ScenePlanner  ...
  (世界观)     (角色)      (大纲)      (场景规划)
                                                   │
                                                   ▼
                                             SceneWriter(正文写作)
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
                                         approve / 整章意见 / 场景意见
                                                        │
                                ChapterDigest / SceneWriter / SceneRewriter
                                                        │
                                                 最终章批准后
                                                        ▼
                                                BookAuditor(全书终审)
```

- **14 Agent**:Orchestrator(调度)+ WorldBuilder / CharacterDesigner / PlotPlanner / ScenePlanner / SceneWriter / SceneRewriter / ChapterCandidate / StyleEditor / ConsistencyChecker / ChapterDigest / Replanner / QualityEvaluator / BookAuditor
- **LangGraph 状态机**:新章先生成结构化场景计划,条件边实现质检回写循环与人工审查 interrupt 暂停/恢复
- **四层记忆**:NovelState 运行状态 + 结构化 Canon(事实/角色/时间线/叙事线程)+ ChromaDB 语义检索 + SQLite/LangGraph 持久化；终稿会从实际正文重新提炼摘要与事实
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

# 只重写第 2 场，或恢复第 3 个章节版本
python main.py --resume novel_ab12cd34 --feedback "加强追逐" --scene-number 2
python main.py --resume novel_ab12cd34 --version-number 3

# 3b. API 服务(前后端分离模式)
uvicorn api.server:app --reload

# 3c. React + TypeScript 工作台(另开终端)
cd frontend
npm install
npm run dev

# 3d. 固定质量评测与回归门禁(不需要模型 Key)
cd ..
python -m scripts.run_evaluations
# 与历史运行比较；任一样本回归超过 3 分时退出码为 1
python -m scripts.run_evaluations --baseline-run-id eval_xxx --json
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
├── agents/                # 14 个 Agent
├── graph/                 # LangGraph:state / nodes / edges / builder
├── memory/                # 结构化 Canon + ChromaDB 向量记忆 + SQLite 章节存储
├── tools/                 # 5 个工具
├── prompts/               # 10 个 Prompt 模板 + PromptManager
├── frontend/              # React + TypeScript 独立工作台
├── api/server.py          # FastAPI 服务(持久后台任务 + 兼容 NDJSON 流)
└── output/                # 导出产物
```

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/register` | 创建用户及独立工作区，并返回 Bearer 会话 |
| POST | `/api/auth/login` | 使用用户名或邮箱登录 |
| GET/POST | `/api/auth/me`、`/api/auth/logout` | 获取当前身份或注销会话 |
| GET/POST | `/api/auth/users` | 查看或添加当前工作区成员 |
| PUT | `/api/auth/users/{user}/role` | owner 调整成员角色 |
| POST | `/api/novels` | 创建小说；可用 `planning_review_enabled` 开启规划审批，并用 `creative_brief` 固化创作约束 |
| POST | `/api/novels/import` | 导入 Markdown/TXT/DOCX/EPUB、ZIP 或带密码的 `.novel-backup.enc` 备份为当前工作区新作品 |
| GET | `/api/novels` | 小说列表 |
| GET | `/api/novels/{id}` | 小说详情 + 章节 |
| GET | `/api/novels/{id}/export?format={markdown|txt|docx|epub|backup}` | 下载出版文件或完整 ZIP 备份；`backup` 可用 `X-Backup-Password` 请求头导出 AES-GCM 加密包 |
| POST | `/api/novels/{id}/export/jobs` | 显式创建后台导出任务；大文件导入/导出也会自动返回 202 任务 |
| GET | `/api/transfers/{job}`、`/api/transfers/{job}/download` | 查询传输任务或下载已完成的导出文件 |
| POST | `/api/transfers/{job}/cancel` | 取消排队或执行中的传输任务 |
| GET | `/api/novels/{id}/state` | 工作台创作状态摘要 |
| GET | `/api/novels/{id}/creative-brief/versions` | 获取创作约束版本历史 |
| PUT | `/api/novels/{id}/creative-brief` | 以乐观锁更新创作约束，并使受影响的审查产物失效 |
| DELETE | `/api/novels/{id}` | 删除作品、章节、进度与检查点 |
| POST | `/api/novels/{id}/run` | 运行创作图(NDJSON 流:node_done/interrupt/end) |
| POST | `/api/novels/{id}/resume` | 恢复蓝图、分镜或终稿人工审查暂停 |
| POST | `/api/novels/{id}/jobs/run` | 创建可重连的后台创作任务 |
| POST | `/api/novels/{id}/jobs/resume` | 以人工审查结果创建后台恢复任务 |
| POST | `/api/novels/{id}/jobs/candidates` | 在章节审查阶段后台生成 2-4 个候选稿 |
| POST | `/api/novels/{id}/jobs/canon` | 以 Canon 操作创建后台重新质检任务 |
| POST | `/api/novels/{id}/jobs/book-revision` | 从完结检查点重开指定终稿章并启动返修任务 |
| GET | `/api/jobs/{job}` | 获取持久任务状态 |
| GET | `/api/jobs/{job}/events` | 按 `after_sequence` 续读任务事件 |
| POST | `/api/jobs/{job}/cancel` | 取消排队或运行中的任务 |
| GET | `/api/novels/{id}/canon` | 获取完整 Canon v3、角色别名、叙事线程与审计记录 |
| GET | `/api/novels/{id}/conflicts?chapter_number={chapter}` | 获取确定性冲突的证据链、影响范围与人工修复建议(只读) |
| POST | `/api/novels/{id}/canon` | 在人工审查阶段治理事实或角色,随后重新质检 |
| GET | `/api/novels/{id}/memory/quality` | 获取记忆检索质量评测历史 |
| POST | `/api/novels/{id}/memory/evaluate` | 运行当前向量索引的 Recall@K/MRR 评测 |
| POST | `/api/novels/{id}/memory/rebuild` | 从 SQLite 终稿、Canon 与分层索引重建向量记忆并可同步评测 |
| GET | `/api/novels/{id}/chapters/{chapter}/versions` | 获取章节版本历史 |
| GET | `/api/novels/{id}/chapters/{chapter}/candidates` | 获取章节候选稿、规则评分和选择状态 |
| GET | `/api/novels/{id}/chapters/{chapter}/versions/diff` | 比较两个章节版本 |
| GET | `/api/novels/{id}/planning/{blueprint|scene}/versions` | 获取蓝图或分镜版本历史 |
| GET | `/api/novels/{id}/planning/{blueprint|scene}/versions/{version}` | 获取规划版本完整结构化载荷 |
| GET | `/api/novels/{id}/planning/{blueprint|scene}/versions/diff` | 比较两个规划版本 |
| POST | `/api/novels/{id}/chapters/{chapter}/versions/{version}/evaluations` | 对章节版本运行规则评测或规则 + 模型评审 |
| GET | `/api/novels/{id}/chapters/{chapter}/evaluations` | 获取章节评测历史 |
| PUT | `/api/novels/{id}/chapters/{chapter}/evaluations/{evaluation}/baseline` | 设置章节回归基准 |
| GET | `/api/novels/{id}/chapters/{chapter}/evaluations/compare` | 比较两个已评测版本 |
| GET | `/api/novels/{id}/book-audits` | 获取按终稿哈希幂等保存的全书审计历史 |
| GET | `/api/novels/{id}/memory` | 获取章节、幕与全书三级长期记忆索引 |
| GET | `/api/novels/{id}/usage` | 获取作品模型调用、耗时与 token 统计 |
| GET | `/api/novels/{id}/traces` | 获取脱敏的 Agent 模型调用轨迹，可按 Agent 筛选 |
| POST | `/api/evaluations/benchmarks` | 运行固定质量评测样本，可选模型评审与历史基准比较 |
| GET | `/api/evaluations/benchmarks` | 获取评测运行历史 |
| GET | `/api/evaluations/benchmarks/{run}` | 获取一次评测运行及逐样本回归结果 |
| GET | `/api/model-settings` | 获取脱敏模型档案与模型分工 |
| POST/PUT/DELETE | `/api/model-settings/profiles` | 管理模型服务档案 |
| PUT | `/api/model-settings/routes` | 保存创作/分析/嵌入模型分工 |
| POST | `/api/model-settings/profiles/{id}/test` | 测试聊天或嵌入模型连接 |
| GET | `/healthz` | 健康检查 |

## 人工审查协议(interrupt)

新建作品可启用规划审批。该选项在 React 工作台默认开启，在 API 与旧客户端中默认关闭以保持兼容。
启用后，正文生成前增加两个持久检查点：

- `blueprint_review`：在 PlotPlanner 后审阅并编辑世界观、角色与完整章节大纲。提交时重新校验角色名、
  章节完整覆盖和叙事线程规则，并重建 Canon。
- `scene_review`：每章在 ScenePlanner 后审阅并逐场编辑目标、冲突、转折、地点、人物、情绪与字数预算。
  提交时重新校验连续编号、必要字段和 narrative beat 唯一分配，并归一化字数预算。

两个规划审批点与终稿审查共用 `/jobs/resume`、SQLite 任务事件和 LangGraph 检查点。关闭浏览器或刷新页面
不会丢失待审内容；审批通过前不会调用 SceneWriter 生成正文。

每次进入规划审批时会按结构化内容哈希幂等保存“生成稿”，审批通过时保存“批准稿”。蓝图版本按作品
独立编号，分镜版本按章节独立编号。工作台可以比较任意两个版本，并将历史版本载入当前编辑器；载入
不会直接推进工作流，仍需人工批准后才会成为新的批准稿。规划快照属于辅助历史，SQLite 写入失败只记录
警告，不会破坏 LangGraph 检查点或跳过审批。

图运行至 `human_review` 节点时暂停,流返回:

```json
{"type": "interrupt", "chapter_number": 1, "title": "...", "content": "...", "scene_plan": [...], "issues": [...]}
```

恢复方式:
- **通过**:`feedback: "approve"` → 章节定稿(chapters append + SQLite 持久化),进入下一章
- **修改意见**:任意文本 → 作为 revision_notes 注入 SceneWriter 重写本章
- **场景修改**:`feedback: "...", scene_number: 2` → SceneRewriter 只替换第 2 场,其余场景逐字保留
- **版本恢复**:`version_number: 3` → 恢复 v3 草稿并重新执行一致性检查
- **候选稿选择**:`candidate_id: "candidate_..."` → 采用候选稿并重新执行一致性检查
- **Canon 治理**:`POST /canon` → 更新结构化设定并重新执行一致性检查,正文保持不变

一致性检查发现 `high` 严重问题时,自动回写重写(上限 `MAX_REVISION_ATTEMPTS` 次,超限转人工裁决)。

长期记忆可通过 `python -m scripts.memory_quality --novel-id <id> --rebuild --json` 手动评测或重建。评测样本由当前世界观、角色、大纲、终稿章节和 Canon 自动生成,索引重建使用稳定记录 ID 并先清除旧 collection,避免过期向量残留。

检查点保存在 `CHECKPOINT_DB_PATH`。CLI 与 API 可顺序接管同一作品并跨进程恢复。
作品等待人工审查时重复调用 `/run` 返回 HTTP 409,必须改用 `/resume`。

旧版本创建且已有部分终稿、但没有 LangGraph 检查点的作品只能查看和导出。系统不会静默重建设定或覆盖旧章节。

## 可恢复后台任务

React 工作台使用 `/jobs/*` 接口驱动创作、人工审查恢复和 Canon 重新质检。创建任务后，图执行在
API 后台协程中继续，不依赖发起请求的浏览器连接。任务状态、当前节点、错误和递增事件序列均写入
SQLite；刷新页面后，工作台从作品状态读取活动任务，并用 `after_sequence` 继续拉取尚未处理的事件。

每部作品同一时刻只允许一个 `queued/running` 任务。运行期间模型配置保持只读，避免半途切换路由。
工作台可主动取消任务；取消若发生在已完成节点之后，LangGraph 检查点仍保留，作品显示为
`interrupted` 并允许从检查点继续。服务关闭或异常重启时，失去执行协程的活动任务也会被标记为
`interrupted`，而不是长期误显示为运行中。

后台任务创建时会在 SQLite 中预留 Worker 租约，执行期间按 `RUN_JOB_HEARTBEAT_SECONDS` 续租；
其他 API 进程只有在租约过期后才能领取同一任务。续租失败时旧执行协程会主动停止，不再提交节点事件
或任务终态。每个 API 进程还会周期检查过期租约并将失去心跳的任务标记为 `interrupted`，用户随后
可从 LangGraph checkpoint 继续。`RUN_JOB_LEASE_SECONDS` 应大于心跳间隔，系统会自动把心跳限制在
租约时长的一半以内。正常关闭只中断当前 Worker 持有的任务，不影响其他健康进程。

任务终态包括 `waiting_review`、`completed`、`failed`、`cancelled` 和 `interrupted`。旧的 `/run`、
`/resume` 与 `/canon` NDJSON 接口继续保留用于 CLI 和兼容客户端。

## 结构化 Canon

Canon v3 从世界观 YAML、角色档案和章节大纲构建结构化权威状态，维护带稳定 ID 的世界事实、
角色最近出场、planned/final 章节时间线、章节事件地点以及跨章节叙事线程。SceneWriter 与 ConsistencyChecker
都会优先读取当前章节附近的 Canon 上下文，避免长篇创作只依赖模糊向量检索。

工作台顶栏的“设定治理”在人工审查阶段开放写入，支持：

- 新增或编辑世界事实、章节事实。
- 将事实标记为 `deprecated`，或重新确认为 `active`；已废止事实保留在数据中，但不会进入 Agent Prompt。
- 合并角色别名；后续章节即使继续使用别名，出场记录也会归入规范角色。
- 编辑角色身份、性格、关系、语言习惯、行为准则和角色弧光。
- 新增或编辑叙事线程，调整优先级、引入章、截止章和 planned/open/resolved/abandoned 状态。
- 为线程维护逐章 setup/develop/resolve beat，并明确每个 beat 的承载场景。
- 为每次操作强制记录原因、操作目标、变更前后值、操作者和时间，保留最近 200 条审计记录。

Canon 写操作只允许在 `human_review` 暂停态执行。更新后当前草稿会重新经过一致性检查并再次等待
人工审批，不会自动重写草稿，也不会静默修改任何 SQLite 终稿。向量同步失败只记录警告，不会
回滚已经写入 LangGraph 检查点的 Canon 变更。

章节通过人工审查并成功写入 SQLite 后，Canon 才会推进为 final 并同步写入 Chroma。SQLite 定稿
失败时 Canon 保持原状，重复 approve 可安全重试。Canon v1/v2 检查点会无损补齐 v3 的事实状态、
稳定 ID、别名表、叙事线程和审计表；完全缺少 Canon 的旧检查点则从已有世界观、角色、大纲和终稿章节即时
重建，不修改旧章节内容。

## 叙事线程与剧情债务

PlotPlanner 使用结构化 `narrative_beats` 规划跨章节伏笔、谜团、任务、关系变化和叙事承诺。
同一线程在各章使用稳定名称，每个 beat 明确 `setup`、`develop` 或 `resolve` 动作；主要线程必须在
全书大纲中拥有回收节点。旧大纲的 `foreshadowing` 文本会自动转换为兼容线程。

ScenePlanner 必须把本章每个 beat 分配到且只分配到一个场景，SceneWriter 与 ConsistencyChecker
会同时读取线程生命周期和场景分配。确定性检查会直接报告以下剧情债务：

- 线程超过 `due_chapter` 仍处于 planned/open。
- 最终章结束前 major 线程仍未 resolved/abandoned。
- 本章计划 beat 缺失，或章节 beat 与场景分配不一致。

工作台项目顶部显示开放与逾期线程数；“设定治理 → 叙事线程”可人工调整线程、状态和 beat。所有
人工调整仍要求填写原因，并在重新执行一致性检查后回到人工审查。

## 场景级规划

每个新章节在正文生成前由 ScenePlanner 拆解为 1-8 个连续场景。场景计划包含叙事目标、核心
冲突、结尾转折、地点、出场角色、主导情绪和字数预算；系统会归一化预算，使总和与章节目标
一致。SceneWriter 必须按该顺序完成正文，ConsistencyChecker 也会读取同一计划进行语义检查。

自动一致性重写和人工修改意见会保留当前场景计划，避免修订时无故改变章节结构；章节通过后
计划随终稿写入 SQLite，下一章再清空并重新规划。旧检查点若直接停在 SceneWriter，会自动生成
单场景兼容计划继续运行。

SceneWriter 与 StyleEditor 使用内部场景边界维护 `scene_drafts`，面向读者的章节正文不会显示边界
标记。人工审查可选择整章或任一场景提交意见；场景级修改只调用 SceneRewriter 替换目标段落，
随后直接重新执行一致性检查。旧草稿缺少场景边界时，系统会按场景字数预算确定性重建边界。

## 章节版本历史

每次草稿进入人工审查时，系统会按正文哈希幂等保存章节快照，并区分初稿、整章修订、场景修订、
历史恢复和最终定稿。工作台可选择任意两个版本查看统一 Diff，也可恢复旧版本；恢复只替换当前
待审草稿，不会直接覆盖 SQLite 终稿，并且必须重新通过一致性检查和人工审批。

## 多候选章节探索

章节进入人工审查后，工作台可以后台生成 2-4 个相互独立的完整候选稿。每个候选会沿用当前
场景计划、Canon、长期记忆和风格档案，并采用不同的因果、人物、氛围或节奏侧重点；用户也可以
补充本轮创作方向。候选稿经过 StyleEditor 润色和固定规则评分后独立写入 SQLite。

生成过程不会推进 LangGraph 检查点，也不会覆盖当前草稿或 SQLite 终稿。工作台可并排查看当前稿
与任一候选稿，并在同一批候选之间反复切换。明确选择后，候选稿才会成为当前草稿，并重新经过
一致性检查、自动质量门和人工审批。若正文、场景计划或 Canon 已发生变化，旧候选会被拒绝，避免
把过期上下文生成的正文恢复到新的审查状态。

## 结构化创作约束

创建小说时可以提交 `creative_brief`，它会随作品持久化到 SQLite，并复制到 LangGraph 状态，贯穿世界观、角色、全书大纲、分镜、正文、局部修订、风格润色、一致性检查、未来重规划和全书终审。字段包括：

- `target_audience`、`age_rating`：目标读者和内容分级。
- `point_of_view`、`narrative_tense`、`narrative_distance`：视角、时态和叙事距离。
- `ending_tone`：结局基调；`themes`、`must_include`、`avoid_content`：主题、必须包含与回避内容。
- `intensity`：`romance`、`mystery`、`action`、`darkness` 四项 0-5 强度。
- `notes`：补充说明。

旧 API 客户端无需修改；省略 `creative_brief` 时系统使用稳定默认值。React 工作台在新建作品时提供结构化选择、滑杆和列表输入，作品页顶部显示视角与分级摘要，并可随时查看和编辑当前约束。

每次实际变更都会生成递增版本；`PUT /creative-brief` 可提交 `expected_version` 做乐观锁校验，版本落后时返回 HTTP 409，避免覆盖另一客户端刚保存的修改。内容未变化的重复保存保持幂等，不产生新版本。活动创作任务运行期间约束只读，防止单次模型调用链混用不同版本。

若作品正停在章节人工审查，保存新约束不会改写当前草稿，但会清空旧质检结果、标记需要重新质检，并把现有候选稿标记为 `stale`。过期候选仍可用于对比，但不能再被采用；工作台自动发送 `recheck`，草稿重新通过一致性检查和质量门后才能批准。检查点恢复时也会以 SQLite 中的最新约束和版本为准。

## 终稿事实提炼

章节通过人工审查后、写入终稿前，ChapterDigest 会只依据实际正文重新生成章节摘要，并提取关键事件、
实际出场角色、地点、主导情绪和需要跨章保持一致的事实。后续 Canon、SQLite 章节记录和 Chroma 长期
记忆均使用这份终稿提炼结果，不再把创作前的大纲摘要当作实际剧情摘要。

提炼结果带有 schema 版本和正文 SHA-256 哈希。SQLite 定稿失败时，已完成的提炼会保留在 LangGraph
检查点中；再次批准时若正文未改变，系统直接复用该结果，不重复调用模型。正文发生修改或恢复其他
版本后哈希失效，下一次批准会重新提炼。

## 分层长篇记忆

每章批准并完成正文提炼后，系统会从全部终稿重建三级索引：章节叶节点保留实际摘要、事件、角色、
地点、事实与首尾锚点；每 5 章聚合为一个幕节点；所有幕节点再组成全书概览。索引带有固定 schema
版本和 SHA-256 哈希，按内容幂等保存到 SQLite，并以稳定 ID 同步到 Chroma。

SceneWriter 同时读取当前章节附近的幕与章节锚点、Canon 和语义检索结果；ConsistencyChecker 在返修
早期章节时也能看到相关后续终稿；BookAuditor 使用完整幕级概览补足各章首尾片段的截断限制。旧检查点
缺少索引时会从已有终稿即时重建，不修改章节正文或 Canon。索引持久化或向量同步失败只记录警告，
不会阻止章节定稿。

## 动态重规划

当前章定稿并完成事实提炼后，Replanner 会比较实际成稿与原章节计划，并只检查当前章之后的未来大纲。
若因果链发生变化，模型只能提交未来章节补丁；系统会强制保留已完成章节、章节总数和编号，校验补丁后
合并未提交字段，并同步更新 Canon 的未来时间线与非人工管理的叙事线程。

重规划结果包含影响等级、原因、schema 版本和完整合并后大纲，并作为 `replanned` 蓝图版本保存。
最终章没有后续大纲时不会调用模型；重规划失败只保留原大纲，不影响已经完成的章节定稿。

## 质量评测与回归基准

每次一致性检查完成后，主工作流会自动运行确定性质量门，计算篇幅达成、结构完整、场景执行、剧情 beat
覆盖、重复控制和一致性六项指标。综合分低于 `QUALITY_GATE_THRESHOLD`，或结构、场景、叙事兑现、
一致性任一关键维度低于 40 分时，系统会把最低分维度转换成明确修订指令并自动回写。达到
`MAX_REVISION_ATTEMPTS` 后仍未通过则停止自动重写，携带完整评分报告进入人工审查。

人工审查阶段可对任意章节版本运行质量评测。规则评测固定计算篇幅达成、结构完整、场景执行、
剧情 beat 覆盖、重复控制和一致性六项指标；可选的模型评审使用固定 rubric 补充连贯性、角色一致、
文体、节奏、场景表现和叙事兑现。每次运行都会保存正文内容哈希、评分 schema/rubric 版本、模型标识、
维度分和结论。

任一评测结果可设为该章的回归基准。后续版本与基准比较时，综合分变化达到 3 分会标记为
`improved` 或 `regressed`，其余标记为 `stable`。模型不可用、超时或结构化输出失败时，API 仍保存并
返回确定性规则结果，评测故障不会影响章节修订、定稿或版本恢复。

最终章批准后，主工作流自动运行一次全书审计。确定性层检查章节完整性、叙事线程回收、角色覆盖、
时间线、章节长度均衡和摘要重复；模型层补充情节连贯、角色弧光、主题兑现、风格一致、结局完成度与
叙事承诺回收。报告按终稿 SHA-256、schema 和 rubric 幂等保存，并在工作台完结页展示分数、发现与
修订优先级。模型终审或辅助存储失败不会阻止作品进入完成态，确定性结果和脱敏错误仍保留在图状态中。

完结页可选择任一终稿章并提交返修要求。系统从已结束的 LangGraph 检查点创建返修工作副本，原 SQLite
终稿在人工批准前保持不变；返修稿重新经过写作、润色、确定性质量门、一致性检查和人工审查。批准后
按章节号替换终稿，清理该章旧的 Canon 事实、角色出场和自动叙事 beat，保留其他终稿与版本历史，
随后按新的全书正文哈希再次运行终审并新增审计记录。

## 配置说明

### 认证与工作区隔离

本地单用户和旧 CLI 默认保持兼容，`AUTH_ENABLED=false` 时所有请求使用内置的本地 owner 身份。生产部署
应设置 `AUTH_ENABLED=true`；此时除 `/healthz`、注册和登录外，所有 `/api/*` 请求都必须携带
`Authorization: Bearer <token>`。会话只在 SQLite 保存 token 的 SHA-256，密码使用带随机盐的 scrypt
哈希，`AUTH_SESSION_HOURS` 控制有效期。

认证接口按“客户端 IP + 登录标识”做窗口限流，`AUTH_RATE_LIMIT_WINDOW_SECONDS` 和
`AUTH_RATE_LIMIT_MAX_ATTEMPTS` 控制窗口与次数，超过后返回 `429` 并附带 `Retry-After`。
限流窗口写入 SQLite 并使用事务锁原子递增，多个 API Worker 共享同一数据库时仍使用同一额度，
不会因为进程扩容而分别放宽保护。
导入、导出、评测、记忆重建和后台创作任务还使用 `SENSITIVE_RATE_LIMIT_WINDOW_SECONDS` 与
`SENSITIVE_RATE_LIMIT_MAX_ATTEMPTS` 做独立资源保护。
服务会记录注册、登录成功/失败、登出、成员与角色变更，以及所有写入型 API 请求的审计事件。
当前租户可通过 `GET /api/audit/logs` 查询最近记录；审计元数据不保存密码、Token 或正文内容。

每个注册用户会创建独立 tenant。小说、后台任务、评测历史、模型服务档案、模型路由和模型调用指标均按
tenant 隔离；跨 tenant 的资源 ID 查询统一返回 404。角色权限为：

- `owner`：管理成员、模型设置和作品删除，也拥有全部创作权限。
- `editor`：创建作品、运行 Agent、提交审查和治理 Canon，但不能删除作品或管理成员/模型密钥。
- `viewer`：只读查看当前工作区的数据。

工作台顶栏的用户按钮提供登录、注册和退出入口。浏览器只保存 Bearer token 与脱敏用户信息；注销后服务端
会话立即失效。跨域部署时 FastAPI CORS 已允许 `Authorization` 请求头。

运行状态接口分为：`GET /healthz` 仅表示进程存活并保持 `{ "status": "ok" }` 兼容返回；
`GET /readyz` 检查 SQLite、LangGraph checkpoint、Chroma 目录和模型回退配置；
`GET /metrics` 输出轻量 Prometheus 风格的请求、失败、活动流和审计写入失败计数。工作台顶栏的
“运行状态与审计”按钮提供同一租户的只读视图，其中 `/api/monitoring/summary` 返回后台创作任务、
传输任务和模型调用的聚合计数，不包含正文或密钥。

SQLite 初始化会在 `schema_migrations` 中分别记录结构化存储与模型设置 schema 版本；`/readyz`
会校验两个组件是否都达到当前代码要求。升级过程中任一迁移未完成时，服务会报告 `not_ready`，避免
负载均衡继续把流量发送到旧结构实例。

外部 Prometheus 可直接使用 `deploy/prometheus.yml` 和 `deploy/novel-agent-alerts.yml`：前者抓取
`/metrics`，后者覆盖 API 不可用、5xx 激增和审计写入失败。生产环境应将 `api:8000` 替换为实际
服务地址，并在 Prometheus/Alertmanager 侧配置通知渠道。

### 运行时全量备份

除了按作品导出的备份，维护脚本还可以对 SQLite、LangGraph checkpoint 和模型主密钥做一致性快照：

```bash
python -m scripts.runtime_backup create --password "备份密码" --keep 7 --confirm-stopped
python -m scripts.runtime_backup verify data/runtime-backups/<备份文件> --password "备份密码"
python -m scripts.runtime_backup restore data/runtime-backups/<备份文件> --password "备份密码" --confirm
```

Docker Compose 部署可先停止 API，再通过一次性维护容器访问同一组命名卷：

```bash
docker compose stop api
docker compose run --rm api python -m scripts.runtime_backup create --password "备份密码" --keep 7 --confirm-stopped
docker compose start api
```

备份使用 SQLite 原生 snapshot、manifest checksum 和可选 AES-GCM 加密；`BACKUP_RETENTION_COUNT`
控制自动清理数量。为保证作品数据库与 LangGraph checkpoint 处于同一逻辑时刻，创建命令要求
`--confirm-stopped`，恢复命令要求 `--confirm`，两者都必须在 API 停止后执行。建议通过宿主机 cron、
Windows Task Scheduler 或编排平台定期执行，并把生成文件复制到独立存储；恢复会先校验所有 checksum 和 SQLite
完整性，再分阶段替换数据库、checkpoint 和 `MODEL_SECRET_KEY_PATH` 对应的主密钥，失败时回滚已替换文件。

### 工作台模型设置

“模型服务”可以同时保存 OpenAI、Anthropic、DeepSeek、通义千问和自定义 OpenAI Compatible
档案。内置地址与模型仅作为快捷值，API 地址和模型名称均可编辑。“模型分工”分别控制：

- **创作模型**：世界观、角色、正文写作和风格润色。
- **分析模型**：大纲规划、场景规划和一致性检查。
- **嵌入模型**：Chroma 长期记忆的向量写入与检索。

创作模型和分析模型都可以额外选择一个备用服务与模型。主模型遇到超时、限流或 5xx 错误时，
系统会按 `MODEL_RETRY_ATTEMPTS` 和 `MODEL_RETRY_BASE_DELAY` 做指数退避；主模型尝试耗尽后自动
切换备用模型。`MODEL_TIMEOUT_SECONDS` 控制单次调用超时，`MAX_NOVEL_TOKENS` 可设置单部作品
累计 token 上限，值为 `0` 时不限制。

每次实际调用尝试都会保存 Agent、用途、模型、主备状态、成功与否、耗时及输入/输出 token。
供应商未返回 usage 时使用本地估算并标记为估算值；工作台项目顶部显示当前累计 token，详细聚合
可通过 `/api/novels/{id}/usage` 查询。模型指标写入或清理失败不会阻断作品定稿与删除。

运行时还会为一次逻辑调用生成稳定的 `call_id`，并为每个重试或备用路由尝试生成独立 `trace_id`。
轨迹保存输入/输出 SHA-256、字符数、模型路由、尝试序号、耗时、token 和错误类型，不保存 Prompt、
正文、模型响应或 API Key。工作台顶栏的调用轨迹面板可以查看最近 100 条记录并按 Agent 筛选；
API 可通过 `limit=1..500` 和可选 `agent` 参数查询。旧数据库启动时会自动补齐轨迹字段。

API Key 使用 Fernet 加密写入 `SQLITE_DB_PATH`，读取接口只返回“已配置”和掩码。主密钥默认
保存在 `MODEL_SECRET_KEY_PATH=data/model-settings.key`。备份或迁移时必须同时保存
`memory/novels.db` 和 `data/model-settings.key`；丢失主密钥后原密文无法恢复，只能重新录入。

工作台未配置三类模型分工时使用 `.env.example` 中的环境配置回退。React 保存的工作区模型路由也会
被 CLI 和 API 读取。小说创作运行期间模型设置保持只读，避免一次流程中途切换模型。

其余环境变量见 `.env.example`：温度、章节数据库与检查点路径、章节字数与重写上限、默认风格，以及
`MAX_IMPORT_BYTES`、`BACKGROUND_TRANSFER_BYTES` 两项传输限制。

`/jobs/*` 后台任务支持多个 API Worker 共享 SQLite 时的租约互斥。CLI、旧 `/run` 流接口与后台任务
之间仍应顺序交接；这些兼容入口没有加入分布式租约，不应与后台 Worker 同时修改同一作品。

## 前后端分离部署

React 工作台通过 FastAPI 的 `/api` 接口通信，开发环境由 Vite 代理到 `http://127.0.0.1:8000`，生产环境可使用 Docker Compose：

```bash
cp .env.production.example .env
# 编辑 .env，替换 FRONTEND_ORIGINS、模型配置和其他部署路径
docker compose up --build
# 浏览器访问 http://localhost:5173
```

Compose 会强制 API 使用 `APP_ENVIRONMENT=production`；若认证未开启、认证限流配置无效，或
`FRONTEND_ORIGINS` 包含 `*`，API 会拒绝启动。生产前端由 Nginx 托管静态资源，并将 `/api`、
`/healthz` 和 `/readyz` 反向代理到 FastAPI。Nginx 会传递真实客户端地址，用于登录限流和审计。

API 和前端容器均启用自动重启、健康检查、`no-new-privileges`、只读根文件系统和 Docker 日志轮转。
API 额外删除全部 Linux capabilities，SQLite、checkpoint、Chroma、模型密钥和传输文件分别保存在
命名卷中。`docker compose down` 不会删除这些数据；仅在明确需要销毁数据时使用 `docker compose down -v`。

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
