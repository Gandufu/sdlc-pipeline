---
description: 澄清、分片保存并发布 Schema v2 Spec Candidate
agent: sdlc-main
subtask: false
---

执行 skill 的 spec 阶段。读取项目根目录的 `.sdlc-pipeline/references/spec-interview.md`，从 status checkpoint 恢复。
先查事实，只询问真正阻塞的产品决策。“采用推荐”只保存决策，不发布。大需求按 Feature 和
可独立验收 Requirement 分片持久化；validate 后展示 preview/revision/hash，只有用户明确
“确认发布”才按 candidate ID/hash 批准。
