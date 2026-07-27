---
name: sdlc-pipeline
description: OpenCode-first 轻量交付状态机；处理 init/spec/code/test、恢复和版本固化。
---

# SDLC Pipeline

先调用 `sdlc_status`，只执行当前阶段：

- init：读取 status 的模板元数据；需要选择时询问用户；调用一次 `lifecycle(init)`。
- spec：读取 `references/spec-interview.md`；摄取来源、保存阻塞决策、确认后发布 Feature Contract。
- code：派发 coder；plugin 只传唯一 progressive context manifest；Core 根据 Git diff 生成证据映射，
  再统一执行 compile/package/lint/typecheck code gate；不运行依赖项目启动的 functional 测试。
- test：调用一次 `lifecycle(verify_delivery)`；只启动候选、检查 readiness、运行无头浏览器
  functional T-id 并 cleanup；成功后展示候选，用户确认才 finalize。

工具只表达意图：

- `sdlc_ingest_source`：保存原始来源；
- `sdlc_query_source`：按 source_id + anchor 查询受限原文片段；
- `sdlc_save_checkpoint`：保存可恢复决策；
- `sdlc_publish_contract`：发布已确认功能契约；
- `sdlc_lifecycle(init|verify_delivery)`：隐藏内部生命周期；
- `sdlc_finalize`：用户确认后固化版本。

判断交给 AI：是否需要额外阻塞问题、模块实现、读取哪些业务资源。
硬事实交给 Core：Schema、anchor、allowed/protected path、Git evidence、PID identity、policy、
原子产物、失败熔断和最终交付验证。
