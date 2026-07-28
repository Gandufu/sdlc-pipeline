# ADR-0003：Schema v2 Candidate 与 post-code Delivery Trace

- 状态：Accepted
- 日期：2026-07-28
- 首次实现版本：`0.14.0`

## 决策

Spec 默认写入流程采用分片 Candidate，而不是一次提交完整 Feature Contract JSON：

1. SourceEnvelope 保存原始输入；
2. Feature Map 只维护 Feature、依赖和 Requirement ID；
3. Requirement、Design、Verification 分别保存为独立 artifact；
4. 每次 put 创建不可变 revision；
5. Core validate 后生成 preview 和稳定 content hash；
6. 用户批准时只提交 candidate ID、hash 和 `confirmed=true`；
7. Core 原子发布只包含 v2 artifact 的 bundle。

Design 只声明 module seam、接口、data contract 和 scaffold extension point，不预测实际代码文件。
code/test 完成后，Core 根据 Git diff、extension point 和测试结果生成 Delivery Trace，并标注
`direct`、`scoped` 或 `shared` 精度。

## 原因

单体 JSON 会随需求规模线性膨胀，容易发生截断、转义和闭合错误，也迫使审批重新传输完整正文。
在 spec 阶段预测精确代码文件还会把不稳定实现细节错误地固化为需求事实。

分片 revision 允许局部重试、跨会话恢复和精确 hash 审批；post-code trace 则让代码映射来自
实际变更与测试证据。

## 不兼容变更

`sdlc_publish_contract`、`feature-contract.schema.json`、旧 publish module 以及聚合
requirements/design/test-plan 文件均已删除。旧客户端必须升级后重新生成 Schema v2 Candidate，
不能把旧 Feature Contract 直接发布到当前版本。
