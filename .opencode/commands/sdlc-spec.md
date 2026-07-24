---
description: 原子生成独立 requirements、design 与 test-plan，并验证 R→D→T
agent: sdlc-main
subtask: false
---

执行 spec 阶段。先调用 `sdlc_status`，在同一主会话澄清目标、范围、约束、验收标准。
分配永不复用的 R/D/T ID；修改需求用新 R-id 和 supersedes。设计必须引用 scaffold 中真实的
extension point 和允许路径。每个 R-id 至少一个 mandatory T-id，并引用 lifecycle tests 命令。

将三份结构化对象一次性提交给 `sdlc_publish(kind=spec)`，不得直接编辑正式文档。
增量流程只有机器条件满足且用户确认时启用，否则使用 standard。
