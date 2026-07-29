# ADR-0004：原生 Markdown Spec 产物

- 状态：Accepted
- 日期：2026-07-29
- 首次实现版本：`0.16.0`

## 背景

Storage Layout v3 已将 JSON 控制面与 Markdown 内容面分离，但 Requirement、Design 和
Verification 仍使用包含完整 JSON fenced block 的 Markdown structured record。它便于机器读取，
却不是适合人工评审和长期归档的正式文档。Candidate revision 和 baseline manifest 中还残留
title 等叙述性字段，也没有在删除临时 Spec Work 前固化阻塞决策的理由。

## 决策

1. Requirement、Design、Verification 使用 frontmatter 加固定标题文法的原生 Markdown；
2. frontmatter 是 Markdown 正文的一部分，只保存身份、关系和短执行字段；
3. JSON 索引只保存 ID、关系 ID、状态、路径、hash、计数和时间，不保存 title、goal 或理由；
4. Core 将 Markdown 解析为内存领域对象，再使用既有 JSON Schema 验证；
5. artifact hash 对规范化后的完整 Markdown 计算，文档自身不保存 content hash；
6. Source 的正文、offset anchor 和 hash 机制不变；
7. Spec Work 继续保存已解决决策、事实、假设和风险以支持中断恢复，不保存聊天全文；
8. validate 将 resolved decision 冻结进 Candidate 并纳入 content hash；发布原样复制到 baseline，
   验证 baseline 后再清理 Spec Work 和 Candidate；
9. publication receipt 保留批准三元组和 baseline 指针，使 Candidate 清理后仍可幂等重试；
10. 不读取旧 structured-record R/D/T，不维护双格式或双写路径。

## Markdown hash 规范

Core 将 CRLF 和 CR 转为 LF，删除每行尾随空白，删除文件首尾空行，并在文件末尾保留一个换行。
SHA-256 对该规范化 UTF-8 内容计算。Candidate 聚合 hash 继续使用
`candidate_id + content_hash + confirmed=true` 审批边界，artifact hash 只存于外部索引。

## 后果

- 人工可以直接评审和归档单篇 R/D/T；
- AC 标题和 frontmatter 关系可以确定性校验；
- `spec.md` 只是从正式文档生成的评审汇总，不是第二事实源；
- 发布成功后临时工作内容可以清理，同时保留决策依据和幂等发布凭据；
- 旧项目需要重新 init/spec，不能依赖旧 R/D/T 读取兼容。
