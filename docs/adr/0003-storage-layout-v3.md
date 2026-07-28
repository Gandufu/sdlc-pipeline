# ADR-0003：Storage Layout v3

- 状态：Accepted
- 日期：2026-07-28
- 首次实现版本：`0.15.0`

## 决策

采用控制面/内容面分离的 Storage Layout v3：

1. `.opencode` 是唯一宿主 adapter；
2. `.sdlc-pipeline/runtime` 保存已安装 Core 资源；
3. `contracts` 保存生命周期、脚手架和 active rules；
4. `state` 的 JSON 只保存索引、ID、引用、hash 与流转状态；
5. `work` 和 `evidence` 的正文使用 Markdown structured record；
6. Candidate revision 引用独立 artifact Markdown，不复制完整候选；
7. 正式 Spec 发布为自包含 Markdown baseline，`current.json` 只作指针；
8. 测试结果和版本完整证据写 Markdown，JSON manifest 仅作 compact 索引。

## 原因

将会话、结果和错误正文写入状态 JSON 会造成体积膨胀、重复、截断和解析失败，也让最终成功掩盖中间
错误。通过 Store Module 统一不变量，状态机可以快速读取小索引，人工仍能直接审阅 Markdown，hash
门禁则保持确定性和可追溯性。

## 不兼容变更

本版本处于开发调试阶段，不提供旧布局迁移或读取：

- 删除 `.sdlc-pipeline/runs` 和 `.sdlc-pipeline/opencode`；
- 删除顶层 runtime 资源目录和旧合同位置；
- 删除 Schema v2 目录、Candidate manifest/pointer/approval schema；
- 删除 `docs/sdlc/bundles`、`spec-current.json` 和 `current/` 镜像；
- 强制升级会清除这些旧受管产物，旧项目应重新 init/spec。
