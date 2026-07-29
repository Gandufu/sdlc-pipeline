---
description: 编写合同声明的测试并执行一次权威交付验证
agent: sdlc-main
subtask: false
---

执行 skill 的 test 阶段。派发前逐项检查已发布 Verification 的 `expected` 已覆盖本次要求的固定
外部服务响应、错误情境与可观察结果；缺少时报告 Spec 缺口，不得把约束静默丢弃或交给 tester 猜测。
只派发一次 `sdlc-tester` task，任务描述保持简短但保留这些已发布精确断言和 preflight 维护要求；
plugin 会替换为唯一 tester context manifest。tester handoff 校验后，plugin 自动调用一次
`verify_delivery`。
若 OpenCode 丢失 tester 的最终 JSON，Core 仅在非空受限测试 diff 且所有声明 selector 都存在时生成带
`output_recovery` 标记的收据并继续这一次验证；不能以此补写测试、放宽路径检查或再次派发 tester。
本阶段只编写 Spec selector 指定的 unit 或 functional 测试。Core 先停止 coder 预览并确认端口释放，
执行 lifecycle 合约声明的 test_preflight；只有被选测试套件声明 `requires_runtime: true` 时才启动
运行时、完成 readiness 并运行测试，最后复查端口与进程 cleanup；不修改业务源码。
失败时报告分类、指纹和日志路径，
成功时展示版本候选并等待用户确认。
