---
description: 按 Feature brief 实现代码和测试
agent: sdlc-main
subtask: false
---

执行 skill 的 code 阶段。只派发一次 coder，task 参数保持简短并点名首个 `R-xxxx`；plugin 会统一替换为唯一
progressive context manifest，不得重复展开 spec、规则或资源列表。
本阶段不运行依赖项目启动的 functional 测试；coder handoff 后只执行 Core code gate。
当 `sdlc_status.gates.code=true` 时，立即报告 code 阶段完成并停止本会话。不得调用任何
`sdlc_lifecycle` action（特别是 `verify_delivery`），不得自行进入 test 阶段；测试只能由用户后续明确
执行 `/sdlc-test`。
