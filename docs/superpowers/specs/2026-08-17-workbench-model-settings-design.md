# 工作台模型配置与管理设计

## 背景

当前聊天模型和嵌入模型都由 `Config()` 从环境变量读取。`models/llm.py`
还在外层缓存完整模型实例，因此运行期间修改配置既没有工作台入口，也可能继续复用旧模型。

本次改造面向本机单用户部署。工作台将能够保存多个模型服务、加密管理 API Key，
并分别选择创作、分析和嵌入模型。保持现有 CLI、API、检查点恢复和环境变量配置兼容。

## 目标

- 在 React 工作台中新增模型设置入口。
- 支持 OpenAI、Anthropic、DeepSeek、通义千问和任意 OpenAI 兼容服务。
- 同时保存多个服务档案，并在档案之间快速切换。
- 独立配置创作模型、分析模型和嵌入模型。
- API Key 加密落盘，任何读取接口都不返回明文。
- 设置更新后，后续模型调用使用新配置，不复用旧连接参数。
- 没有工作台设置时继续使用现有环境变量。

## 非目标

- 不实现多用户、认证、权限或云端密钥托管。
- 不为每部小说保存独立模型配置。
- 不提供用量计费、配额统计或模型自动发现。
- 不迁移或删除现有 `.env` 内容。
- 不在一次正在执行的创作流中切换模型。

## 数据模型

模型设置与小说数据共用 `sqlite_db_path`，新增两张表。

### `model_profiles`

- `id TEXT PRIMARY KEY`：稳定 UUID。
- `name TEXT NOT NULL UNIQUE`：工作台显示名称。
- `provider TEXT NOT NULL`：`openai`、`anthropic`、`deepseek`、`qwen` 或
  `openai_compatible`。
- `base_url TEXT`：OpenAI 兼容端点；Anthropic 可为空并使用 SDK 默认地址。
- `api_key_encrypted BLOB`：Fernet 密文，不保存明文。
- `chat_models_json TEXT NOT NULL`：可选聊天模型名称数组。
- `embedding_models_json TEXT NOT NULL`：可选嵌入模型名称数组。
- `created_at TEXT NOT NULL`、`updated_at TEXT NOT NULL`。

### `model_routes`

- `purpose TEXT PRIMARY KEY`：`creative`、`analysis` 或 `embedding`。
- `profile_id TEXT NOT NULL`：引用 `model_profiles.id`。
- `model_name TEXT NOT NULL`：实际提交给供应商的模型名称。
- `updated_at TEXT NOT NULL`。

三个路由在同一个事务中更新。删除被任何路由引用的档案返回冲突，不自动改写路由。

## 密钥保护

新增 `MODEL_SECRET_KEY_PATH`，默认指向 `data/model-settings.key`。首次保存密钥时：

1. 原子生成 Fernet 主密钥文件。
2. 在支持 POSIX 权限的平台将文件限制为当前用户读写。
3. 使用主密钥加密 API Key，再将密文写入 SQLite。
4. 主密钥路径和 SQLite 运行数据均保持在 Git 忽略范围内。

主密钥不存在但数据库已有密文时，不重新生成并覆盖。后端返回明确的不可解密错误，要求用户
重新录入密钥。日志不得包含明文密钥、Authorization 请求头或供应商完整错误响应。

读取档案只返回：

- `has_api_key: boolean`
- `api_key_masked: string`，例如 `sk-...9x2a`

更新档案时省略 `api_key` 或传空字符串表示保留旧密钥。清除密钥必须使用显式
`clear_api_key: true`，避免表单空值误删。

## 供应商适配

后端把供应商品牌与协议驱动分开：

- `anthropic` 使用 `ChatAnthropic`。
- `openai` 使用 `ChatOpenAI` 和 OpenAI 默认地址。
- `deepseek`、`qwen`、`openai_compatible` 使用带 `base_url` 的 `ChatOpenAI`。
- 嵌入路由使用带 `base_url` 的 `OpenAIEmbeddings`；Anthropic 档案不能作为嵌入路由。

内置模板只提供推荐地址与模型名称。用户始终可以手动输入模型名称；系统不假设供应商模型
列表长期不变。

## 运行时解析

新增 `ModelSettingsStore` 负责数据库、事务、加解密和脱敏，新增 `ModelResolver` 负责把路由
解析为 LangChain 模型参数。

`get_llm()` 不再缓存“读取 Config 的结果”。每次 Agent 构造时先解析当前路由，再调用内部
模型工厂。内部工厂可以按完整的不可变连接参数缓存客户端，因此设置变化会产生新的缓存键，
不会继续使用旧 provider、模型、地址或密钥。

调用对应关系：

- 世界观、角色、场景写作、风格润色使用 `creative`。
- 大纲规划、一致性检查使用 `analysis`。
- `NovelMemory` 使用 `embedding`。

若数据库中尚未配置三类路由，解析器使用现有 `Config` 环境变量作为兼容回退。环境回退只在
内存中解析，不会自动把环境变量密钥复制进 SQLite。工作台会显示当前处于“环境配置回退”状态。

