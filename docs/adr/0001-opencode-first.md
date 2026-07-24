# ADR-0001：OpenCode-first 与确定性 core

- 状态：Accepted
- 日期：2026-07-25

决定只正式支持 OpenCode，并固定 `sdlc-main`、`sdlc-coder`、`sdlc-executor` 三个角色。
用户阶段命令为 init/spec/code/test；status/finalize 是内部工具。

需求、设计、测试计划合并为同一 spec 交互，但保持独立 JSON/Markdown 产物。生命周期、
追溯、文档渲染、运行现场和版本由 Python core 承担，OpenCode plugin 只作薄 adapter。

原因是减少固定上下文、宿主兼容分支和 agent 数量，同时保留真实编译、重启、测试、版本证据
这些不能裁剪的闭环能力。
