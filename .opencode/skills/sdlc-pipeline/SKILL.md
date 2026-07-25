---
name: sdlc-pipeline
description: OpenCode-first 项目交付状态机。执行 init/spec/code/test、查询状态或固化已确认版本时使用。
---

# SDLC Pipeline

机器真值是 JSON，Markdown 由 runner 渲染。主会话不得直接修改 `docs/sdlc` 正式产物。

阶段门禁：

1. init：在当前项目目录导入内置/GitHub 模板 → adapter/scaffold → probe → install → compile → start → health/artifact → stop。
2. spec：同一会话原子发布独立 requirements、design、test-plan，并校验 R→D→T。
3. code：唯一 coder → handoff/diff/path 校验 → runner compile/restart/verify。
4. test：唯一 executor → mandatory 测试 → 结果 → 用户确认 → internal finalize。

按需调用四个深接口：`sdlc_status`、`sdlc_publish`、`sdlc_lifecycle`、
`sdlc_finalize`。只把受影响 ID、路径、hash、失败尾部和 context pack 路径传给模型；
完整日志保留在 `.sdlc-pipeline/runs/logs`。

init 必须由主会话直接调用 `sdlc_lifecycle(action=init)`。不得使用 bash/Python runner
代替深接口，也不得要求用户执行手工命令。`/sdlc-init` 本身授权 runner 自动安装模板合约
明确声明的缺失系统工具；未声明安装方式时返回真实失败，不向用户编造绕过步骤。
