---
name: sdlc-pipeline
description: OpenCode-first 轻量 Task 状态机；处理 spec/code/review/test/finalize。
---

# SDLC Pipeline

先调用 `sdlc_status`，只执行当前 Task 阶段：

- Spec：逐字记录用户输入；一次准备完整 R/D/T；展示 preview/hash。
- Awaiting Spec Approval：只有用户明确确认才发布正式 baseline。
- Code：派发独立 context 的 coder；Core 接收 handoff 并执行 compile/package/start/readiness。
- Human Review：实现问题回 Code，需求问题回 Spec，通过后进入 Test。
- Test：独立 context 的 tester 检查 coder 产物并交付 Verification 测试；实现问题回 Code，测试实现问题留在
  Test，需求或验收错误回 Spec。
- Awaiting Release Approval：用户确认后 finalize。
- Finalized：后续问题由新的关联 Task 处理。

插件只保存用户原始 `input.md`、Task 状态/事件、正式 baseline 和最终执行证据。
不摄取 Source，不保存临时 Spec Work/Candidate revision，不管理 OpenCode 会话恢复。

工具：

- `sdlc_status`
- `sdlc_task(record_input|transition)`
- `sdlc_spec(prepare|approve)`
- `sdlc_lifecycle(init)`
- `sdlc_finalize`

`sdlc_spec` 输入不携带 R/D/T/AC ID、R/D/T 关联、测试命令或测试路径；Core 统一生成。
extension point 只从 `sdlc_status.spec_contract` 选择。首次校验失败后报告并停止，
不得搜索插件实现或猜格式重试。

main、coder、tester 都拥有完整项目读写能力，角色由模型、独立 context、任务目标和 handoff
区分，不使用目录 ACL 模拟角色。Spec 按需读取项目和用户参考；完整 CSS/JS/图片可在 Code 阶段展开。
