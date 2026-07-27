---
name: sdlc-pipeline
description: OpenCode-first 项目交付状态机。执行 init/spec/code/test、查询状态或固化已确认版本时使用。
---

# SDLC Pipeline

机器真值是 JSON，Markdown 由 runner 渲染。主会话不得直接修改 `docs/sdlc` 正式产物。

阶段门禁：

1. init：幂等状态检查 → 用户从已登记模板元数据中选择 → adapter/scaffold → probe → install → compile → start → health/artifact → stop。
2. spec：读取 `.sdlc-pipeline/references/spec-interview.md`；先查事实，再用 `question` 一次只问一个
   决策问题。每题给 2–3 个候选答案、标注推荐项并允许自定义答案；共享理解经用户确认后，
   原子发布固定风格 requirements、design、test-plan，并校验 R→D→T。
3. code：唯一 coder → handoff/diff/path 校验 → runner compile/restart/verify。
4. test：唯一 executor → mandatory 测试 → 结果 → 用户确认 → internal finalize。

按需调用四个深接口：`sdlc_status`、`sdlc_publish`、`sdlc_lifecycle`、
`sdlc_finalize`。只把受影响 ID、路径、hash、失败尾部和 context pack 路径传给模型；
完整日志保留在 `.sdlc-pipeline/runs/logs`。

init 先用 `sdlc_status.init_state` 幂等判定；没有项目合约时必须展示 `templates` 元数据并等待
用户明确选择，即使只有一个模板也不得自动选择。之后只调用一次 `sdlc_lifecycle(action=init)`。
init 根据模板元数据中的 `rules` 生成 `.sdlc-pipeline/rules/active.json`；后续 context pack 只加载
其中列出的框架规则，不因发行包中存在 `java.md` 等其他规则而加载无关内容。
