# 轻量、可恢复、可追溯的 Agentic SDLC 模式研究

日期：2026-07-27

## 1. 研究目标

当前场景不是开放式软件工厂，而是一个边界很清楚的交付任务：

> 给定已登记脚手架和一份需求，在约定路径、规则和 lifecycle 内完成一个 Feature Slice，
> 以可执行测试证明交付目标，并保留足以中断恢复、审计和定位失败的证据。

因此评价一个外部做法时，不看它有多少 agents、skills 或文档，而看它是否能同时满足：

1. 单一功能通常能在可接受时间内完成；
2. 模型上下文只包含当前决策所需信息；
3. 确定性错误不触发完整 Agent 重跑；
4. 完成声明必须绑定新鲜的机器证据；
5. 中断后从已完成边界继续，而不是重新讨论和重新构建；
6. 产物能从需求追到设计、代码、测试和版本，但不要求模型重复抄写机器已知事实。

本文只采用项目自身仓库或产品官方文档作为事实来源。ECC、Superpowers、Matt Pocock
skills 和 Karpathy-inspired skills 都是社区项目；其中只有 `karpathy/autoresearch` 是
Andrej Karpathy 本人的项目，Claude Code 机制以 Anthropic 官方文档为准。

## 2. 外部项目的真实做法及取舍

### 2.1 obra/superpowers

Superpowers 建立了一条严格的 brainstorm → design/spec → plan → implementation →
review → verification 流程。它强调：

- 先读项目上下文，一次问一个澄清问题，设计获批后才能实现；
- 任务足够独立时，每个任务使用新鲜、隔离上下文的 implementer；
- 每个任务经过 spec compliance 和 code quality review，最后再做全分支 review；
- 完成前必须重新运行能证明声明的命令，不能相信 Agent 的成功报告；
- TDD 使用严格 red → green → refactor 循环。

来源：

