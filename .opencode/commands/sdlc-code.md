---
description: 实现或修复业务代码并进入人工验收
agent: sdlc-main
subtask: false
---

读取状态。本次参数非空时先逐字调用 `sdlc_task(record_input)`。
若当前处于 Human Review 或 Test 且用户报告实现问题，调用
`sdlc_task(transition, implementation_issue)`。

只有 Task 位于 Code 时派发一次 `sdlc-coder`。task 描述保持简短，点明本次需求或缺陷；
plugin 会提供正式 Spec context。hook 自动校验 handoff，执行 compile/package/start/readiness，
成功后 Task 进入 Human Review 并返回预览地址。本命令不得进入 Test。
