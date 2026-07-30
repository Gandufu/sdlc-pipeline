---
description: 记录原始需求并一次性准备或发布正式 Spec
agent: sdlc-main
subtask: false
---

先读取状态。本次参数非空时，逐字调用 `sdlc_task(record_input)`：

<user-input>
$ARGUMENTS
</user-input>

如果当前为 Human Review/Test 且本次指出需求或验收错误，先调用
`sdlc_task(transition, requirements_issue)`。

只询问真正阻塞范围或验收的一项问题。信息充分后一次构造完整 R/D/T，并调用
`sdlc_spec(prepare)`；展示 preview/hash 后停止。如果本次消息是对上一轮 preview 的明确发布确认，
以相同 Spec 和 hash 调用 `sdlc_spec(approve, confirmed=true)`。

不摄取 Source，不保存临时访谈，不建立 Candidate revision，不处理会话恢复。
