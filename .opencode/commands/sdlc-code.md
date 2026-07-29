---
description: 按 Feature brief 只实现业务代码
agent: sdlc-main
subtask: false
---

执行 skill 的 code 阶段。只派发一次 coder，task 参数保持简短并点名首个 `R-xxxx`；plugin 会统一替换为唯一
progressive context manifest，不得重复展开 spec、规则或资源列表。
coder 不得读取或修改测试脚本；coder handoff 后由 Core code gate 依次执行
compile/package/lint/typecheck、启动与 readiness，并保留预览进程供用户检查。完成后必须报告
模板声明的访问地址；若模板没有 HTTP 地址，则明确报告桌面应用已启动。
当 `sdlc_status.gates.code=false` 且 journal 为 `state=failed`、`phase=code`、
`last_failure.class=code`、`last_failure.repeat_count=1` 时，先读取 failure evidence，再只派发一次
聚焦 `sdlc-coder` 修复该确定性业务代码失败。不得把 `journal.recoverable` 视为同 phase retry 的阻止条件；
Core 会保留失败 evidence 并在同一 code phase 创建下一 attempt，重新执行完整 code gate。若重复次数不是
1 或 Run 已 blocked，则报告并停止，禁止重试。

在不满足上述 code failure retry 条件的常规情况下，当 `sdlc_status.gates.code=true` 时，立即报告 code
阶段完成并停止本会话。唯一例外是：
`sdlc_status.journal.state=failed`、`journal.phase=test`，并且本次 `$ARGUMENTS` 明确要求“返工”或
“修复代码”。此时先读取失败 evidence，确认是业务代码问题后，只派发一次聚焦的 `sdlc-coder` 修复已发布
范围内的代码；不得修改测试、配置或 Spec。该 task 会由 Core 以 `code` phase 原子记录
`run.rework_started`，并重新执行完整 code gate。没有这三个条件时不得借由 `/sdlc-code` 重复构建。

无论常规 code 阶段还是上述 retry/返工，都不得调用任何 `sdlc_lifecycle` action（特别是
`verify_delivery`），不得自行进入 test 阶段；测试只能由用户后续明确执行 `/sdlc-test`。
