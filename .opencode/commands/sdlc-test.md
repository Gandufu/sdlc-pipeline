---
description: 派发唯一 executor，执行全部 mandatory T-id，生成结果并请求版本固化确认
agent: sdlc-main
subtask: false
---

执行 test 阶段。先调用 `sdlc_status`，必须已有真实 compile/restart/health/artifact 证据。
仅派发一次 `sdlc-executor`。executor 通过
`sdlc_lifecycle(action=execute_test_plan)` 执行计划并返回逐 T-id handoff；校验后主会话调用
`sdlc_lifecycle(action=record_test_results)` 复用与当前 spec/lifecycle/source 绑定的 runner
evidence，生成固定格式结果和精简摘要，不重复执行测试命令。

失败时保留现场，不创建 tag。全部 mandatory 用例通过时展示 Vxxxx 候选、R/D/C/T、
测试与 Token 摘要，并询问用户是否固化。不要在同一轮自行假定确认；用户明确确认后才调用
`sdlc_finalize`。
