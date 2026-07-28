# 社区中的 Spec、中间状态与知识索引模式

调研日期：2026-07-28

## 结论

当前“用户确认后，由模型重新组装整份长 JSON，再调用发布工具”的做法不合适。它把三件不同的事混在同一次模型输出里：

1. 保存候选内容；
2. 表达用户批准；
3. 发布正式基线。

社区方案更接近以下分层：

- **正式基线**：已审阅的 spec/plan，作为可寻址、可 diff、可恢复的持久 artifact；
- **执行中间态**：独立的 scratch/ledger/ticket 状态，用来恢复进度，不冒充正式基线；
- **大型知识与来源**：拆成小文件，通过索引、链接、来源和生命周期元数据渐进加载；
- **审批动作**：引用已经保存的 artifact，而不是在审批时再次生成 artifact。

因此不应在“按严格 schema 实现”与“采用 OKF 式 wiki + index”之间二选一。对本 SDLC，更合适的是：

- 用 schema、hash、candidate ID 和状态机管理**发布契约与审批**；
- 用 OKF 式小文档、来源链接和生成索引管理**大需求的原文、领域知识与长期上下文**；
- 由正式 contract 引用知识条目，而不是把大段原文重复嵌入一次工具调用。

## 1. obra/superpowers

核对版本：官方仓库 `obra/superpowers`，commit
[`3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9`](https://github.com/obra/superpowers/tree/3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9)。

### 1.1 Spec 和 plan 是正式、可审阅的仓库文件

`brainstorming` 先分段展示设计并逐段获取确认；确认后把完整设计写入
`docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`，提交设计文档，自审，再请用户审阅文件；用户再次批准后才进入 planning。这意味着“确认对象”已经是落盘文件，而不是随后重新生成的文本。

来源：

- [brainstorming：流程与逐段批准](https://github.com/obra/superpowers/blob/3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9/skills/brainstorming/SKILL.md#L17-L26)
- [brainstorming：写入、commit、自审和用户审阅](https://github.com/obra/superpowers/blob/3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9/skills/brainstorming/SKILL.md#L89-L113)

大需求也不会被压成一份巨大 spec。多个独立子系统必须拆成多个 sub-project，各自走 spec → plan → implementation：

- [brainstorming：拆分多个独立子系统](https://github.com/obra/superpowers/blob/3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9/skills/brainstorming/SKILL.md#L55-L62)

计划保存为 `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md`。若设计仍包含多个独立子系统，则继续拆成多个 plan；每个任务包含精确文件、接口、测试、预期输出和 commit 步骤：

- [writing-plans：计划路径与继续拆分](https://github.com/obra/superpowers/blob/3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9/skills/writing-plans/SKILL.md#L13-L20)
- [writing-plans：任务结构和执行细节](https://github.com/obra/superpowers/blob/3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9/skills/writing-plans/SKILL.md#L44-L112)

需要区分：当前 `writing-plans` 明确规定了 plan 的仓库路径，但不像 design doc 那样明确要求“生成后立即 commit plan”。它仍把 plan 当作 durable artifact，而不是 tool payload。

### 1.2 执行 scratch 与正式 artifact 分离

每个 plan 有独立的 `<repo>/.superpowers/sdd/<plan-basename>/` 工作区，保存：

- `progress.md` 进度 ledger；
- 单任务 brief；
- implementer report；
- review diff package。

这个工作区生成自己的 `.gitignore`，内容为 `*`，因此不进入 `git status` 或 commit：

- [subagent-driven-development：workspace、ledger 与恢复](https://github.com/obra/superpowers/blob/3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9/skills/subagent-driven-development/SKILL.md#L104-L126)
- [sdd-workspace：创建 ignored scratch](https://github.com/obra/superpowers/blob/3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9/skills/subagent-driven-development/scripts/sdd-workspace#L1-L17)
- [sdd-workspace：`.gitignore` 行为](https://github.com/obra/superpowers/blob/3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9/skills/subagent-driven-development/scripts/sdd-workspace#L29-L38)

`progress.md` 第一行绑定 plan path，`Task N: complete` 决定恢复点。上下文压缩后，以 ledger 和 git log 为准；若 scratch 被 `git clean -fdx` 删除，则从 git history 重建。

任务 brief 只从 plan 抽取当前任务，report 写入文件后只返回短状态，review package 把 commits、stat 和完整 diff 固化到文件，避免在 agent 间反复复制整份计划或大段 diff：

- [subagent-driven-development：brief、report 与 review package](https://github.com/obra/superpowers/blob/3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9/skills/subagent-driven-development/SKILL.md#L177-L206)
- [task-brief 脚本](https://github.com/obra/superpowers/blob/3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9/skills/subagent-driven-development/scripts/task-brief)
- [review-package 脚本](https://github.com/obra/superpowers/blob/3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9/skills/subagent-driven-development/scripts/review-package)

最终 review 通过后删除该 plan 的 scratch，Git history 成为最终记录：

- [subagent-driven-development：清理 scratch](https://github.com/obra/superpowers/blob/3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9/skills/subagent-driven-development/SKILL.md#L369-L376)

### 1.3 没有成熟的全局 wiki/index 状态层

Superpowers 核心目前没有正式的跨计划 roadmap/wiki 索引。官方仓库的 open proposal
[#1192](https://github.com/obra/superpowers/issues/1192)
正是因为 specs/plans 虽然 durable，但缺少“哪个 active、blocked、next”的 connective tissue，才提议增加 `docs/superpowers/roadmap.md`。

这说明它已经解决了单个 spec/plan 的持久化和执行恢复，但跨 feature 的导航仍是待补能力。

## 2. mattpocock/skills

核对版本：官方仓库 `mattpocock/skills`，commit
[`ed37663cc5fbef691ddfecd080dff42f7e7e350d`](https://github.com/mattpocock/skills/tree/ed37663cc5fbef691ddfecd080dff42f7e7e350d)。

### 2.1 Spec 发布到 tracker，而不是停留在聊天或一次性 payload

`to-spec` 从当前对话和代码库理解生成 spec，并发布到项目配置的 issue tracker，标记为 `ready-for-agent`：

- [to-spec：生成并发布 spec](https://github.com/mattpocock/skills/blob/ed37663cc5fbef691ddfecd080dff42f7e7e350d/skills/engineering/to-spec/SKILL.md#L7-L19)

它的 spec 是面向用户问题、user stories、implementation decisions、testing decisions 和 out-of-scope 的持久说明；特意避免易腐化的具体文件路径和代码片段：

- [to-spec：spec 模板及耐久性边界](https://github.com/mattpocock/skills/blob/ed37663cc5fbef691ddfecd080dff42f7e7e350d/skills/engineering/to-spec/SKILL.md#L21-L69)

当 tracker 选择 local Markdown 时：

- 每个 feature 一个 `.scratch/<feature-slug>/`；
- spec 为 `.scratch/<feature-slug>/spec.md`；
- implementation ticket 为 `.scratch/<feature-slug>/issues/<NN>-<slug>.md`；
- status 写在 ticket 文件顶部；
- 评论和历史追加在文件末尾。

来源：

- [local Markdown tracker：目录和文件约定](https://github.com/mattpocock/skills/blob/ed37663cc5fbef691ddfecd080dff42f7e7e350d/skills/engineering/setup-matt-pocock-skills/issue-tracker-local.md#L1-L18)

这里的 `.scratch/` 是“repo-local tracker”命名。官方文件没有规定它必须被 `.gitignore`，也没有保证它一定 commit；是否纳入 Git 需要项目自己明确。不能仅因目录名叫 scratch 就把它等同于 Superpowers 的 ignored scratch。

### 2.2 大 spec 被拆成可独立恢复的 tickets

`to-tickets` 要求每个 ticket 是一个端到端、可独立演示或验证、能在单个新 context window 完成的 tracer-bullet slice。发布前先让用户确认粒度和 blocking edges：

- [to-tickets：vertical slice 与用户确认](https://github.com/mattpocock/skills/blob/ed37663cc5fbef691ddfecd080dff42f7e7e350d/skills/engineering/to-tickets/SKILL.md#L19-L56)

local tracker 下每个 ticket 一个文件，按依赖顺序编号；真实 tracker 下使用原生 issue、blocking/sub-issue 关系。可以执行的 frontier 是 blockers 已全部完成的 tickets：

- [to-tickets：每 ticket 一文件、blocking 与 frontier](https://github.com/mattpocock/skills/blob/ed37663cc5fbef691ddfecd080dff42f7e7e350d/skills/engineering/to-tickets/SKILL.md#L58-L65)

因此，它处理“大需求”的主要方式不是放宽单个 spec payload，而是：

1. 先保存 spec；
2. 再拆为多个有依赖关系的、可在新上下文独立执行的工作单元。

### 2.3 Wayfinder 是“大型、尚未完全明确工作”的中间状态模型

`wayfinder` 明确区分 map 与 ticket：

- map 是 canonical artifact，但只是低分辨率 index；
- 每个决定只存在于一个 child ticket；
- map 只保存决定的一行 gist 和链接，不复制细节；
- 未能准确表达的问题留在 `Not yet specified`（fog），等前置决定完成后再“毕业”为 ticket。

来源：

- [wayfinder：canonical map 是 index，不是 store](https://github.com/mattpocock/skills/blob/ed37663cc5fbef691ddfecd080dff42f7e7e350d/skills/engineering/wayfinder/SKILL.md#L21-L29)
- [wayfinder：fog 和渐进细化](https://github.com/mattpocock/skills/blob/ed37663cc5fbef691ddfecd080dff42f7e7e350d/skills/engineering/wayfinder/SKILL.md#L82-L101)

恢复与并发依赖显式状态：

- 开始前 claim ticket；
- blocking 关系计算 frontier；
- resolution 写入 comment/answer 后关闭 ticket；
- map 的 `Decisions so far` 只追加 context pointer；
- 新暴露的问题创建新 ticket，已变清晰的 fog 从 map 移除。

来源：

- [wayfinder：claim、blocking 和 frontier](https://github.com/mattpocock/skills/blob/ed37663cc5fbef691ddfecd080dff42f7e7e350d/skills/engineering/wayfinder/SKILL.md#L57-L71)
- [wayfinder：记录 resolution 与推进 frontier](https://github.com/mattpocock/skills/blob/ed37663cc5fbef691ddfecd080dff42f7e7e350d/skills/engineering/wayfinder/SKILL.md#L121-L126)
- [local tracker：map、ticket、claim 和 resolve 的文件实现](https://github.com/mattpocock/skills/blob/ed37663cc5fbef691ddfecd080dff42f7e7e350d/skills/engineering/setup-matt-pocock-skills/issue-tracker-local.md#L21-L30)

### 2.4 临时 handoff 明确不进 workspace

用于跨会话的 `handoff` 文档保存在 OS 临时目录，不放进当前 workspace；它不复制已有 spec、plan、ADR、issue、commit 或 diff，只引用路径/URL：

- [handoff：OS temp 与只引用既有 artifact](https://github.com/mattpocock/skills/blob/ed37663cc5fbef691ddfecd080dff42f7e7e350d/skills/productivity/handoff/SKILL.md#L7-L16)

这形成了一个清楚的边界：可替代的“对话接力摘要”是临时文件；真正的决定与工作状态留在 spec、ticket、ADR 和 Git 中。

## 3. Open Knowledge Format 与用户给出的文章

用户给出的文章：

- [Google 发布 OKF：把 LLM Wiki 变成开放标准](https://blog.frognew.com/2026/06/open-knowledge-format.html)

文章对 OKF 的用途判断基本准确：它是“知识格式”，不是新的知识服务；通过 Markdown、YAML frontmatter、目录和链接让不同 producer/consumer 交换知识。其直接上游是：

- [Google Cloud 官方发布文章](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing/)
- [GoogleCloudPlatform/knowledge-catalog 官方仓库](https://github.com/GoogleCloudPlatform/knowledge-catalog)
- [OKF v0.2 正式规范](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/3fcbb9f828c2f23d109c855ee403c3a4c81f3a96/okf/SPEC.md)
- [Karpathy 的 LLM Wiki 原始 gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)

需要注意版本差异：该文章介绍的是首发时的 v0.1，并使用 `timestamp` 和 body `# Citations`。当前官方规范已是 v0.2；`timestamp` 被 `generated.at` 取代，body citations list 被 frontmatter `sources` 加稳定 source ID 取代：

- [OKF v0.2：从 v0.1 的变更](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/3fcbb9f828c2f23d109c855ee403c3a4c81f3a96/okf/SPEC.md#L793-L824)

### 3.1 OKF 擅长什么

OKF bundle 是 Markdown 目录树，可作为 Git repo、压缩包或大仓库子目录分发；Git 是推荐方式，因为自带历史、归属和 diff：

- [OKF：bundle 结构和分发方式](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/3fcbb9f828c2f23d109c855ee403c3a4c81f3a96/okf/SPEC.md#L109-L134)

每个 concept 以文件路径作为 ID，正文是结构化 Markdown；frontmatter 只有 `type` 始终必填，允许 producer 扩展字段：

- [OKF：concept frontmatter 和扩展规则](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/3fcbb9f828c2f23d109c855ee403c3a4c81f3a96/okf/SPEC.md#L153-L209)

它很适合大型需求的知识层：

- `sources` 保存外部或 bundle 内来源，并通过稳定 `id` 做 claim-level attribution；
- 普通 Markdown 链接形成关系图；
- `references/` 可镜像外部材料；
- `index.md` 支持 progressive disclosure，可自动生成；
- `log.md` 保存目录范围的日期更新历史；
- `generated`、`verified`、`status`、`stale_after` 表达来源、人工确认和生命周期。

来源：

- [OKF：sources、稳定 ID 与逐 claim 引用](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/3fcbb9f828c2f23d109c855ee403c3a4c81f3a96/okf/SPEC.md#L277-L363)
- [OKF：generated、verified 与 lifecycle](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/3fcbb9f828c2f23d109c855ee403c3a4c81f3a96/okf/SPEC.md#L363-L433)
- [OKF：链接和 references 约定](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/3fcbb9f828c2f23d109c855ee403c3a4c81f3a96/okf/SPEC.md#L434-L486)
- [OKF：index.md 渐进加载](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/3fcbb9f828c2f23d109c855ee403c3a4c81f3a96/okf/SPEC.md#L502-L529)
- [OKF：log.md 更新历史](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/3fcbb9f828c2f23d109c855ee403c3a4c81f3a96/okf/SPEC.md#L530-L550)

### 3.2 OKF 不能替代什么

官方明确把以下内容列为 non-goals：

- 不规定固定领域 taxonomy；
- 不规定 storage、serving 或 query infrastructure；
- 不替代 OpenAPI、Protobuf 等领域 schema；
- 不规定执行器的 packaging/invocation runtime。

来源：

- [OKF：goals 和 non-goals](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/3fcbb9f828c2f23d109c855ee403c3a4c81f3a96/okf/SPEC.md#L21-L69)

因此，OKF 即使有 `draft | stable | deprecated`，也不是完整审批状态机。它没有定义：

- candidate 与正式版本的原子 promotion；
- approval 绑定哪个精确内容；
- hash/evidence binding；
- 谁可以批准；
- 前置 gate；
- 并发发布、幂等性和失败恢复。

特别是 OKF 规定 `status` 缺失时默认为 `stable`，而且大多数 trust/lifecycle 字段是 optional；这适合宽松知识交换，不适合作为严格 release gate 的唯一事实源。

## 4. 其他主流 SDD 方案

### 4.1 GitHub Spec Kit：显式选择持久化模型

GitHub Spec Kit 的标准链路是 Spec → Plan → Tasks → Implement，核心 artifact 是
`spec.md`、`plan.md` 和 `tasks.md`。更值得借鉴的是：它没有假装所有团队都只有一种
“正确”的 spec 生命周期，而是要求团队显式选择三种 persistence model 之一：

- **Flow-back**：spec、plan、tasks 和代码都可反向影响彼此，最后人工 reconcile；速度快，但有 silent divergence 风险；
- **Flow-forward**：完成后的 feature 目录视为 immutable；需求变化时创建新 feature 目录，旧目录保留用于 audit；
- **Living spec**：`spec.md` 是 contract，plan/tasks 是可再生的 derived artifacts。

来源：

- [Spec Kit 官方流程](https://github.github.io/spec-kit/)
- [Spec Kit：Spec Persistence Models](https://github.github.io/spec-kit/concepts/spec-persistence.html)
- [Spec Kit：大功能先拆为多个独立 spec](https://github.github.io/spec-kit/concepts/spec-of-specs.html)

对本 SDLC，最适合的是 **Flow-forward candidate/history + Living published spec** 的组合：

- 候选和审批历史不可变，便于 hash、审计和失败恢复；
- 当前正式 requirements 是 living baseline；
- plan、rendered Markdown、index 可以从结构化 baseline 重建。

Spec Kit 同样建议超大功能先做 “spec of specs”，再让每个独立 spec 各走一遍 specify/plan/tasks/implement。这进一步反证“一个大 feature contract 装下所有子系统”并不是主流处理方式。

### 4.2 Fission-AI/OpenSpec：change delta → apply → archive

OpenSpec 把当前事实与待议变更分开：

```text
openspec/
├── specs/                         # 当前 source-of-truth specs
└── changes/<change-name>/         # 进行中的 change
    ├── proposal.md
    ├── specs/                     # spec deltas
    ├── design.md
    └── tasks.md
```

人和 AI 先 review change folder；实现期间在 `tasks.md` 更新 checklist；完成后
`archive` 把 change 移到带日期的 archive，并把 delta 合并回 current specs。

来源：

- [OpenSpec 官方 README：propose/apply/archive 示例](https://github.com/Fission-AI/OpenSpec#see-it-in-action)
- [OpenSpec 官方 README：change artifacts 与归档结果](https://github.com/Fission-AI/OpenSpec#what-do-the-specs-actually-look-like)
- [OpenSpec 官方仓库中的 live specs 和 in-flight changes](https://github.com/Fission-AI/OpenSpec/tree/main/openspec)

这个模式与本仓库最接近，也最值得直接参考：

- `changes/<id>/` 是完整、可审阅的候选，不是确认后才重建；
- `specs/` 是当前正式状态；
- archive 同时保存 change 历史并更新 living specs；
- `openspec list/show/validate` 从文件系统恢复 active changes，而不是依赖聊天历史。

它仍比本 SDLC 宽松：OpenSpec 官方强调 artifact 可随时迭代、没有 rigid phase gates。因此可借其目录和 delta/archive 模型，但 approval、hash binding、幂等发布和 release gate 仍需本仓库自己的确定性状态机。

### 4.3 BMAD-METHOD：规划 artifact 与实施状态分层

BMAD 安装后把 workflow/agent 配置放在 `_bmad/`，把项目产出放在
`_bmad-output/`。规划阶段生成 PRD、architecture、epics/stories；实施阶段另用
`sprint-status.yaml` 跟踪所有 epics 和 stories：

```text
_bmad-output/
├── planning-artifacts/
│   ├── PRD.md
│   ├── architecture.md
│   └── epics/
├── implementation-artifacts/
│   └── sprint-status.yaml
└── project-context.md
```

来源：

- [BMAD Getting Started：artifact 根目录和 fresh-chat 恢复方式](https://github.com/bmad-code-org/BMAD-METHOD/blob/main/docs/tutorials/getting-started.md#installation)
- [BMAD：PRD、architecture 与 implementation-readiness](https://github.com/bmad-code-org/BMAD-METHOD/blob/main/docs/tutorials/getting-started.md#step-1-create-your-plan)
- [BMAD：sprint-status.yaml 与最终目录结构](https://github.com/bmad-code-org/BMAD-METHOD/blob/main/docs/tutorials/getting-started.md#step-2-build-your-project)

BMAD 明确要求每个 workflow 使用 fresh chat；恢复依据是落盘 artifact，`bmad-help` 检查项目中已经完成了什么并推荐下一步。中途变更通过 `bmad-correct-course`，而不是默默改写旧上下文。

它的启示不是复制多 agent 角色，而是保持：

- planning artifacts 与 implementation status 分层；
- implementation-readiness 是跨文档一致性检查；
- 新会话从项目文件恢复，不把 conversation 当数据库。

### 4.4 GSD：可重建的 STATE，而不是唯一可信的 STATE

GSD 把长期规划状态放进 repo-local `.planning/`：`PROJECT.md`、`REQUIREMENTS.md`、
`ROADMAP.md`、phase `CONTEXT.md`、plans、summaries 和 `STATE.md`。执行完所有 phase 后，
先 audit requirements coverage，再 complete milestone，归档并打 tag：

- [GSD User Guide：phase loop、audit 与 archive/tag](https://github.com/gsd-build/get-shit-done/blob/main/docs/USER-GUIDE.md#workflow)
- [GSD User Guide：断点恢复](https://github.com/gsd-build/get-shit-done/blob/main/docs/USER-GUIDE.md#resuming-after-a-break)

GSD 最有价值的设计是：`STATE.md` 不是不可质疑的单点真相。`state validate` 将其与
phase directories、plan files 和 summaries 对照；`state sync --verify` 先预览；
`state sync` 可从磁盘 artifact 重建状态：

- [GSD：STATE.md drift 检测与重建](https://github.com/gsd-build/get-shit-done/blob/main/docs/USER-GUIDE.md#statemd-out-of-sync)
- [GSD Features：STATE consistency gates](https://github.com/gsd-build/get-shit-done/blob/main/docs/FEATURES.md#69-statemd-consistency-gates)

对于跨会话但尚不属于 phase 的知识，GSD 使用 `.planning/threads/{slug}.md`，包含
Goal、Context、References 和 Next Steps；成熟后可以 promotion 为 phase 或 backlog。
并行 workstream 各自持有隔离的 `.planning/` subtree，防止多个 session 相互覆盖状态：

- [GSD：persistent threads](https://github.com/gsd-build/get-shit-done/blob/main/docs/USER-GUIDE.md#persistent-context-threads)
- [GSD：isolated workstreams](https://github.com/gsd-build/get-shit-done/blob/main/docs/USER-GUIDE.md#workstreams)

本 SDLC 应借鉴其“derived state 可验证、可重建”原则：即便保留一个 run-state/index 文件，它也应能从 candidate、approval evidence、published baseline、task/test artifacts 重新计算，不能成为无法校验的第二事实源。

### 4.5 Kiro：三文件 spec 与任务依赖图

Kiro 每个 spec 固定生成：

- `requirements.md`（或 bugfix 的 `bugfix.md`）；
- `design.md`；
- `tasks.md`。

`tasks.md` 同时承载离散任务和实时状态；执行器从任务依赖构图，按 wave 并行执行可独立任务。复杂 feature 默认走 requirements → design → tasks；Quick Spec 才允许一次生成且不经过 approval gates。

来源：

- [Kiro 官方 Specs：三文件结构与三阶段流程](https://kiro.dev/docs/specs/#core-structure)
- [Kiro 官方 Specs：task 状态和 dependency waves](https://kiro.dev/docs/specs/#task-execution)
- [Kiro 官方 Specs：复杂工作与 Quick Spec 的边界](https://kiro.dev/docs/specs/#types-of-specs)

Kiro 进一步支持“长契约必须分阶段落盘”的判断，但它与 IDE 产品绑定较深，不适合作为本仓库的存储协议。可借三文件边界和 dependency graph，不应照搬 IDE state。

### 4.6 横向比较

| 方案 | 正式基线 | 进行中状态 | 恢复机制 | 完成后 |
|---|---|---|---|---|
| Superpowers | Git 中 design/spec/plan | ignored `.superpowers/sdd/<plan>/` ledger | ledger + git log | 删除 scratch，Git 留痕 |
| mattpocock/skills | tracker 中 spec/map/tickets | ticket status、blocking、claim、fog | 扫 tracker 取 frontier | resolution + closed ticket + index pointer |
| Spec Kit | `spec.md`，策略由团队选择 | `plan.md`、`tasks.md` | feature 目录 | flow-back / flow-forward / living spec |
| OpenSpec | `openspec/specs/` | `changes/<id>/` proposal/delta/design/tasks | list/show/validate active changes | archive change，delta 合并 current specs |
| BMAD | planning artifacts | `sprint-status.yaml`、story files | fresh chat 读取 artifacts，help 检测完成度 | retrospective/correct-course |
| GSD | PROJECT/REQUIREMENTS/ROADMAP | phase plans、summaries、`STATE.md` | validate/sync 从文件系统重建 | audit、archive、tag |
| Kiro | requirements/design/tasks | task status + dependency graph | IDE 读取 spec files | task 完成；长期归档策略不突出 |
| OKF | stable knowledge concepts | draft/status/log | index + links + Git | stable/deprecated；不定义发布事务 |

社区的共同结论不是“所有东西写 Markdown”这么简单，而是：

1. **先落盘，再批准或执行**；
2. **大需求拆分，状态和依赖显式化**；
3. **正式事实、change/candidate、execution scratch 分层**；
4. **恢复从 artifacts 和 Git 进行，不依赖聊天**；
5. **当前状态最好可从更细粒度 evidence 重建**；
6. **索引只保存摘要和 pointer，不重复正文**。

## 5. 对本仓库 SDLC 的建议

### 5.1 不要在 approve 时重建候选

推荐的最小可靠协议：

```text
ingest sources
  → save candidate contract
  → validate candidate deterministically
  → render candidate for review
  → user approves candidate_id + content_hash
  → atomically promote that exact candidate
  → generate/update official requirements and indexes
```

`approve spec` 应只提交类似：

```json
{
  "candidate_id": "speccand-...",
  "content_hash": "sha256:...",
  "decision": "approve"
}
```

而不是再次携带完整 contract。正式 requirements 必须来自已校验 candidate 的确定性投影，而不是新的模型生成。

### 5.2 三类文件要明确分层

| 层 | 内容 | 建议生命周期 | 是否作为审批对象 |
|---|---|---|---|
| Source/knowledge | 原始 PRD、原型说明、API 文档、领域概念、来源 anchor、索引 | 长期保存；可采用 OKF v0.2 风格 | 否；只作为来源 |
| Candidate | 完整结构化 contract、渲染预览、validation report、hash | 审批前持久化；拒绝后保留或归档 | 是 |
| Published baseline | 正式 requirements/spec 与发布证据 | Git/版本库中的 durable baseline | approve 后的结果 |
| Execution scratch | progress ledger、task brief、agent report、临时 diff package | 可恢复；完成后清理或归档 | 否 |

关键不是目录名，而是每层的 contract：

- 谁能写；
- 是否可变；
- 是否进入 Git；
- 何时清理；
- 如何恢复；
- 哪个 ID/hash 被批准。

### 5.3 大需求采用“小 contract + 知识索引”，不要采用“大 contract”

对于“首页 + History + 设备 API 前置 + 系统/网络/视频/音频/其他设置”，建议：

1. 原始大需求、原型和亿联 API 文档进入 source/knowledge bundle；
2. bundle 用 `index.md` 做目录，每个 concept 小文件保存，并带 `sources`、`generated`、`verified`、`status`；
3. 拆成多个可独立验收的 Feature Contract；
4. 每个 contract 只保存稳定 `source_id + anchor/path`，不复制所有来源正文；
5. 再把 feature 拆成单 context 可完成、带 blocking edges 的 implementation tickets；
6. 生成一个只包含摘要和链接的 feature/roadmap index，不复制 contract 内容。

这同时吸收了：

- Superpowers 的“独立子系统各走自己的 spec → plan → implementation”；
- mattpocock/skills 的“map 是 index，不是 store”和 frontier；
- OKF 的 concept、source、link 与 progressive disclosure。

### 5.4 Schema 仍然必要，但位置要正确

Schema 应校验：

- candidate contract 的结构与语义；
- source reference 的合法性；
- ID 唯一性和依赖闭环；
- approval/promotion 的状态转换；
- requirements 的确定性投影。

Schema 不应承担：

- 保存整个对话；
- 承载所有原始需求正文；
- 充当跨 feature 导航；
- 在一次工具调用中传输超长内容；
- 代替 candidate store 或 Git。

## 6. 最终判断

本仓库应继续“按 spec 实现”，但这里的 spec 应当是**已经落盘、已经校验、由 ID/hash 精确寻址、经用户批准后原子发布的正式契约**。

同时可以引入 OKF 式 wiki + index，但它应该是**知识与来源层**，不是发布状态机：

```text
OKF-like knowledge bundle
        │ source_id + anchor
        ▼
candidate contracts ── validate ── approve(id + hash)
        │
        ▼
published requirements/specs
        │
        ▼
dependency tickets + execution ledger
```

如果只选 OKF，会缺少严格审批和发布语义；如果只选一份巨大 schema contract，会继续遭遇长度、重组、引用和可导航性问题。两层组合才符合社区已经验证的 artifact boundary。
