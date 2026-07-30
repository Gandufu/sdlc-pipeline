# Feedback/Rework 生命周期

## 问题

code gate 通过并启动人工预览后，用户仍可能发现实现、Spec 或测试契约缺陷。过去只有失败 test 到 code/spec
的若干提示词分支，没有统一的持久化反馈对象；重复调用 `/sdlc-code` 可能被已通过 gate 拒绝，coder 也无法
读取 Feedback 引用的受限 Source。

## 契约

`sdlc_begin_rework` 是唯一返工入口。主会话提交：

- `origin`：`manual_preview`、`manual_acceptance` 或 `automated_test`；
- `classification`：`implementation`、`spec` 或 `test_contract`；
- expected、actual、复现步骤、受影响 R/D/T/AC；
- 可选的 Source anchor 与 evidence 引用。

Core 校验当前 Spec、Run、来源和受影响 ID，分配 `FB-xxxx`，在
`.sdlc-pipeline/evidence/feedback/` 保存证据，并把 rework 状态写入当前 Run。

## 状态推进

```text
reported
  ├─ implementation ─> code_verified ─> verified/resolved
  └─ spec|test_contract ─> spec_published ─> code_verified ─> verified/resolved
```

- Feedback active 时，旧 code/test 成功证据不能让流程越过返工门禁。
- `spec`/`test_contract` 在新 Candidate 获得明确发布确认前禁止派发 coder。
- `implementation` 允许一次受 Feedback 约束的 coder 派发，仍需完整 code gate。
- code gate 只推进到 `code_verified`；权威 delivery gate 成功才 resolve。
- 已结束或 finalize 的 Run 不改写，缺陷进入新的修复 Task/Run。

## 上下文与 Source 权限

coder brief 只携带当前 Feedback 的结构化摘要和引用。`sdlc_query_source` 对 coder 的授权同时要求：

1. 存在 active coder attempt；
2. anchor 出现在当前 Spec 或 active Feedback；
3. requester 是 `sdlc-coder`。

主会话仍可在 Spec 阶段查询已摄取来源；tester 不获得该工具。

## 恢复原则

不做 Git 回滚，也不删除旧 evidence。`sdlc_status.rework` 暴露 feedback ID、目标阶段、stage 和状态；
会话中断后按该状态恢复。相同缺陷存在 active Feedback 时不得重复登记，交付验证失败则保留 active 状态供
下一次显式修复。
