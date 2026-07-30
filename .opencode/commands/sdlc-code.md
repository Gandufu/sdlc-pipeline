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

当用户在 code gate 通过后的人工预览/验收中报告缺陷，或 test attempt 已失败时，不得直接重复派发 coder。
先把用户已明确提供的事实和现有 evidence 整理为完整 Feedback，并调用一次 `sdlc_begin_rework`：
`origin` 区分 `manual_preview`、`manual_acceptance`、`automated_test`；`classification` 必须判断为
`implementation`、`spec` 或 `test_contract`；同时提供 `summary`、`expected`、`actual`、非空
`reproduction_steps`、当前 Spec 中的 `affected_ids`，以及可为空的 `source_refs`、`evidence_refs`。
不能从现有信息确定预期、实际结果、复现步骤或影响范围时，先向用户补问，禁止编造后调用。

只有工具返回 `target_phase=code` 时，才派发一次聚焦 `sdlc-coder`，修复 Feedback 指向的业务代码并重新执行
完整 code gate。若返回 `target_phase=spec`，立即报告需要执行 `/sdlc-spec` 发布修订 baseline，不得派发
coder。已有 active rework 时继续恢复该 rework，禁止为同一缺陷重复登记 Feedback。

在不满足 code failure retry 且没有 active rework 的情况下，`sdlc_status.gates.code=true` 表示 code
阶段已完成，应报告预览入口并停止本会话，不得借由 `/sdlc-code` 重复构建。

本次命令参数可能包含人工反馈、复现信息或修复意图，必须按上述 Feedback 合同处理，不得丢弃：

<user-input>
$ARGUMENTS
</user-input>

无论常规 code 阶段还是上述 retry/返工，都不得调用任何 `sdlc_lifecycle` action（特别是
`verify_delivery`），不得自行进入 test 阶段；测试只能由用户后续明确执行 `/sdlc-test`。
