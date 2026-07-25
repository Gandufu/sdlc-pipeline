---
description: 原子生成独立 requirements、design 与 test-plan，并验证 R→D→T
agent: sdlc-main
subtask: false
---

执行 spec 阶段。先调用 `sdlc_status`，在同一主会话澄清目标、范围、约束、验收标准。
分配永不复用的 R/D/T ID；修改需求用新 R-id 和 supersedes。设计必须引用 scaffold 中真实的
extension point 和允许路径。每个 R-id 至少一个 mandatory T-id，并引用 lifecycle tests 命令。

结构化记录用户原始输入，并明确区分已确认事实、影响范围、假设、待确认问题、风险和决策。
先向用户展示 R/D/T 候选摘要、允许修改路径、风险以及所有 blocking 问题；只有获得明确确认后，
才设置 `spec_confirmed=true`，将三份结构化对象一次性提交给
`sdlc_publish(kind=spec)`。未确认时不得发布正式文档。
增量流程只有机器条件满足且用户确认时启用，否则使用 standard。