## API

新增接口：

- `GET /api/model-settings`：返回供应商模板、脱敏档案、三类路由和配置来源。
- `POST /api/model-settings/profiles`：创建档案。
- `PUT /api/model-settings/profiles/{profile_id}`：更新档案。
- `DELETE /api/model-settings/profiles/{profile_id}`：删除未被引用的档案。
- `PUT /api/model-settings/routes`：原子更新三类路由。
- `POST /api/model-settings/profiles/{profile_id}/test`：测试指定聊天或嵌入模型。

连接测试请求包含 `kind` 和 `model_name`。聊天测试发送最小提示并要求简短响应；嵌入测试只
嵌入固定短文本。响应包含 `ok`、`latency_ms` 和脱敏后的诊断信息。

验证规则：

- 档案名称、供应商、地址和模型名称做长度与格式校验。
- OpenAI 兼容服务必须使用 `http` 或 `https` 地址。
- 三类路由必须引用存在的档案和非空模型名称。
- `embedding` 路由不能引用 Anthropic 档案。
- 被路由引用的档案删除返回 HTTP 409。
- 无效输入返回 HTTP 422；缺失档案返回 HTTP 404。
- 检测到当前进程有创作流正在运行时，设置写接口返回 HTTP 409。

## 工作台界面

顶栏新增齿轮图标，打开模型设置对话框。对话框使用两个页签：

### 模型服务

左侧是服务档案列表和新增按钮，右侧是当前档案表单：

- 供应商模板
- 显示名称
- API 地址
- API Key 密码输入框和已配置状态
- 聊天模型名称列表
- 嵌入模型名称列表
- 测试连接、保存、删除

选择内置供应商时自动填充推荐地址和模型，但允许编辑。已保存密钥不会写回输入框；只有输入
新值才覆盖。测试和保存期间禁用对应按钮并显示明确进度。

### 模型分工

依次显示创作、分析和嵌入三行配置。每行先选择服务档案，再从该档案的模型列表选择模型，也
允许直接输入模型名称。保存时三类路由原子提交。

创作流运行期间仍可查看设置，但新增、保存、删除、测试和路由切换按钮全部禁用。API 同时做
冲突校验，避免仅依赖前端限制。

## 错误处理

- 模型配置不完整时，在运行图之前返回可操作的错误信息。
- 模型调用失败继续使用现有 NDJSON `{type: "error", message}` 事件。
- 密钥解密失败与供应商认证失败使用不同诊断文本。
- 供应商异常先清除 URL 查询参数、请求头和可能的密钥片段，再记录和返回。
- 嵌入写入继续是可降级能力；失败只记录警告，不回滚 SQLite 终稿。
- 设置保存使用事务，任一步失败都不留下部分路由。

## 兼容性与迁移

- 现有小说、章节、进度和 LangGraph 检查点不迁移。
- 现有 `LLM_PROVIDER`、`MODEL_NAME`、`OPENAI_API_KEY`、`ANTHROPIC_API_KEY` 和
  `EMBEDDING_MODEL` 在未设置工作台路由时继续生效。
- CLI 与 Streamlit 通过同一个 `ModelResolver` 读取 SQLite 设置，因此在 React 工作台保存后，
  三个入口使用相同模型路由。
- 已经暂停在人工审查的作品恢复后使用恢复时的全局路由，不保存作品级模型快照。

## 测试策略

后端单元与集成测试覆盖：

- 密钥密文不等于明文，正确主密钥可恢复，错误或缺失主密钥给出诊断异常。
- 创建、脱敏读取、更新保留旧密钥、显式清除密钥和删除档案。
- 被路由引用的档案不可删除，三类路由原子更新。
- Anthropic 不能被选作嵌入路由。
- OpenAI、Anthropic、DeepSeek、Qwen 和自定义兼容档案生成正确客户端参数。
- 路由或密钥更新后不复用旧模型参数。
- 空数据库使用环境变量回退。
- API 响应和日志不出现明文密钥。
- 运行中的设置修改返回 409。
- 连接测试成功、认证失败和网络失败路径。

前端验证覆盖 TypeScript 类型检查和生产构建，并通过浏览器检查：

- 新增、编辑、测试和删除服务档案。
- 密钥掩码与留空保留语义。
- 三类模型切换和保存后的重新加载。
- 运行期间控件禁用。
- 桌面和移动视口不存在溢出或遮挡。

最终运行完整 pytest、ruff、compileall、前端 typecheck、前端 build 和 Docker build；Docker
不可用时明确记录未执行项。

## 已确认假设

- 应用主要在本机由单个用户使用。
- 配置是全局的，不按作品隔离。
- 创作、分析和嵌入模型分别配置。
- 密钥加密存入 SQLite，本机主密钥单独保存。
- 首期供应商范围为 OpenAI、Anthropic、DeepSeek、通义千问和 OpenAI Compatible。
