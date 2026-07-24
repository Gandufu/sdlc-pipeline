---
description: 派发唯一 executor，执行全部 mandatory T-id，生成结果并请求版本固化确认
agent: sdlc-main
subtask: false
---

执行 test 阶段。先调用 `sdlc_status`，必须已有真实 compile/restart/health/artifact 证据。
仅派发一次 `sdlc-executor`。其 handoff 校验后，调用 `sdlc_lifecycle(action=test)` 重放
测试计划命令并保存完整日志和精简摘要。

失败时保留现场，不创建 tag。全部 mandatory 用例通过时展示 Vxxxx 候选、R/D/C/T、
测试与 Token 摘要，并询问用户是否固化。不要在同一轮自行假定确认；用户明确确认后才调用
`sdlc_finalize`。
