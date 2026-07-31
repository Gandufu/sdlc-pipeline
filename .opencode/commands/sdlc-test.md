---
description: 人工验收通过后编写测试并执行权威验证
agent: sdlc-main
subtask: false
---

用户参数只指以下标记之间的内容，命令正文不是用户输入：

<user-input>
$ARGUMENTS
</user-input>

读取状态。仅当 `<user-input>` 内去除空白后仍非空、且不是完整的
`<sdlc-feedback>...</sdlc-feedback>` 时，才将其中内容逐字调用
`sdlc_task(record_input)`；标记内容为空时禁止记录任何输入。完整的
`<sdlc-feedback>` 是当前阶段的监督/测试修复反馈，只透传给 Tester，绝对不得写入
`input.md`。

- Task 位于 Human Review 时才调用一次 `review_passed`，然后读取一次最新状态。
- Task 已位于 Test 时禁止再次调用 `review_passed`，直接派发 Tester。
- Test 中发现测试实现问题：调用 `sdlc_task(transition, test_issue)`。
- Test 中发现业务实现问题：停止并提示使用 `/sdlc-code`。
- Test 中发现需求或验收错误：停止并提示使用 `/sdlc-spec`。

这是纯编排命令。派发前禁止调用 `read`、`glob`、`grep`、`bash` 或 `edit`，禁止读取
input、Spec、Verification、业务源码、测试、handoff 或目录列表；这些内容由 hook 生成的
紧凑阶段 brief 交给 Tester。main 只允许调用本命令要求的 `sdlc_status`、
`sdlc_task` 和一次 `task`。

只有 Task 位于 Test 时行动。若 `sdlc_status.test_reverify_available=true`，先且只调用一次
`sdlc_lifecycle(action=reverify_test)`，成功即进入 Awaiting Release Approval，失败原样报告并停止；
不得再次派发 Tester。否则派发一次 `sdlc-tester`。tester 使用独立 context 检查 coder 产物，
以正式 Verification 测试为主要交付；hook 自动执行权威验证，成功后 Task 进入
Awaiting Release Approval。
普通派发的 task prompt 不得复述需求、Spec、Verification 或读取步骤；非空用户测试反馈只能逐字放在
`<sdlc-feedback>...</sdlc-feedback>` 中，由 hook 单独透传。
