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

不得提交 R/D/T/AC ID、`requirement_ids`、`design_ids`、`acceptance_criteria_ids`、
`test_key` 或 `selector`；Core 统一生成关联，
extension point 只从 `sdlc_status.spec_contract.extension_points` 选择。
若 `sdlc_spec` 返回错误，原样报告并立即停止，不搜索实现、不猜格式、不重试。

优先读取 `input.md`、用户明确点名的参考文件和现有项目架构；判断影响范围时可按需读取
项目源码、测试和配置，避免与当前需求无关的全目录扫描。完整 CSS/JS/图片可留给 Coder
实现时展开；大型协议优先搜索需求涉及的接口局部。

Spec 读取只做提示和观测，不做权限门禁或固定次数限制。记录本轮已读取路径；同一路径内容没有
变化且没有新的明确理由时不得重复读取。可以按需求复杂度读取必要的 HTML、CSS、JavaScript、
协议、目录结构和项目文件；信息足够即 prepare，不为追求“完整理解”继续扩展无关上下文。

Verification 按 unit/functional 层级和执行方式合并；同层级的多个验收断言写进同一项
Verification，不得为每个验收点生成独立测试文件。

不摄取 Source，不保存临时访谈，不建立 Candidate revision，不处理会话恢复。
