# ADR 0006：合同驱动的测试套件与交付预检

- 状态：Accepted
- 日期：2026-07-29
- 首次实现版本：`0.18.0`
- 取代：ADR 0005 中“只允许 functional Verification”的部分

## 背景

ADR 0005 正确地把 code gate 的工程控制与 tester 的功能验证分开，但将 `tests` 收紧成唯一
`functional` 键。这使 tester 无法在 Spec 中声明并维护既有 unit 测试，也无法在 tester 交付测试
源码后统一执行 lint、typecheck 和完整 unit suite。Electron 的 `pnpm start` 包装进程还会使 Core
记录的 PID 与实际 Forge 运行进程脱节，造成 renderer 白屏或测试阶段错误复用旧运行时。

## 决策

1. lifecycle Schema 升级到 v1.1，同时继续读取 v1.0；v1.1 的每个测试套件必须声明
   `requires_runtime`，允许 selector 时必须声明 `selector_patterns`。
2. Verification `level` 支持 `unit` 与 `functional`；selector 的可用路径由对应 lifecycle suite
   校验，而不是由 Core 硬编码框架或文件后缀。
3. v1.1 合同必须声明 `test_preflight`。Core 在 tester handoff 后、启动 test runtime 前顺序执行它，
   失败时记录证据并阻止 runtime/test 执行。
4. Core 仅在当前 test-plan 至少一个 suite 的 `requires_runtime` 为真时启动并 health-check runtime。
   unit-only 交付不启动应用；functional 仍在 readiness 后执行。
5. 脚手架作为 Adapter，选择具体命令、selector 模式和运行时启动方式；Core 不内置 Electron、
   Playwright、Vitest 或 Spring Boot 逻辑。Electron Forge Adapter 直接调用 Forge CLI，而非 pnpm
   包装进程。

## 结果

- tester 的精确路径授权不变，仍不能修改业务代码或未在 Spec 中声明的测试文件。
- 模板能在交付验证中捕获 unit 测试与 UI 演进失配，而不是由 Codex 临时修改测试绕过。
- v1.0 项目维持原 functional-only 行为；新模板采用 v1.1。
