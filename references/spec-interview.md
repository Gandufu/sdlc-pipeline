# Storage Layout v3 Spec Candidate 澄清规则

先读取项目、scaffold、active policy、lifecycle 与已摄取来源；能从事实得到的答案不询问用户。

只把以下情况视为阻塞决策：

1. 会改变功能范围或非范围；
2. 会改变可观察验收结果；
3. 会改变公开接口、数据来源或错误语义。

一次只问一个问题，通常在三题内完成。若仍有会改变范围、验收或公开接口的阻塞决策，可以继续，
但必须向用户说明影响。每次回答后保存临时 spec work。非阻塞未知项写入 assumptions 或 risks。

调用 `sdlc_save_spec_work` 时，直接传结构化字段 `question`、`source_refs`、
`confirmed_facts`、`assumptions`、`risks`；不要把它们再嵌套为 JSON 字符串，也不要传 `state`、
`decisions` 或 `notes`。每个已回答的阻塞问题保存为一个 `question`（ID 是 `Q-0001` 形式，
`status` 固定 `resolved`），例如：

```json
{"question":{"id":"Q-0001","prompt":"是否新增 IPC？","answer":"采用推荐","status":"resolved","rationale":"需要真实派生状态"}}
```

完整的访谈内容只写入 `work/runs/<RUN>/spec-work.md`；`state/runs/<RUN>/spec-work.json`
仅保存 `content_ref`、hash、ID、状态和 source refs。`sdlc_status.spec_work` 也只返回该索引；
中断后需恢复内容时，调用 `sdlc_query_spec_work`。不要把会话正文、问题或答案写入 JSON 索引。

若附带 `source_refs`，持久化格式是字符串数组，例如 `["SRC-XXXXXXXXXXXX#anchor"]`；也可传
`sdlc_ingest_source` / Candidate 工具返回的 `{source_id, anchor}` 对象，Core 会无损规范化为该字符串。

大需求先建立 Feature Map，再拆成可独立验收的 Requirement。每个 R/D/T 作为独立 artifact
立即保存，不在消息中组装单体 JSON。Requirement 包含目标、角色、范围、非范围、主流程、
异常流程和带 source refs 的 AC；Design 只描述 module/seam/interface/data contract 与
extension point，不预测实际代码文件。写 Design 前必须读取
`.sdlc-pipeline/contracts/scaffold.json`；
`extension_points` 只能逐字使用该文件已声明的 ID，不能编造 `feature` 等泛称。Verification 建立 AC
到 lifecycle 逻辑测试键 `test_key`
（如 `unit`、`integration`、`functional`）的映射，不能填写 `pnpm test` 等 shell command。
`F/R/D/T/AC` ID 由 Core 分配或校验；`feature_id` 可提供语义 hint，Core 会规范化为 `F-xxxx`；尤其不得手填 AC id，Requirement 保存后按所属 R 与顺序
使用 `AC-R-xxxx-yy`。仅当 lifecycle 中该 `test_key` 的 `allow_selector` 为 true 时才填写
`selector`，且必须是 `tests/` 下的项目内相对路径；unit/integration 等不允许 selector 的
test key 必须传 `selector: null`，不要填测试文件名。
正式文档使用项目配置语言（默认中文），代码标识、协议字段和原文保持原样。
Core 将 R/D/T 写成 frontmatter 加固定标题文法的原生 Markdown；不得在正式 artifact 中嵌入
structured-record JSON fenced block。模板位于
`.sdlc-pipeline/runtime/templates/artifacts/`。若 Requirement 或 Design 由已解决的阻塞问题驱动，
通过 `decision_ids` 引用对应 Q-id；Verification 可用 `test_basis` 标记 acceptance、risk、
regression 或 contract 依据，但正文不得重复测试代码步骤。

推荐方案与正式发布是两个独立动作：

1. 用户说“采用推荐”时，只把选项和理由保存到临时 spec work，继续生成候选；
2. 调用 `sdlc_validate_candidate`，展示 preview 路径、revision、content hash、source refs、
   范围、AC、接口与验证映射；
3. 只有用户明确说“确认发布”时，才调用
   `sdlc_approve_candidate(candidate_id, content_hash, true)`。

不得把“采用推荐”“继续”“没问题”等局部答复推断为发布授权。不得让用户或模型在批准时
重发 candidate 正文。Core 负责分片 Schema、跨引用、来源 anchor、revision/hash 校验，
并在批准后原子发布自包含的 Markdown baseline。

validate 时 Core 将 resolved decision 冻结进 Candidate 并纳入 content hash；若之后 Spec Work
决策变化，approve 会要求重新 validate。成功发布时 Core 将冻结版本原样复制到 baseline，再验证
完整 baseline，最后删除对应的临时 spec work 和 Candidate。紧凑 publication receipt 保留批准三元组并支持幂等重试；
若清理失败，发布仍然有效，索引会标记为 `cleanup_pending` 以供后续重试。发布或显式丢弃前，
临时 work 始终保留，因此流程可中断恢复并可追溯。

中断恢复时先读取 `sdlc_status.spec_work`，若 `active` 为 true 则调用 `sdlc_query_spec_work`；再读取
`sdlc_status.spec_candidate`：draft 从当前 revision 继续 put；ready 直接展示原 preview/hash 等待确认；
published 不重复生成。
