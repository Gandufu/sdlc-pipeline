# ADR-0006：以角色与 context 隔离取代目录 ACL

- 状态：Accepted
- 日期：2026-07-30

## 背景

`sdlc-main`、`sdlc-coder` 和 `sdlc-tester` 的目标是支持不同模型承担架构、编码和测试职责。
旧实现把这种职责分工表达成目录和工具限制：main 不能编辑，coder 不能读取测试，tester
只能写测试目录，plugin 还在每次写入前调用 Core 做路径校验。这使 agent 无法检查上一阶段
产物，也把宿主权限策略错误地下沉到了确定性 Core。

## 决策

1. `sdlc-main` 是完整主会话，拥有项目读取、编辑和命令能力，负责生命周期决策、回退和派发。
2. `sdlc-coder` 与 `sdlc-tester` 同样拥有完整项目读取、编辑和命令能力。
3. 两个子代理通过 OpenCode task 获得独立 context，只接收各自的 task prompt、Core
   即时生成的紧凑阶段 brief 和必要的上一阶段 handoff 摘要，不继承主会话或另一子代理的推理；
   brief 不作为文件持久化。
4. 角色通过模型配置、任务目标、context 和 handoff 合约区分。项目可以在 `opencode.json`
   中分别为 main、coder、tester 选择模型。
5. plugin 不再对 `read/edit/write/bash` 调用实施目录 ACL；Core 不再提供 `write-check`
   或 `path-check`。
6. Spec 的 extension point 和 `scope_paths` 继续描述设计范围，但只作为上下文与审计信息。
   `validate_diff` 记录范围偏离，不因目录本身拒绝交付。
7. handoff 仍检查阶段交付职责：coder 必须产生实现交付，tester 必须提供声明的测试目标；
   compile/package/readiness 和权威 Test gate 仍由 Core 执行。
8. tester context 必须包含 coder handoff 引用，使测试模型能独立检查上一阶段产物。

## 结果

- main 可以处理架构调整和异常恢复，不再被误当成只读路由器。
- coder/tester 可以读取完整项目并使用不同模型独立判断。
- Core 保持 host-independent，只维护状态、正式产物引用、handoff 和确定性执行证据。
- 范围偏离仍可被审计，但不会在工具调用前制造额外失败和重试。
