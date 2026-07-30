---
description: 澄清、分片保存并发布 Layout v3 Spec Candidate
agent: sdlc-main
subtask: false
---

执行 skill 的 spec 阶段。读取项目根目录的 `.sdlc-pipeline/runtime/references/spec-interview.md`；若
`status.spec_work.active` 为 true，调用 `sdlc_query_spec_work` 恢复临时访谈内容。
若用户反馈或失败 evidence 表明已发布 Spec/测试契约有误，不得直接以普通 spec 调用切换阶段。尚无 active
rework 时，先整理完整的 expected/actual/reproduction/affected IDs/source/evidence，并调用一次
`sdlc_begin_rework`，分类为 `spec` 或 `test_contract`；信息不足时先补问，禁止用自由文本原因代替结构化
Feedback。只有 `sdlc_status.rework.target_phase=spec` 时才进入修订 Candidate 流程；发布新 baseline 后
Core 会将 rework 推进到 `spec_published`，随后才允许 `/sdlc-code`。原 Feedback 和失败 evidence 必须保留。
先查事实，只询问真正阻塞的产品决策。“采用推荐”只保存决策，不发布。大需求按 Feature 和
可独立验收 Requirement 分片持久化；validate 后展示 preview/revision/hash，只有用户明确
“确认发布”才按 candidate ID/hash 批准。
每个 `sdlc_put_requirement` 都必须在同一次请求中带非空 `acceptance_criteria`：每条包含
`given`、`when`、`then`、`source_refs`，但不手填其 `id`。候选中已经确认的事实不足以填写 AC 时先补充
spec work，禁止发送缺失 `acceptance_criteria` 的请求；这种可预防的 schema 错误会消耗 Run 的失败上限。

本次命令参数是用户提供的需求或确认文本，必须在不放宽上述阶段与门禁约束的前提下处理，
不得丢弃；没有参数时再按访谈规则继续：

<user-input>
$ARGUMENTS
</user-input>

项目外文件或目录必须先经 `sdlc_ingest_source(allow_external_copy=true)` 摄取；目录显式使用
`source_type=directory`，误传为 file 时 Core 也会自动识别。受控副本必须保持原格式与相对目录树：
HTML 仍是 HTML、Markdown 仍是 Markdown、PNG 仍是 PNG，禁止把二进制写成 `content.md`。
receipt 中的 text anchor 可通过 `sdlc_query_source` 读取受限原文；asset anchor 查询后返回
`asset_ref`，只能交给支持对应媒体类型的视觉/文档工具，不得按文本读取或臆造语义。后续引用只使用
`source_id/anchor`，绝不再读取项目外原路径。
