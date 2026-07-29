# 术语

| 术语 | 定义 |
|---|---|
| Adapter | `.opencode` 中的薄宿主集成；不拥有状态机 |
| Core | `runtime/scripts/sdlc_core` 中的确定性 Python 模块 |
| Contract | `contracts/lifecycle.json`、`scaffold.json` 与 `active-rules.json` |
| Compact index | 只含 ID、状态、引用、hash、关系和时间的受限 JSON |
| Markdown record | 通用 work/evidence 正文；可包含 structured record，不用于正式 R/D/T |
| Artifact document | 使用 frontmatter 和固定标题文法的原生 Requirement、Design 或 Verification Markdown |
| Spec Work | 发布前保存已解决决策、事实、假设和风险的可恢复临时工作内容，不是聊天记录 |
| Source | 一份来源 Markdown，以及 anchor offset/hash 索引 |
| Candidate | `work/candidates` 中可分片修改、尚未正式批准的 Spec |
| Baseline | `docs/sdlc/baselines` 中经精确 hash 批准的自包含正式 Spec |
| Publication receipt | Candidate 清理后保留的紧凑批准索引，绑定 candidate、revision、content hash 与 baseline |
| Current pointer | `docs/sdlc/current.json`；只指向一个 baseline |
| Run | `state/runs` 中的生命周期流转索引及其 work/evidence 引用 |
| Attempt | 一个可幂等追踪的 Core 操作；结果和错误正文不存 JSON |
| Active rules | init 写入 `contracts/active-rules.json` 的规则 hash 索引 |
| Delivery Trace | code/test 后依据真实 Git diff 与测试证据生成的 R→D→C→T 关系 |
