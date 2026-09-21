# ADR-002：以版本化 OpenAPI 契约连接独立前端和后端

## 状态

Accepted

## 决策

后端提供 \`/api/v1\`，在 CI 生成并校验 OpenAPI artifact；前端使用生成的 TypeScript 客户端和运行时 schema，不再导入后端源码、Python 类型或相对路径文件。旧 \`/api\` 保持兼容别名，直到迁移稳定窗口结束。

## 原因

- 独立仓库必须能在没有 Python 仓库的情况下构建。
- 手写前端请求类型已经分散在 \`frontend/src/api.ts\` 和 \`types.ts\`，容易发生漂移。
- OpenAPI diff 可以把破坏性变更放入代码评审。

## 约束

- 只做向后兼容的加法变更；删除或修改字段必须先发布新版本。
- 错误、分页、任务事件、幂等和版本冲突都属于公共契约。
- SSE/轮询事件使用同一事件 envelope，客户端可按 sequence 续传。

## 被拒绝方案

- GraphQL：当前异步任务、流式事件和文件传输并不适合先引入另一套协议。
- 前端直接读取数据库或共享 Python model：破坏仓库独立性和安全边界。
- 只维护 Markdown API 文档：无法自动生成类型和执行兼容检查。
