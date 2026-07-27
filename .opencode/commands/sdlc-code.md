---
description: 派发唯一 coder，校验 diff，并真实 compile/restart/health/artifact verify
agent: sdlc-main
subtask: false
---

执行 code 阶段。先调用 `sdlc_status` 并确认 init/spec 门禁；如果状态返回任何未解决的
blocking 问题，停止并请用户先回到 `/sdlc-spec` 解决。仅派发一次 `sdlc-coder`；
plugin 会生成最小 context pack、校验 handoff、Git diff、protected paths 与允许范围。
coder task 成功返回后，plugin 的 after hook 会自动调用一次
`sdlc_lifecycle(action=compile_restart_verify)`；主会话不得再次调用，直接读取 runner 证据。

只有 runner 返回 compile、旧实例 stop、新 PID start、health 与 artifact hash 全部通过才成功；
不得采信 agent 自述的 compiled 状态。
