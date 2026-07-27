---
description: 原子生成独立 requirements、design 与 test-plan，并验证 R→D→T
agent: sdlc-main
subtask: false
---

执行 spec 阶段。先调用 `sdlc_status`，在同一主会话澄清目标、范围、约束、验收标准。
分配永不复用的 R/D/T ID；修改需求用新 R-id 和 supersedes。设计必须引用 scaffold 中真实的
extension point 和允许路径。每个 R-id 至少一个 mandatory T-id，并引用 lifecycle tests 命令。

结构化记录用户原始输入，并明确区分已确认事实、影响范围、假设、待确认问题、风险和决策。
正式文档使用中文：R/D/T 的 title、description、acceptance criteria、分析、测试前置条件、输入与预期
均须使用中文；原始输入、代码标识、命令、协议字段与用户明确要求的英文内容保持原样。
先向用户展示 R/D/T 候选摘要、允许修改路径、风险以及所有 blocking 问题；只有获得明确确认后，
才设置 `spec_confirmed=true`，将三份结构化对象一次性提交给
`sdlc_publish(kind=spec)`。未确认时不得发布正式文档。
增量流程只有机器条件满足且用户确认时启用，否则使用 standard。

发布前必须读取 `.sdlc-pipeline/schemas/spec.schema.json`，并以其作为唯一 payload 契约。
`payload` 顶层必须是对象，至少包含：`schema_version: "1.0"`、`flow: "standard"`、
`spec_confirmed: true`、`requirements`、`design`、`test_plan`。其中 `requirements` 不是数组，
必须是 `{source_inputs, analysis, items}` 对象；`design` 和 `test_plan` 都是 `{items}` 对象。
所有 ID 固定为四位数字：`R-0001`、`D-0001`、`T-0001`（不能写成 `R-001`）。
