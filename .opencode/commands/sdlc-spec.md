---
description: 澄清、分片保存并发布 Layout v3 Spec Candidate
agent: sdlc-main
subtask: false
---

执行 skill 的 spec 阶段。读取项目根目录的 `.sdlc-pipeline/runtime/references/spec-interview.md`；若
`status.spec_work.active` 为 true，调用 `sdlc_query_spec_work` 恢复临时访谈内容。
若 journal 为 `state=failed, phase=test`，不得直接以普通 spec 调用切换阶段。仅当本次参数明确要求
“受控规格修订”且失败 evidence 证实已发布 Spec 与固定来源存在偏移时，先调用一次
`sdlc_rework_spec_after_test_failure`，reason 精确说明偏移与 evidence；否则报告并停止。该入口只允许
一次规格返工，保留原失败 evidence，不能作为测试失败的通用绕过方式。
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

项目外文件必须先经 `sdlc_ingest_source(allow_external_copy=true)` 摄取。摄取 receipt 已给出可引用的
`source_id/anchor`；只可通过 `sdlc_query_source` 读取受限片段，绝不再用 read、grep 等工具读取原外部路径。
