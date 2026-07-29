# ADR 0005：分离 Code 工程控制与 Functional 测试

- 状态：Accepted
- 日期：2026-07-29
- 首次实现版本：`0.17.0`

## 背景

旧 lifecycle 为了让 policy 可执行，把 `lint`、`static_analysis`、`unit` 和 `integration`
全部放入 `tests`。其中 `integration` 与 `static_analysis` 实际都可能只是 typecheck，
导致工程控制被误称为功能测试，也让 tester 与 coder 的职责边界不清晰。

当前流程已经规定 coder 不读取或编写测试脚本；coder handoff 后由 Core 执行 compile/package、
lint、typecheck、启动、readiness 和停止。tester 是独立子 agent，只编写 Spec selector 指定的
Playwright functional 脚本。

## 决策

1. lifecycle `commands` 明确声明 `lint` 和 `typecheck`；policy executable verifier 使用
   `command_key` 引用它们。
2. lifecycle `tests` 只保留可由 Verification `test_key` 引用的 `functional` 执行器。
3. Verification `level` 固定为 `functional`，并要求 selector 指向 `tests/functional/` 下的脚本。
4. 模板仓库的 Vitest 属于模板维护者自检，不是 Feature tester 的交付职责。
5. Playwright MCP 可用于非权威探索，但 functional 脚本必须使用项目依赖并由 Core 确定性执行。

## 结果

- code gate 与 test gate 不再共享同一组逻辑键。
- `integration=typecheck`、`static_analysis=typecheck` 等伪测试映射被删除。
- 这是最新版契约的直接替换，不保留旧 lifecycle policy 字段兼容。