- [Superpowers 仓库](https://github.com/obra/superpowers)
- [brainstorming skill](https://github.com/obra/superpowers/blob/main/skills/brainstorming/SKILL.md)
- [subagent-driven development](https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md)
- [verification before completion](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md)
- [test-driven development](https://github.com/obra/superpowers/blob/main/skills/test-driven-development/SKILL.md)

适合采用：

- `evidence before claims`；
- 先探索项目事实，再只问用户真正的产品决策；
- coder 使用隔离且精确构造的 context pack；
- 需求、实现和验证之间存在明确完成条件；
- 针对高风险或独立任务使用额外 review，而不是把 review 当默认固定成本。

不宜默认照搬：

- 每个小任务一个新 Agent、每任务两轮 review、最后再全量 review；
- 所有变更都执行完整版 brainstorming、plan 和强制 TDD；
- 对一个紧耦合的 Feature Slice 拆出大量任务并分别冷启动上下文。

原因是当前流水线的主要瓶颈正是 Agent 冷启动、重复读取和失败后重派。Superpowers 自己也把
subagent-driven development 的适用条件限定为“已有计划且任务大多独立”。一个 Home +
设备信息的垂直切片通常是紧耦合改动，更适合一个 coder 在同一上下文内完成。

### 2.2 Everything Claude Code（ECC）

当前 canonical 仓库是 [affaan-m/ECC](https://github.com/affaan-m/ECC)。ECC 是社区项目，
不是 Anthropic 官方项目。

ECC 最值得借鉴的不是庞大的组件目录，而是它提供的选择机制：

- 有 `minimal` / no-hooks 路径；
- hooks runtime 可按需安装；
- rules 按 common + 实际语言/profile 选择；
- Skills 作为按需工作流入口；
- host adapter 复用共同脚本，不为每个宿主复制业务逻辑；
- MCP、hooks 和额外能力 opt-in；
- 在研究→实现、里程碑或方案切换边界 compact，而不是在正在实现时任意压缩。

来源：

- [ECC README](https://github.com/affaan-m/ECC/blob/main/README.md)
- [ECC low-context / no-hooks path](https://github.com/affaan-m/ECC/blob/main/README.md#low-context--no-hooks-path)
- [ECC key concepts](https://github.com/affaan-m/ECC/blob/main/README.md#key-concepts)
- [ECC token optimization](https://github.com/affaan-m/ECC/blob/main/README.md#token-optimization)

适合采用：

- thin OpenCode adapter + 单一 Python core；
- profile 只激活 Electron + TypeScript + React 所需内容；
- Skills 按阶段加载，规则正文不常驻；
- hook 只做低成本、确定性的边界动作；
- 安装时禁止同一能力的 plugin/manual 双重来源。

不宜采用：

- 把 ECC 的 agents、skills、continuous learning、memory、security workflow 全部带入关键路径；
- 每轮启动大量 MCP 或自动注入所有规则；
- 让“学习/经验沉淀”改变当前 Run 的确定性交付语义。

ECC 应被视为工具箱和分发模式，而不是应当逐项执行的 SDLC 状态机。

### 2.3 Anthropic Claude Code 官方机制

Claude Code 官方把扩展机制按上下文成本分开：

- `CLAUDE.md` 每轮加载，适合少量项目不变量；
- Skills 的描述用于发现，正文需要时再加载；
- Hooks 在 Agent loop 外运行，适合确定性阻断、审计和边界验证；
- Subagents 拥有独立上下文，只向主会话返回结果；
- Agent loop 是 gather context → take action → verify → 根据新证据继续。

来源：

- [Claude Code features overview](https://code.claude.com/docs/en/features-overview)
- [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works)
- [Skills](https://code.claude.com/docs/en/slash-commands)
- [Subagents](https://code.claude.com/docs/en/sub-agents)
- [Hooks reference](https://code.claude.com/docs/en/hooks)
- [Hooks guide](https://code.claude.com/docs/en/hooks-guide)
- [Agent SDK agent loop](https://code.claude.com/docs/en/agent-sdk/agent-loop)

官方 SDK 还提供 `maxTurns`、`maxBudgetUsd` 和 effort 等边界。这说明“持续工作”不等于
“无界重试”；loop 应有预算和终止条件。

Claude Code 的 checkpoint 与 session resume 也不能替代流水线 Journal：

- checkpoint 保存用户 prompt 前由直接编辑工具产生的文件快照；
- Bash、外部进程、并发修改和多数 subagent 修改不都受 checkpoint 保护；
- `--continue` / `--resume` 恢复的是 host 会话；
- transcript JSONL 是内部格式，不应作为稳定业务 API。

来源：

- [Checkpointing](https://code.claude.com/docs/en/checkpointing)
- [Sessions](https://code.claude.com/docs/en/sessions)

适合采用：

- host session id 只作为“尽量恢复同一模型上下文”的辅助；
- Run Journal、Git fingerprint 和 evidence refs 才是权威业务恢复点；
- command hook 处理 schema、path、policy、lifecycle 等可由代码判断的问题；
- subagent 只用于高噪音探索、真正独立的任务或高风险 review。

不宜采用：

- 用 prompt hook 或 reviewer Agent 判断本可由代码精确判断的规则；
- 每次 Edit 都运行全量 build/lint；
- 把 host checkpoint 当事务存储；
- 将 transcript/token 内部状态序列化成自建恢复协议。

### 2.4 mattpocock/skills

Matt Pocock 明确反对让一个流程框架“拥有整个过程”，其 skills 目标是小、可组合、可修改。
这与当前需求高度一致。

来源：

- [mattpocock/skills README](https://github.com/mattpocock/skills)
- [grilling](https://github.com/mattpocock/skills/blob/main/skills/productivity/grilling/SKILL.md)
- [codebase-design](https://github.com/mattpocock/skills/blob/main/skills/engineering/codebase-design/SKILL.md)
- [diagnosing-bugs](https://github.com/mattpocock/skills/blob/main/skills/engineering/diagnosing-bugs/SKILL.md)
- [TDD](https://github.com/mattpocock/skills/blob/main/skills/engineering/tdd/SKILL.md)

其中四个模式值得保留：

1. grilling：环境可查的事实直接查，只把决策交给用户；一次问一个问题，并给推荐答案。
2. deep module：大量确定性复杂度藏在小接口后面，caller 和测试只跨同一个 seam。
3. diagnosing：先构建紧的 pass/fail feedback loop；旧版/新版 differential loop 是优先手段。
4. TDD：测试行为和公共 seam，而不是实现细节。

需要调整的是 grilling 的触发范围。“relentlessly”适合开放式产品构思，不适合已有脚手架上的
小功能。这里应变成 bounded grilling：

- 先自动读取脚手架、原型、已有 API 和 profile；
- 最多询问 3 个会改变产品行为、范围或验收的 blocking decision；
- 技术实现选择进入 design defaults/ADR，不逐题询问；
- 用户已有明确答案时不重复确认。

### 2.5 Karpathy-inspired skills 与 Karpathy 本人的 autoresearch

用户所称 `andrej-karpathy-skills` 不是 Andrej Karpathy 官方仓库。旧
`forrestchang/andrej-karpathy-skills` 当前重定向到
[multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills)。
它把公开观点整理成四条短规则：

- Think Before Coding；
- Simplicity First；
- Surgical Changes；
- Goal-Driven Execution。

这些适合直接压缩成 coder 的短常驻规则，尤其是“每一条变更都能追到用户需求”和“给出可验证
目标，而不是笼统动作”。但它不是状态机、Journal 或恢复方案，不应赋予更多架构职责。

Andrej Karpathy 本人的 [karpathy/autoresearch](https://github.com/karpathy/autoresearch)
对 loop 更有参考价值：

- 固定且很小的可修改范围；
- 固定评估 harness，Agent 不允许修改；
- 先测 baseline；
- 每次实验有固定 5 分钟预算；
- 使用单一客观指标判断 keep/discard/crash；
- 日志写文件，不把完整输出灌入上下文；
- 每次实验记录 commit、metric、status 和短描述。

来源：

- [autoresearch README](https://github.com/karpathy/autoresearch/blob/master/README.md)
- [autoresearch program.md](https://github.com/karpathy/autoresearch/blob/master/program.md)

这是当前流水线最应该借鉴的 loop 形状：

> 固定作用域 + 不可修改的验证器 + 基线 + 有预算的尝试 + 简短结构化结果。

不应照搬 `LOOP FOREVER`。软件交付存在环境故障、歧义和人工决策，必须设置 retry/time budget
和 BLOCKED 终态。

### 2.6 Ralph loop

Anthropic 的 Claude Code 仓库包含
[Ralph Wiggum plugin](https://github.com/anthropics/claude-code/blob/main/plugins/ralph-wiggum/README.md)。
它通过 Stop hook 阻止退出，把同一个 prompt 再次送回当前会话；文件和 Git 历史保存上一轮工作。
官方 README 同时强调：

- 适合成功标准清楚、可自动验证的任务；
- 应设置 `max-iterations`；
- 不适合需要人类判断、设计不清楚或生产故障定位的任务。

因此当前项目只能采用“Ralph 的证据驱动持续性”，不能采用“同 prompt 无差别重放”。
如果失败证据没有变化，重复同一 prompt 只会增加成本。每一轮必须由新的 failure delta 驱动，
并受同错误指纹和总预算限制。

## 3. 对当前项目的推荐架构

### 3.1 五阶段，而不是文档工厂

```text
Intake → Spec-lite → Implement → Verify → Finalize
```

1. Intake：登记 source，探测脚手架、baseline、profile 和已有能力。
2. Spec-lite：形成一个 Feature Contract，最多询问 3 个 blocking decision。
3. Implement：一个 coder 在一个连续上下文内实现一个 Feature Slice。
4. Verify：Core 运行唯一一次权威交付验证，失败时仅返回 failure delta。
5. Finalize：用户确认后固化版本和 manifest。

`requirements.md`、`design.md`、`test-plan.md` 是同一个 Feature Contract 的三个视图，
不是三个需要独立 Agent 反复审查的项目。

### 3.2 Feature Contract 的最小机器模型

```text
Feature
  id, title, goal, actor
  source_refs[]              # source_id + anchor，不复制原文
  scope[], non_goals[]
  domain_data[]              # 业务字段/概念，不是 TS 实现细节
  main_flow[]                # 3–7 步
  alternate_flows[]          # 只保留可验收异常
  acceptance_criteria[]
    ac_id, given, when, then, verifier

FeatureDesign
  feature_id
  modules[]                  # 责任与 seam
  interfaces[]               # 输入/输出/错误/性能约束
  data_contracts[]           # 字段、类型、必填、来源
  touched_extension_points[]
  decisions[]                # 只记录重要且难逆转决策

VerificationPlan
  ac_id
  test_key
  level                      # unit/integration/e2e
  expected
```

lint、static analysis、dependency/security checks 是 profile 注入的 Engineering Controls，
不属于用户 Feature 的业务 test plan。

正式 Markdown 继续由 Core 确定性渲染，但只呈现最终合同；完整访谈过程只留在 Journal。

### 3.3 深接口：模型不管理基础设施字段

OpenCode adapter 应暴露面向意图的少量工具，而不是一个包含双重 `kind` 和大量 JSON 字符串的
浅接口：

```text
ingest_source(content | file | url) -> source_ref
publish_feature_contract(contract)  -> artifact_refs
run_delivery_verification(feature_id) -> evidence_ref
finalize_delivery(candidate_id) -> version_ref
```

以下字段由 adapter/Core 自动生成，永远不让模型填写：

- idempotency key；
- run/attempt/event id；
- changed files；
- Git baseline/current fingerprint；
- D→C、AC→test-file evidence edge；
- policy-injected checks；
- process identity；
- artifact hash；
- timestamps 和 tool versions。

这同时落实 Matt Pocock 的 deep module：模型只学习一个小接口，复杂事务、校验和恢复隐藏在 Core
内部。

### 3.4 单 coder、有界 delivery loop

推荐 loop：

```text
inspect once
  → edit
  → focused check
  → 若失败：targeted repair（最多 2 次）
  → authoritative verification（只由 Core 执行一次）
  → 若失败：按 failure delta targeted repair（最多 1 次）
  → re-verify
  → PASS 或 BLOCKED
```

约束：

- coder 不手动执行会被 hook/Core 重复执行的完整 compile/restart/health；
- 同一 error fingerprint 连续出现 2 次，停止自动重试；
- 总 coder dispatch 默认 1，只有 host 会话不可恢复时才允许第 2 次；
- schema/tool/path/evidence metadata 错误不得重新派发 coder；
- 每轮只注入：当前 Feature Contract、允许路径、相关源码、上次 failure delta；
- 失败日志落盘，模型只接收首个根因、退出码和受限尾部；
- retry 不能扩大 scope。

### 3.5 Failure Router：决定修什么，而不是一律重跑 Agent

| Failure class | 处理方 | 是否重派 coder |
|---|---|---|
| schema/tool 参数可规范化 | adapter/Core | 否 |
| idempotency 冲突 | adapter 生成新 operation key 或复用缓存 | 否 |
| Git path / diff / evidence edge | Core 从 VCS 和文件系统生成 | 否 |
| policy control 缺项 | profile 自动注入 | 否 |
| handoff 缺少机器可推导字段 | Core 补齐 | 否 |
| compile/type/lint 代码错误 | 同一 coder + failure delta | 否 |
| unit/integration/e2e 失败 | 同一 coder targeted repair | 否 |
| 环境、凭据、设备不可达 | BLOCKED，保留现场 | 否 |
| 真实需求歧义 | 请求用户决策，checkpoint | 否 |
| host session 丢失 | 用 context pack 恢复 | 必要时一次 |

### 3.6 验证金字塔与唯一执行者

1. 写码循环：只跑最接近改动的测试或 typecheck target。
2. code boundary：Core 做 schema、diff、protected path、compile、profile controls。
3. delivery boundary：Core 做 stop → start → readiness/health → AC 测试 → cleanup。
4. finalize boundary：校验 evidence fingerprint 未陈旧。

完整 build、启动和浏览器 E2E 每个交付候选只运行一次；只有代码 fingerprint 发生变化才失效重跑。
不同且无资源冲突的 lint/static analysis/unit 可以并行。严禁 coder 和 hook 各执行一次完整 build。

### 3.7 轻量 Journal 与恢复语义

保留 append-only Journal，但记录“边界”，不记录每一次模型思考：

```text
run.json
  run_id, feature_id, phase, status
  baseline_fingerprint, current_fingerprint
  active_attempt, host_session_id
  started_at, updated_at, budget

events.jsonl
  run_started
  source_ingested
  decision_recorded
  contract_published
  code_changed
  verification_started/passed/failed
  run_blocked/completed

attempt.json
  step, input_hash, state
  error_fingerprint
  evidence_refs[]
  started_at, ended_at
```

写 checkpoint 的时机只有：

- 用户回答一个 blocking decision；
- 原子发布 Feature Contract；
- 生产代码 fingerprint 改变；
- lifecycle 副作用完成；
- 验证产生结果；
- Run 进入 BLOCKED/COMPLETED。

恢复算法：

1. 校验 project root、baseline 和 active profile；
2. 把 owner 已退出的 running attempt 标为 aborted；
3. 找最后一个 completed boundary；
4. 若 output fingerprint 与 Journal 一致，跳过该 step；
5. 若有可恢复 host session 则继续它，否则用最小 context pack 创建新会话；
6. 永不尝试恢复模型内部 token/思维状态。

### 3.8 可观测性应回答四个问题

`sdlc_status` 和最终报告只需快速回答：

1. 当前在哪个 phase/step，已耗时多久？
2. 正在等待模型、进程、用户还是验证器？
3. 最近一次失败的 class、fingerprint、证据路径是什么？
4. 下一步会执行什么，是否会复用已有 evidence？

建议指标：

- phase wall time；
- model wait / lifecycle wait / user wait；
- coder dispatch count；
- verification count 和 cache hit；
- repeated error fingerprint count；
- context pack chars/files；
- full build、start、browser E2E 次数；
- 每阶段 token（仅使用 host 可可靠提供的聚合值）。

不要把重复 event 中的累计 token 再求和，也不要把完整 stdout 写入 Tool 返回值。

## 4. 建议的默认性能预算

以下是本项目应自行验证的工程目标，不是外部项目事实：

| 阶段 | 默认目标 | 硬边界 |
|---|---:|---:|
| Intake + profile 探测 | 1 分钟 | 2 分钟 |
| Spec-lite（不含用户等待） | 2 分钟 | 5 分钟 |
| coder | 8 分钟 | 15 分钟 |
| compile + controls | 3 分钟 | lifecycle timeout |
| start/health/AC tests/cleanup | 5 分钟 | lifecycle timeout |
| 总自动执行 | 20 分钟 | 30 分钟后 BLOCKED |
| blocking questions | 0–3 | 超过 3 需说明为何不能默认 |
| coder dispatch | 1 | 最多 2 |
| targeted repair | 0–2 | 同错误 2 次即 BLOCKED |
| full build | 1/代码 fingerprint | 禁止无变化重复 |
| browser E2E | 1/候选 fingerprint | 失败后仅重跑失败项，再做一次最终套件 |

关键原则不是保证所有功能 20 分钟完成，而是超过预算时停止并给出可定位证据，不能静默运行一小时。

## 5. 最终采用矩阵

| 来源 | 采用 | 不采用 |
|---|---|---|
| Superpowers | 先理解再实现、隔离 context、evidence before claims、风险触发 review | 每任务新 Agent、固定双 review、所有小改动完整流程 |
| ECC | minimal/opt-in、Skills-first、profile 选择、DRY adapter、边界 compact | 全量 agents/skills/hooks/MCP、continuous learning 进入关键路径 |
| Claude Code 官方 | 短常驻规则、按需 Skill、确定性 hook、受限 subagent、session 辅助恢复 | prompt verifier 判断确定性规则、checkpoint 替代 Journal |
| Matt Pocock skills | 查事实不问用户、bounded grilling、deep module、tight feedback loop、seam tests | 无上限 grilling、为形式而建立大量 seam |
| Karpathy-inspired | simplicity、surgical change、goal-driven verification | 把四条提示词当编排系统 |
| Karpathy autoresearch | baseline、固定作用域、固定 verifier、时间预算、简短实验账本 | 无限实验、允许修改验证器 |
| Ralph | 根据机器反馈持续修复、max iterations | 同 prompt 无差别重放、没有新证据仍继续 |

## 6. 对当前仓库的实施优先级

### P0：先消除确定性失败导致的 Agent 重跑

1. Git porcelain 使用 `-z` 解析，禁止 `.strip()` 破坏前导状态列；
2. idempotency key 从模型 schema 中移除；
3. 拆分 publish 工具，消除双重 `kind`；
4. lint/static analysis 从业务 test plan 移到 profile controls；
5. changed files 和 evidence edge 由 Core 生成；
6. 增加 Failure Router，同错误指纹达到上限后 BLOCKED。

### P1：把流程压缩为一个 Feature Slice

1. 实现 Feature Contract schema 和三种确定性视图；
2. bounded grilling，最多 3 个产品 blocking decision；
3. 单 coder 连续 loop，失败只回传 delta；
4. 唯一 lifecycle owner，去掉 coder/hook 双 build；
5. evidence 按 code + contract + lifecycle fingerprint 复用。

### P2：完成轻量恢复与性能验收

1. Journal 只记录 durable boundary；
2. host session id + 自有 Journal 双层恢复；
3. 增加 elapsed、wait class、dispatch/build/retry 计数；
4. 建立 old/new differential benchmark；
5. Electron 参考用例固定为：
   `init → Home+设备信息 spec → code → compile/start/health → unit/E2E → cleanup → finalize`；
6. 注入 spec 中断、coder 代码失败、进程残留、测试失败、host 重启；
7. 除正确恢复外，还必须验证每条故障不会触发无关的完整 coder/build 重跑。

在 Electron 金标准达到时间预算和恢复标准前，不扩展 Spring、Node Web、Python API profile。

## 7. 最终判断

当前项目不需要更大的 Agent 组织，而需要更深的确定性 Core 和更短的 Agent loop。

推荐形态是：

> **短规则 + 单 Feature Contract + 单 coder 有界循环 + Core 唯一验证 +
> 边界 Journal + Git/evidence fingerprint。**

可追溯性应来自机器自动生成的事实边，而不是让模型重复书写文档；可恢复性应来自幂等边界和
fingerprint，而不是恢复思考；可靠性应来自不可由 coder 修改的 lifecycle verifier，而不是增加
reviewer 数量。这样既保留交付可信度，也能从结构上消除单个功能运行近一小时的主要放大器。
