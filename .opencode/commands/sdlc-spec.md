---
description: 澄清、分片保存并发布 Layout v3 Spec Candidate
agent: sdlc-main
subtask: false
---

执行 skill 的 spec 阶段。读取项目根目录的 `.sdlc-pipeline/runtime/references/spec-interview.md`，从 status checkpoint 恢复。
先查事实，只询问真正阻塞的产品决策。“采用推荐”只保存决策，不发布。大需求按 Feature 和
可独立验收 Requirement 分片持久化；validate 后展示 preview/revision/hash，只有用户明确
“确认发布”才按 candidate ID/hash 批准。

本次命令参数是用户提供的需求或确认文本，必须在不放宽上述阶段与门禁约束的前提下处理，
不得丢弃；没有参数时再按访谈规则继续：

<user-input>
$ARGUMENTS
</user-input>

项目外文件必须先经 `sdlc_ingest_source(allow_external_copy=true)` 摄取。摄取 receipt 已给出可引用的
`source_id/anchor`；只可通过 `sdlc_query_source` 读取受限片段，绝不再用 read、grep 等工具读取原外部路径。
