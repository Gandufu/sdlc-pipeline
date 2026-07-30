---
name: sdlc-pipeline
description: OpenCode-first 轻量交付状态机；处理 init/spec/code/test、恢复和版本固化。
---

# SDLC Pipeline

先调用 `sdlc_status`，只执行当前阶段：

- init：读取 status 的模板元数据；需要选择时询问用户；调用一次 `lifecycle(init)`。
- spec：读取项目根目录的 `.sdlc-pipeline/runtime/references/spec-interview.md`；摄取来源、保存阻塞决策、分片构建 Candidate，
  validate 后按用户确认的 ID/hash 发布。
- code：派发 coder；plugin 只传唯一 progressive context manifest；coder 只实现业务代码；
  Core 根据 Git diff 生成证据映射，再统一执行 compile/package/lint/typecheck、启动、readiness，
  并保留预览进程和访问地址
  和停止，不读取或生成测试脚本。
- test：主会话派发唯一 tester 子 agent；tester 编写 Spec selector 指定的 unit 或 functional 测试
  脚本并返回 handoff；plugin 校验后调用一次 `lifecycle(verify_delivery)`。Core 停止 coder 预览、
  确认端口释放，执行 test_preflight，并仅在被选 suite 需要 runtime 时启动、readiness 后执行测试，
  再检查 cleanup；成功后展示候选，用户确认才 finalize。

工具只表达意图：

- `sdlc_ingest_source`：保存原始来源；
- `sdlc_query_source`：按 source_id + anchor 查询受限原文片段；
- `sdlc_save_spec_work`：保存可恢复的临时决策内容；
- `sdlc_query_spec_work`：按需恢复临时决策内容；
- `sdlc_begin_rework`：将人工预览/验收缺陷或自动测试失败登记为结构化 Feedback，并按
  implementation/spec/test_contract 路由返工；
- `sdlc_begin_candidate`：创建可恢复候选；
- `sdlc_put_requirement|design|verification`：逐个写入小 artifact；
- `sdlc_validate_candidate`：生成 diagnostics、preview 和冻结 hash；
- `sdlc_approve_candidate`：只用 ID/hash/confirmed 原子发布；
- `sdlc_lifecycle(init|verify_delivery)`：隐藏内部生命周期；
- `sdlc_finalize`：用户确认后固化版本。

判断交给 AI：是否需要额外阻塞问题、模块实现、读取哪些业务资源。
硬事实交给 Core：Schema、anchor、allowed/protected path、Git evidence、PID identity、policy、
原子产物、失败熔断和最终交付验证。

code gate 通过后发现缺陷时，不直接重复派发 coder，也不做 Git 回滚。主会话先收集 expected、actual、
复现步骤、受影响 R/D/T/AC、Source 和 evidence，调用 `sdlc_begin_rework`。implementation 在同一 Run
中重新完成 code/test；spec 或 test_contract 先发布修订 baseline。只有重新通过 delivery gate 后
Feedback 才 resolved；已结束 Run 的缺陷另建修复 Task/Run。
