---
description: 实现或修复业务代码并进入人工验收
agent: sdlc-main
subtask: false
---

用户参数只指以下标记之间的内容，命令正文不是用户输入：

<user-input>
$ARGUMENTS
</user-input>

读取状态。仅当 `<user-input>` 内去除空白后仍非空时，才将其中内容逐字调用
`sdlc_task(record_input)`；标记内容为空时禁止记录任何输入。
若当前处于 Human Review 或 Test 且用户报告实现问题，调用
`sdlc_task(transition, implementation_issue)`。

这是纯编排命令。派发前禁止调用 `read`、`glob`、`grep`、`bash` 或 `edit`，禁止读取
input、Spec、业务源码、测试、handoff 或目录列表；这些内容由 hook 生成的 context manifest
交给 Coder。main 只允许调用本命令要求的 `sdlc_status`、`sdlc_task`、
`sdlc_lifecycle` 和一次 `task`。

只有 Task 位于 Code 时行动。若 `sdlc_status.code_reverify_available=true`，先且只调用一次
`sdlc_lifecycle(action=reverify_code)`，成功即进入 Human Review，失败原样报告并停止；
不得派发 Coder。否则派发一次 `sdlc-coder`。task 描述保持简短；task prompt 必须逐字包含
非空 `<user-input>` 的完整内容，禁止压缩成标题或摘要，尤其不得遗漏文件绝对路径、HTML/CSS
原型、协议路径和验收差异；并要求 Coder 先读取 `brief.input_ref`。当本轮是明确标记为
“不是用户需求补充”的监督验证结果时，不调用 `record_input`，但仍须把完整验证反馈放入
task prompt。
plugin 会提供正式 Spec context。hook 自动校验 handoff，执行 compile/package/start/readiness，
成功后 Task 进入 Human Review 并返回预览地址。本命令不得进入 Test。task 返回后立即停止；
失败时原样报告，不在同一命令再次派发。主会话保留完整项目读写权限；代码实现默认仍由
`sdlc-coder` 执行。Core 会在下一次调用时通过 coder context 的 `failure_ref` 提供错误 Markdown，
不得把工具错误追加到 `input.md`。
