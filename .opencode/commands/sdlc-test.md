---
description: 编写 Playwright 测试并执行一次权威交付验证
agent: sdlc-main
subtask: false
---

执行 skill 的 test 阶段。只派发一次 `sdlc-tester` task，任务描述保持简短；plugin 会替换为
唯一 tester context manifest。tester handoff 校验后，plugin 自动调用一次 `verify_delivery`。
本阶段只编写 Spec selector 指定的 Playwright functional 测试。Core 先停止 coder 预览并确认端口
释放，再执行 T-id 绑定的 Playwright 脚本；脚本负责启动、验证和关闭 Electron，Core 最后复查端口
与进程 cleanup；不重新 compile、lint 或 package，也不修改业务源码。
失败时报告分类、指纹和日志路径，
成功时展示版本候选并等待用户确认。
