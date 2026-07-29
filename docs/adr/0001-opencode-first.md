# ADR-0001：OpenCode-first 与确定性 core

- 状态：Accepted
- 日期：2026-07-25

决定只正式支持 OpenCode，并固定 primary `sdlc-main` 与两个职责互斥的子 agent：
`sdlc-coder` 只写业务代码，`sdlc-tester` 只写 Spec 声明的测试脚本。两个子 agent 都通过
`task-before/task-after` seam 获取 context、提交 handoff；plugin 根据 role 分别触发 code gate
或 `verify_delivery`。确定性 Core 负责 code/test gate、进程生命周期与证据绑定。
用户阶段命令为 init/spec/code/test；status/finalize 是内部工具。

需求、设计、测试计划合并为同一 spec 交互，但保持独立 Markdown artifact 和 compact JSON 索引。生命周期、
追溯、文档渲染、运行现场和版本由 Python core 承担，OpenCode plugin 只作薄 adapter。

Python core 不依赖 OpenCode 的会话或工具模型，是可移植的确定性引擎；OpenCode JavaScript 是当前
宿主 adapter。若未来支持其他宿主，应以新薄 adapter 对接同一 Core，而不是复制状态机、审批与证据
实现，也不在当前版本引入多宿主模板矩阵。

原因是减少固定上下文、宿主兼容分支和 agent 数量，同时保留真实编译、重启、测试、版本证据
这些不能裁剪的闭环能力。
