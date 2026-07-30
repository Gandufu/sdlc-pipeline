---
description: 人工验收通过后编写测试并执行权威验证
agent: sdlc-main
subtask: false
---

读取状态。本次参数非空时先逐字调用 `sdlc_task(record_input)`。

- Human Review 通过：调用 `sdlc_task(transition, review_passed)`。
- Test 中发现测试实现问题：调用 `sdlc_task(transition, test_issue)`。
- Test 中发现业务实现问题：停止并提示使用 `/sdlc-code`。
- Test 中发现需求或验收错误：停止并提示使用 `/sdlc-spec`。

只有 Task 位于 Test 时派发一次 `sdlc-tester`。tester 只修改正式 Verification 声明的测试脚本；
hook 自动执行权威验证，成功后 Task 进入 Awaiting Release Approval。
