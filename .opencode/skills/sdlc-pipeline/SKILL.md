---
name: sdlc-pipeline
description: OpenCode-first 项目交付状态机。执行 init/spec/code/test、查询状态或固化已确认版本时使用。
---

# SDLC Pipeline

机器真值是 JSON，Markdown 由 runner 渲染。主会话不得直接修改 `docs/sdlc` 正式产物。

阶段门禁：

1. init：clone → adapter/scaffold → probe → install → compile → start → health/artifact → stop。
2. spec：同一会话原子发布独立 requirements、design、test-plan，并校验 R→D→T。
3. code：唯一 coder → handoff/diff/path 校验 → runner compile/restart/verify。
4. test：唯一 executor → mandatory 测试 → 结果 → 用户确认 → internal finalize。

按需调用四个深接口：`sdlc_status`、`sdlc_publish`、`sdlc_lifecycle`、
`sdlc_finalize`。只把受影响 ID、路径、hash、失败尾部和 context pack 路径传给模型；
完整日志保留在 `.sdlc-pipeline/runs/logs`。
