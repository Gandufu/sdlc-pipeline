# SDLC Pipeline 2.0：Core-first Agent Harness 与项目软件工厂演进方案

状态：架构提案，待确认
日期：2026-07-30
适用范围：从零设计 SDLC Pipeline 2.0；现有实现与既有方案仅作为问题样本，不作为继承基线

---

## 0. 执行摘要

2.0 不应再被定义为“一个更大的 OpenCode 插件”，而应被定义为：

> **一个协议中立的软件工厂内核：用确定性 Core 管理项目事实、Task、门禁、证据和返工；用 Agent Action API 服务模型执行；用 Operator API 承载真正的人类审批；用 Framework Pack 适配不同项目模板；在过渡期通过 OpenCode Plugin、MCP、CLI 或 SDK Adapter 接入现有 Agent，最终演进为拥有一等 Agent Runtime 的项目软件工厂系统。**

核心结论：

1. **采用 Core-first、协议可插拔。** MCP、OpenCode Plugin、CLI、HTTP/SDK 都是过渡接入 Adapter；任何一个都不是状态机、审批系统、执行引擎或软件工厂内部总线。
2. **Core 不依赖固定模型或 Host Session。** 过渡期由 OpenCode、Claude Code、Codex、Hermes 等外部 Host 执行；终局由软件工厂自己的 Agent Runtime 调度模型和工具。
3. **模型工具与人工控制接口必须分离。** `approve spec`、`approve delivery`、发布、豁免门禁等操作不能作为普通模型工具暴露。
4. **模板不是一组 prompt。** Framework Pack 必须提供机器可验证的能力清单、命令、路径边界、环境变量白名单、结果解析器和 TCK。
5. **模板能力不直接暴露给模型。** 模型只能请求“运行本 Task 的 mandatory gates”；Core 决定调用哪个模板能力、以什么顺序、用什么解析器裁决。
6. **项目仓库是长期事实来源。** Project 长期存在，Task 是一次增量变更，Session 是临时入口，Attempt 是一次执行，Git 保存历史。
7. **第一步不建设完整软件工厂平台。** 先在一个真实 Electron 项目上，用一个最薄 Adapter 跑通快速迭代闭环；Adapter 选 OpenCode Plugin、MCP 或 SDK，只由验证成本决定。
8. **第一阶段只验证一条最短闭环：**

   ```text
   恢复项目上下文
     → 创建/恢复 Task
     → 编辑增量提案
     → 确定性校验
     → 人工批准
     → Agent 实现
     → Harness 执行门禁
     → 结构化失败返工
     → 人工验收
     → Delivery Ready
   ```

9. **不在 P0 引入** Baseline 快照目录、SQLite、远程服务、多项目调度、动态多 Agent 组织、自动学习、模板 RPC、自动提交或发布。
10. **以验收场景决定是否继续。** 若跨 Session 恢复、失败定向返工、模板隔离和真实运行闭环不能在 10 个工作日左右的验证窗口内成立，应停止扩建并修正契约，而不是继续堆功能。

---

## 1. 重新定义问题

### 1.1 要解决的不是“如何让 Agent 多做事”

真正要解决的是五个可验证问题：

1. 一个项目长期演进时，新的 Task 如何复用当前有效的需求、设计、接口和测试事实。
2. Agent 中断、换 Session、换模型或换宿主后，如何从业务检查点恢复，而不是依赖聊天记录。
3. Agent 修改代码后，谁用什么不可篡改的规则判断“可以继续”。
4. 不同框架模板如何用同一套编排接口完成准备、构建、测试、启动、就绪、功能验证和清理。
5. 从单项目 Harness 演进到多项目软件工厂时，哪些契约可以保留，哪些能力应上移到控制面。

### 1.2 本方案采纳的约束

`codex意见.md` 中称为“十一条建议”的部分实际列出了 12 条不变量。本方案不直接继承其具体布局，但采纳其中经重新论证后仍成立的约束：

- Project 是长期实体；Task 是一次有明确目标的增量变更。
- Session 只用于交互和尽力恢复，不是业务生命周期实体。
- Task 可以修改多个 Feature，但必须声明影响范围。
- 项目当前事实使用仓库内、可阅读、可版本化的文档表达。
- JSON 只保存索引、状态、引用、哈希和紧凑诊断，不保存大段需求或对话正文。
- Git 是项目文档和代码的历史系统，不再复制一套“历史文件系统”。
- Finalized Task 不回退；后续缺陷创建关联 Task。
- Core 决定状态、门禁、证据新鲜度和失效范围，Prompt 不能解释或覆盖状态机。

### 1.3 参考方案中不预设保留的内容

下列内容全部重新验证，不作为前提：

- `Change + Task` 双层聚合；
- Baseline 快照目录或 Baseline 编号；
- SQLite 作为单项目初期必需存储；
- “v1 MCP 协议就是最终协议”；
- 每 Project 一个常驻 Core 实例；
- MCP 可以替代审批 UI、宿主 hooks 或 CI API；
- v1 只做 compile/unit test、把真实运行和功能验证推迟到软件工厂阶段；
- 由模型直接调用 `approve`、`merge`、`finalize` 或 `publish`。

---

## 2. 为什么是 Core-first，而不是先押注某个接入协议

### 2.1 三种形态比较

| 过渡接入形态 | 优点 | 结构性问题 | 使用位置 |
|---|---|---|---|
| OpenCode 薄插件 | 复用现有宿主事件、权限、Session、工具拦截 | 锁定宿主；Plugin API 变化；CI/平台复用差 | 若它是 P0 最短路径就继续用，但只做代理 |
| MCP Adapter | 跨宿主；typed tools 标准化；容易做 Inspector/契约测试 | 不能统一观察 prompt/edit/session；Host 支持不一致；协议仍在快速变化 | 适合互操作和外部 Host 接入，不是内核 |
| CLI/本地 SDK Adapter | 实现和测试最直接；可供 CI 与黑盒测试调用 | 模型宿主体验需要再包装 | 应作为参考 Adapter 和 Operator 入口 |
| HTTP/Event API | 适合最终平台、远程 Runner 和控制面 | P0 服务化成本高 | 软件工厂阶段启用 |
| First-party Agent Runtime | 可以统一上下文、预算、权限、作业、审批和观测 | 只有平台形成后才值得建设 | **终局执行入口** |

推荐结构不是 `Core + MCP`，而是：

```text
Protocol-neutral Core
  + versioned Agent Action API
  + Operator API
  + Framework Pack API
  + replaceable Adapters
```

P0 先实现 in-process/CLI reference adapter 和一个最短 Host Adapter。MCP 是否进入 P0，由一项限时兼容性探针决定，不能反向决定 Domain。

### 2.2 MCP 作为过渡 Adapter 时的正确职责

MCP 当前规范将 Host、Client、Server 分开，Server 负责提供 Resources、Prompts 和 Tools；协议本身不拥有业务状态机。2026-07-28 规范又改为无状态、自包含请求和按请求能力协商，并把 Tasks、Skills over MCP 等放到可选扩展中。这说明 Domain 必须与 MCP 版本隔离，不能把某一版协议语义写进 TaskEngine。

若选择实现 MCP Adapter，它只负责：

- 暴露稳定、少量、结构化的 Agent Tool API；
- 将 MCP 输入转换为 Application Use Case；
- 将 Core 结果转换为 `structuredContent + outputSchema`；
- 协商 Resources、Prompts、Tasks 等可选能力；
- 提供协议版本与宿主兼容性诊断。

MCP Adapter 不负责：

- 推断或改变 Task 状态；
- 判定测试是否通过；
- 直接执行模板命令；
- 证明用户已经批准；
- 保存 Host transcript；
- 选择模型或组织多 Agent；
- 充当软件工厂内部所有服务的通信协议。

### 2.3 为什么审批不能是普通 MCP Tool

MCP Tool 是 model-controlled。Host 可以提示用户确认调用，但不同 Host 的 UI、权限和审计能力不同；Server 不能仅凭 `confirmed: true` 证明它来自人类。

因此 2.0 必须划分两个信任域：

```text
Agent Tool API
  模型可见、可调用
  用于读取上下文、提交待验证内容、运行受控门禁、记录反馈

Operator Control API
  模型不可直接调用
  通过 CLI、Host UI、Web Portal 或签名审批消息触发
  用于批准 Spec、确认人工验收、批准 Delivery、取消 Task、未来的门禁豁免
```

Host 自带的 tool approval 仍可作为第一道交互保护，但不能代替 Core 的 Operator Receipt。

### 2.4 为什么过渡期仍可能需要 Host Adapter

纯 MCP 无法统一获得以下事件：

- 用户提交 prompt；
- Session start/stop/compact；
- 普通 Read/Edit/Bash 工具调用；
- 子 Agent 创建和结束；
- 宿主 permission decision；
- 当前消息、Session 与 worktree 的稳定关联。

OpenCode 和 Claude Code 都提供 hooks、skills、agents 和权限能力，但 API 不相同。因此 Host Adapter 只做：

- 安装或发现所选连接方式（MCP、Plugin tool、CLI/SDK）；
- 提供一个短入口 Skill/Command；
- 将 Host session/worktree 作为非权威 metadata 传给 Core；
- 在宿主支持时，将高风险操作映射到 `ask/deny`；
- 记录 Host 事件或提示用户恢复当前 Task；
- 不实现任何生命周期判断。

OpenCode V2 Plugin API 当前仍标记为 beta，更应保持可替换和可删除。软件工厂拥有 First-party Agent Runtime 后，Host Adapter 退化为外部入口，不再是主执行面。

---

## 3. 外部 Agent/Harness 生态：采用什么，不采用什么

| 来源 | 值得采用 | 不应照搬 |
|---|---|---|
| Claude-Code-Game-Studios | 领域边界、path-scoped rules、文档模板、显式协作/批准、变更传播意识 | 49 agents、73 skills 和模拟组织层级不是通用软件交付的最小内核 |
| Superpowers | 先设计后实现、worktree、TDD、完成前新鲜证据、失败后系统诊断 | 每个微任务都冷启动 Agent、双重 review、所有任务强制完整流程 |
| ECC | minimal/profile 安装、能力 opt-in、共享实现配多宿主适配器、上下文节制 | 把 agents、hooks、memory、security、continuous learning 全部放入关键路径 |
| mattpocock/skills | 小而可组合的 skills、deep module、先建立紧反馈回路、domain vocabulary | 让一个 workflow framework 拥有所有过程，或把 skill 当成状态机 |
| Claude Code | Skills 按需加载、Subagent 上下文隔离、Hooks 执行确定性边界动作、MCP 按 Agent 缩小暴露面 | 把 transcript/checkpoint 当业务存储；用模型 hook 判定可编码规则 |
| OpenCode | MCP 本地/远程接入、Agent 级权限、按需 Skills、可选 Plugin hooks | 将 beta Plugin API 变成 Core 依赖；一次暴露大量 MCP 工具挤占上下文 |
| Hermes | Skills 与 Memory 分工、渐进披露、模型/工具提供方可替换 | 让自动学习即时修改当前项目的权威规则、门禁或模板 |
| OpenAI Harness Engineering | 仓库知识作为系统事实、给 Agent 地图而不是大手册、每 worktree 可运行、日志/指标对 Agent 可读、机械执行架构约束 | 在 P0 就复制百万行项目所需的完整可观测性和自治规模 |

由这些项目共同指向的不是“更多 Agent”，而是以下 Harness 形状：

```text
小上下文入口
  + 可发现的深层项目知识
  + 隔离且可运行的工作区
  + 不可由 Agent 改写的验证器
  + 有预算的证据反馈循环
  + 明确的人类决策边界
```

---

## 4. 目标架构

### 4.1 过渡期：本地 Agent Harness

![过渡期协议中立本地 Harness](SDLC-Pipeline-2.0-Transition-Harness.svg)

可编辑源文件：[SDLC-Pipeline-2.0-Architecture.drawio](SDLC-Pipeline-2.0-Architecture.drawio) 第 1 页。

过渡期只要求“所选 Adapter 足够薄、可替换”。如果现有 OpenCode 插件是最快验证路径，可以继续用；如果 MCP 能更低成本地提供 typed tools，就使用 MCP；如果两者都拖慢 P0，则直接用本地 SDK/CLI 驱动黑盒闭环。

### 4.2 七个架构边界

1. **Domain Kernel**：状态、失效规则、不变量、错误分类；纯代码、无 MCP、无 Host、无模型调用。
2. **Application Layer**：编排 Use Case、幂等、乐观并发、Operator Receipt、证据绑定。
3. **Harness Runtime**：工作区、进程、就绪、测试、超时、清理、日志与 Evidence。
4. **Template Port**：把框架差异收敛成 Capability，不把命令暴露给模型。
5. **Agent Action API**：协议中立、版本化的模型动作接口；Adapter 只能映射它。
6. **Operator/Factory API**：人与平台使用的控制接口，不与模型权限混合。
7. **Adapters**：Plugin、MCP、CLI、SDK、HTTP 都可替换；删除任一 Adapter 不应破坏 Core 测试。

### 4.3 终局：项目软件工厂系统

![项目软件工厂终局架构](SDLC-Pipeline-2.0-Project-Software-Factory.svg)

可编辑源文件：[SDLC-Pipeline-2.0-Architecture.drawio](SDLC-Pipeline-2.0-Architecture.drawio) 第 2 页。

终局变化不是“把本地 MCP Server 部署到云上”，而是：

- 平台拥有 Project、Task、Run、Approval、Template、Policy、Environment 和 Delivery 的控制面；
- 平台拥有一等 Agent Runtime，统一模型路由、上下文、预算、工具、隔离、评审和观测；
- Harness Runtime 下沉为可水平扩展的 Execution Plane；
- MCP 只保留为外部 Agent Host Gateway，可存在，也可以完全不用；
- 本地 2.0 Core 的 Domain、Action、Template、Evidence 契约成为平台服务的种子，而不是部署拓扑。

### 4.4 软件工厂内部不用 MCP 一统天下

未来的 Project Registry、Template Registry、Runner、Artifact Store、Approval Service、Event Bus 应使用适合服务间通信的 HTTP/gRPC/Queue/Object Storage 接口。MCP 只在需要让外部模型发现和调用能力时作为可选 Gateway。

---

## 5. 最小领域模型

| 概念 | 语义 | 是否长期 |
|---|---|---:|
| Project | 产品、仓库和项目事实边界 | 是 |
| Feature | 稳定产品能力，用于组织 Requirement 和依赖 | 是 |
| Requirement | 当前有效产品行为及验收条件 | 是 |
| Task | 一次有明确交付目标的增量变更，可跨 Feature | 是 |
| Attempt | Task 某阶段的一次有预算执行 | 是，紧凑索引 |
| GateRun | 一次确定性门禁运行，绑定输入 revision | 是，证据化 |
| Evidence | 日志、测试结果、截图、差异、运行收据的引用 | 是或按保留策略 |
| Delivery | Task 达到可交付状态的签名收据，不等同于部署 | 是 |
| Session | 某宿主的一次交互入口 | 否，仅 metadata |

不引入独立 `Change` 聚合。Task 已经表达一次变更；若未来需要把多个 Task 打包发布，新增的是 Release/Delivery Group，不应再在 Task 上方复制一套变更生命周期。

### 5.1 Task 状态机

![Task 状态机](SDLC-Pipeline-2.0-Task-State.svg)

可编辑源文件：[SDLC-Pipeline-2.0-Architecture.drawio](SDLC-Pipeline-2.0-Architecture.drawio) 第 3 页。

规则：

- 状态转换由事件和 Core guard 决定，模型不能传入目标状态。
- 返工只使受影响的下游 GateRun/Approval 失效，不删除历史 Evidence。
- Finalized 后发现问题时创建 `related_to` 原 Task 的新 Task。
- P0 每个可写 workspace 只有一个活动 Task；并发通过不同 worktree 隔离，后续再增加 Project 级冲突检测。
- 同一失败指纹连续出现两次且没有新的 failure delta，或超过 Attempt 预算时进入 `Blocked`，不继续无差别重试。

---

## 6. 项目事实、Task 与运行态存储

### 6.1 推荐布局

```text
docs/sdlc/                              # Git 管理，当前有效事实
  project.md                            # 产品目标、Feature 地图、依赖、索引
  requirements.md                       # 当前有效 Requirement / AC
  architecture.md                       # 模块、接口、数据流、ADR 引用
  verification.md                       # R/AC -> Gate/Test 追溯
  tasks/
    active/TASK-0001/proposal.md        # 待批准增量，不是全量 Spec
    completed/TASK-0000/delivery.md     # 完成摘要与 Evidence 引用

.sdlc/                                  # Orchestrator 运行态
  project.json                          # project_id、模板绑定、facts_revision
  tasks/TASK-0001/
    state.json                          # 紧凑状态、版本、引用
    events.jsonl                        # 只追加领域事件
    attempts/
      ATTEMPT-0001.json                 # 输入/结果/evidence refs
  evidence/TASK-0001/
    GATE-0001/
      result.json
      stdout.log
      stderr.log
```

### 6.2 存储原则

- `docs/sdlc/*.md` 表达当前事实，不按 Task 复制完整项目文档。
- `proposal.md` 表达 Task 对当前事实的增量，不创建 Candidate 分片工具。
- `facts_revision` 由正式文档内容哈希组成；批准和 Delivery 必须绑定精确 revision。
- Git 保存历史，不创建 `baselines/<id>/` 快照树。
- SQLite 不进入 P0。未来控制面数据库只是索引/投影，不取代仓库事实。
- 大日志永远通过 Evidence URI/路径引用，不塞进 Tool result、JSON 索引或模型上下文。
- 外部文件默认只是用户/宿主提供的参考。只有明确需要长期保存时才进入项目仓库并由 Git 管理；Core 不自动建立 Source 归档系统。
- 密钥、设备 IP、Token 和临时环境信息只由 Runtime Secret Provider 注入。

---

## 7. 四类接口

## 7.1 Agent Action API：供 Agent Runtime 或外部模型 Adapter 调用

P0 最多定义 7 个深动作。它们先作为 Python Application API 和 JSON Schema 固化，再由所选 Adapter 映射为 Plugin tools、MCP tools、SDK methods 或 HTTP actions：

| Tool | 作用 | 是否修改状态 |
|---|---|---:|
| `sdlc_status` | 返回当前 Task、state、有效/失效 gate、阻塞、下一步 | 否 |
| `sdlc_task_open` | 根据目标创建 Task，或显式恢复已有 Task | 是，低风险且幂等 |
| `sdlc_context_get` | 按 Feature/R/D/T/失败指纹编译最小上下文包 | 否 |
| `sdlc_spec_validate` | 读取仓库内 `proposal.md`，校验并冻结 proposal hash | 是 |
| `sdlc_gate_run` | 请求 Core 运行当前状态允许的 gate set | 是 |
| `sdlc_feedback_record` | 记录人工/自动反馈，Core 分类并使下游证据失效 | 是 |
| `sdlc_delivery_prepare` | 检查新鲜证据并生成待人工批准的 Delivery Preview | 是 |

明确不向模型暴露：

- `approve_spec`
- `approve_review`
- `approve_delivery`
- `override_gate`
- `git_commit`
- `git_push`
- `release_publish`
- 任意模板原始命令执行
- 任意状态跳转

所有修改类工具必须携带：

```json
{
  "project_ref": "...",
  "task_id": "TASK-0001",
  "expected_task_version": 7,
  "idempotency_key": "caller-stable-key"
}
```

所有 Action 使用统一输出包络：

```json
{
  "schema_version": "sdlc.tool-result/v1alpha1",
  "ok": false,
  "project_id": "PRJ-0001",
  "task_id": "TASK-0001",
  "task_version": 8,
  "state": "executing",
  "summary": "unit gate failed",
  "next_actions": [
    {
      "kind": "agent_action",
      "tool": "sdlc_context_get",
      "reason": "读取本轮新增 failure delta"
    }
  ],
  "diagnostics": [
    {
      "code": "GATE_TEST_UNIT_FAILED",
      "category": "product",
      "retryable": true,
      "fingerprint": "sha256:...",
      "evidence_ref": "sdlc://evidence/GATE-0007"
    }
  ],
  "artifact_refs": []
}
```

设计要求：

- Action Schema 与传输协议无关；状态码、诊断、Artifact/Evidence 引用在所有 Adapter 中保持一致。
- 映射为 MCP 时提供 `outputSchema`、`structuredContent` 和兼容旧 Host 的短文本摘要。
- 映射为模型工具时，工具列表稳定、顺序稳定、描述短，避免破坏 prompt cache 和挤占上下文。
- MCP Resources 可映射 `sdlc://project/map`、`sdlc://task/...` 和 Evidence，但必须有等价 Action 查询路径。
- Prompts、Skills over MCP、MCP Tasks 只是 MCP Adapter 的增强能力，Core 和 P0 不依赖。

## 7.2 Operator Control API：供人调用

P0 提供本地 CLI，Host Pack 可把它包装为 UI：

```text
sdlc task approve-spec TASK-0001 --proposal-hash sha256:...
sdlc task accept-review TASK-0001 --task-version 12
sdlc task approve-delivery TASK-0001 --delivery-hash sha256:...
sdlc task block TASK-0001 --reason "等待真机"
sdlc task cancel TASK-0001 --reason "范围取消"
```

每次操作生成不可变 Operator Receipt：

```json
{
  "action": "approve_spec",
  "task_id": "TASK-0001",
  "subject_hash": "sha256:...",
  "task_version": 8,
  "actor": "local-operator",
  "timestamp": "...",
  "receipt_id": "APR-..."
}
```

P0 不做企业身份认证，但接口中预留 `actor` 和 `auth_context`；远程控制面阶段再接 OIDC/RBAC。

## 7.3 Framework Template Provider API：供 Core 调用

Framework Pack 的逻辑接口：

```text
describe()                -> PackDescriptor
inspect_project(root)     -> ProjectFacts
materialize(inputs, root) -> MaterializeResult      # 新项目时可选
prepare_workspace(ctx)    -> WorkspaceReceipt
execute(capability, ctx)  -> ExecutionReceipt
collect_evidence(run)     -> EvidenceRefs
cleanup(workspace)        -> CleanupReceipt
```

P0 只实现声明式 Provider，由 Core 统一解释 Manifest；不允许 Pack 自带常驻 RPC 服务。遇到真实声明式能力无法表达的案例后，才评估 executable provider。

## 7.4 Factory Control API：未来平台调用

软件工厂阶段再增加：

- Project Catalog API
- Template Registry API
- Policy Registry API
- Run Queue / Runner API
- Artifact & Evidence API
- Approval API
- Release / Deployment API
- Audit Event Feed

这些接口面向平台和服务，不直接全部暴露给模型。

---

## 8. Framework Pack 契约

### 8.1 Pack 结构

```text
framework-packs/electron-react/
  template.yaml
  scaffold/                   # 可选，创建新项目时使用
  context/
    architecture.md
    testing.md
  policies/
    paths.yaml
  parsers/                    # P0 仅允许 Core 内置 parser ID
  tck/
    success-fixture/
    failure-fixture/
```

### 8.2 Manifest v1alpha1

```yaml
apiVersion: sdlc.dev/framework-pack/v1alpha1
kind: FrameworkPack
metadata:
  id: electron-react
  version: 0.1.0
  digest: sha256:...

compatibility:
  core: ">=2.0.0-alpha <2.1.0"

project:
  markers:
    allOf: ["package.json"]
    anyOf: ["forge.config.*", "electron.vite.config.*"]
  contextEntries:
    - path: docs/architecture.md
      when: architecture

paths:
  writable:
    - src/**
    - tests/**
  protected:
    - .sdlc/**
    - docs/sdlc/**
    - .github/**

capabilities:
  project.inspect:
    runner: builtin

  dependencies.restore:
    runner: process
    argv: ["pnpm", "install", "--frozen-lockfile"]
    cwd: "."
    timeoutSeconds: 900
    environmentAllowlist: ["CI", "PNPM_HOME"]
    writes: ["node_modules/**"]
    resultParser: exit-code

  code.check:
    runner: process
    argv: ["pnpm", "check"]
    cwd: "."
    timeoutSeconds: 600
    environmentAllowlist: ["CI"]
    writes: []
    resultParser: exit-code
    blocking: true

  test.unit:
    runner: process
    argv: ["pnpm", "test", "--", "--run"]
    cwd: "."
    timeoutSeconds: 900
    environmentAllowlist: ["CI"]
    writes: ["coverage/**", "test-results/**"]
    resultParser: junit-or-exit-code
    blocking: true

  app.start:
    runner: process
    argv: ["pnpm", "start"]
    lifecycle: background
    timeoutSeconds: 120
    readiness: app.ready

  app.ready:
    runner: probe
    probe:
      type: process
      argv: ["node", "scripts/readiness.mjs"]
    timeoutSeconds: 60

  test.functional:
    runner: process
    argv: ["pnpm", "test:functional"]
    timeoutSeconds: 1200
    resultParser: playwright-json
    blocking: true

  app.stop:
    runner: builtin
    lifecycle: cleanup
```

### 8.3 稳定 Capability 命名

Core 标准能力：

```text
project.inspect
scaffold.materialize
workspace.prepare
dependencies.restore
code.check
test.unit
app.start
app.ready
test.functional
app.stop
package.build
```

未来能力使用命名空间扩展，例如：

```text
contract.openapi.validate
security.sbom.generate
deploy.sit
device.yealink.smoke
```

Capability 只是执行能力，不得定义 Task 状态转换或审批策略。

### 8.4 Template Contract Test Kit

每个 Framework Pack 必须通过：

1. Manifest Schema 和 Core version range 校验。
2. 禁止 shell 字符串，只允许 `argv` 数组。
3. `cwd`、writable/protected path 解析不能逃逸项目边界。
4. 未声明环境变量不得注入。
5. 每个后台进程必须有 readiness、timeout 和 cleanup。
6. success fixture 必须成功；failure fixture 必须被 parser 稳定识别为失败。
7. cleanup 至少执行两次仍安全。
8. Evidence 必须包含 capability、开始/结束时间、exit code、revision、stdout/stderr refs。
9. Pack 不得修改 `.sdlc/**`、审批收据或 Core policy。
10. 同一输入重复运行应得到相同裁决；允许日志时间等非语义字段不同。

Framework Pack 由平台/Core 调用，模型没有 `execute_raw_capability`。

---

## 9. Harness 闭环

![Harness 反馈闭环](SDLC-Pipeline-2.0-Harness-Loop.svg)

可编辑源文件：[SDLC-Pipeline-2.0-Architecture.drawio](SDLC-Pipeline-2.0-Architecture.drawio) 第 4 页。

### 9.1 Failure Router

统一分类：

| Category | 默认去向 | 示例 |
|---|---|---|
| `product` | Executing | 编译失败、业务测试失败、运行崩溃 |
| `spec` | Draft | Requirement/AC/设计本身错误或缺失 |
| `test_contract` | Acceptance/Test repair | 测试脚本或 parser 错误 |
| `environment` | Blocked | 设备未到、端口占用、外部服务不可用 |
| `policy` | Blocked/Operator | Protected path、许可、安全策略 |
| `infrastructure` | 有预算重试后 Blocked | Runner 中断、磁盘、网络临时故障 |
| `unknown` | 一次诊断 Attempt 后 Blocked | 无法稳定复现 |

每次重试必须携带新的 failure delta：

- 新失败用例；
- 新堆栈；
- 新差异定位；
- 新环境状态；
- 新假设验证结果。

仅“再试一次”不构成新的 Attempt 依据。

### 9.2 Context Compiler

Agent 每次只获得当前动作需要的内容：

```text
项目地图摘要
+ 相关 Feature / Requirement / AC
+ 相关架构接口与 ADR
+ 当前 Task proposal 和决策
+ 当前 diff / workspace revision
+ 上一次新增 failure delta
+ 当前 Framework Pack 的相关规则
+ 允许与禁止路径
```

明确排除：

- 全部历史 transcript；
- 全部 Task 正文；
- 全量测试日志；
- 所有 Framework Pack；
- 所有无关 Tool/Action 描述；
- 已通过且未失效的 GateRun 详细输出。

---

## 10. P0：快速迭代骨架验证

### 10.1 P0 只回答四个问题

1. 同一 Core 能否在不依赖 Host Session 的情况下创建、恢复并完成一个 Task。
2. 失败能否定向回到正确阶段，而不是重跑整个流程。
3. 一个真实 Framework Pack 能否驱动 compile/unit/start/readiness/functional/cleanup。
4. Agent Action API 能否先被 reference adapter 和一个真实 Host Adapter 使用，且 Adapter 不拥有状态或门禁。

### 10.2 推荐技术切片

- 语言：Python，沿用现有 Core 工程经验。
- Core 调用：in-process Python API + JSON Schema reference adapter。
- Host 接入：在 OpenCode 薄插件、MCP stdio、CLI/SDK 中选择实测成本最低的一种；P0 只实现一个。
- MCP 探针：限时验证官方 SDK 的 typed tools/structured result；验证不通过即延后，不阻塞 Core。
- 状态：Markdown + JSON + JSONL + filesystem atomic write。
- 目标项目：隔离的 Electron canary project。
- 第一执行宿主：优先复用当前 OpenCode，但不把它写入领域契约。
- 第二宿主：不是 P0 完成条件；P1 用于验证 Adapter 可替换性。
- Operator：本地 CLI。
- Framework Pack：`electron-react` 一个真实 Pack + 一个最小 fake Pack 用于 TCK。
- 执行：单 Project、单活动可写 Task、一个 Attempt 串行执行。

### 10.3 推荐骨架

```text
src/
  sdlc_core/
    domain/
    application/
    ports/
    persistence/
  sdlc_adapters/
    reference.py
    opencode/               # 或 mcp/，P0 二选一
    schemas/
  sdlc_operator/
    cli.py

adapters/
  mcp/                      # 可选兼容层，不是 Core 依赖
  host-packs/
    opencode/
    claude-code/

framework-packs/
  electron-react/
  fake-canary/

tck/
  action-api/
  adapters/
  framework-pack/
  lifecycle/

examples/
  electron-canary/
```

这是 clean-break 目标结构；若批准实施，应先通过 ADR 决定如何与当前 `scripts/sdlc_core/` 切换，不能长期维护两套正式 Core。

### 10.4 实施顺序

#### Slice 0：契约先行

- 固化领域词汇、Task 状态图、事件和失效矩阵。
- 写 Agent Action input/output schemas。
- 写 Operator Receipt schema。
- 写 Framework Pack manifest schema 和 fake TCK。
- 写 8 个黑盒验收场景；此时不接 Host。

#### Slice 1：Core 最小闭环

- `sdlc_status`
- `sdlc_task_open`
- proposal validation
- Operator spec approval
- GateRun/Evidence
- Failure Router
- Delivery Preview/approval

#### Slice 2：真实 Harness

- Electron Pack
- process runner
- background runtime + readiness + cleanup
- unit/functional result parser
- revision/evidence freshness

#### Slice 3：选定一个过渡 Adapter

- reference adapter contract tests
- OpenCode 薄插件或 MCP stdio 二选一
- 最小入口 Skill/Command
- Adapter 不含状态机的静态检查
- MCP 若未入选，只保留限时探针结论，不扩大实现

### 10.5 P0 黑盒验收

| ID | 场景 | 必须观察到的结果 |
|---|---|---|
| P0-01 | 新项目创建 Task | 生成 Task ID、proposal path、facts revision；不创建 Baseline 快照 |
| P0-02 | 模型尝试直接完成 Spec | 没有 Operator Receipt 时保持 `AwaitingSpecApproval` |
| P0-03 | 编译失败后修复 | 只重跑失效 gate；已通过且输入未变的 gate 不重复 |
| P0-04 | 同一失败指纹重复两次 | Task 进入 `Blocked`，返回 Evidence 和人工所需决策 |
| P0-05 | 新 Session 恢复 | 两次 Action 调用内得到 Task、下一步和最小上下文；不重复询问已确认事实 |
| P0-06 | 功能测试需要 Runtime | start → readiness → functional → cleanup 顺序确定，失败也执行 cleanup |
| P0-07 | 修改 protected path | Core 拒绝进入 GateRun；Host 是否有 hook 不影响裁决 |
| P0-08 | Delivery Preview | 必须绑定当前 project/task revision 和全部 mandatory GateRun |
| P0-09 | reference adapter 调用 Core | 不经过任何 Host 也能完成状态和 Gate 黑盒测试 |
| P0-10 | 选定 Host Adapter 调用 Core | input/output schema 与 reference adapter 一致，Host 不拥有状态 |

### 10.6 P0 成功指标

- 模型可见 SDLC Actions 不超过 7 个。
- 大日志不进入模型 Action result。
- Session 恢复不依赖 transcript。
- 同一 idempotency key 不产生重复事件或 GateRun。
- 所有完成声明都能追到当前 revision 的新鲜 Evidence。
- Template 命令、parser、path policy 不能被模型参数覆盖。
- Operator Approval 无法由普通 Agent Tool 伪造。
- 选定 Adapter 删除后，Core、Action TCK 和 lifecycle 测试仍通过。
- 一次窄 Feature 的失败修正不重新执行 init/spec 全流程。

### 10.7 P0 停止/转向条件

出现任一情况即停止加功能：

- 同一结构性失败连续三轮没有新证据；
- 任何 Adapter 要求把状态机或裁决逻辑搬出 Core；
- Framework Pack 为表达真实 Electron 生命周期必须绕过 Core runner；
- Operator Approval 仍能被模型路径伪造；
- 跨 Session 恢复仍必须读取 Host transcript；
- 为跑通一个 Feature 被迫先引入数据库、多项目调度或远程控制面。

---

## 11. 软件工厂演进路线

路线按“能力门槛”推进，不按版本号堆功能。

### 阶段 P0：Contract & Canary

交付：

- Core Kernel
- Agent Action reference adapter
- Operator CLI
- Electron Framework Pack
- 一个最薄的真实 Host Adapter
- TCK + canary

退出条件：第 10.5 节全部通过。

### 阶段 P1：Local Project Harness

新增：

- Task worktree provider
- 多 Task 只读并存、单 worktree 写租约
- UI/浏览器可读 Evidence
- 更完整的 spec/product/test/environment Failure Router
- 第二 Adapter conformance；可选验证 MCP/Claude Code，但不绑定产品方向
- Delivery 与 Git commit 的显式 Operator 集成，但不自动 push

退出条件：两个真实项目持续使用，跨 Session 恢复和定向返工稳定。

### 阶段 P2：Factory Kernel & First-party Agent Runtime

新增：

- 第一方 Agent Scheduler、Model Gateway、Context Compiler 和 Tool Gateway
- 可恢复的 Agent Job、预算、取消、人工接管和 Review/Eval Runtime
- 本地单节点 Project Service 与 Runner Service
- Framework Pack Registry
- Pack digest、签名、兼容性和升级检查
- Policy Pack 与 Framework Pack 分离
- Spring Boot/前后端分离等第二类真实模板
- Pack conformance matrix
- CI headless client

退出条件：

- 至少两种显著不同技术栈无需修改 Core 状态机即可完成同一流程；
- 不依赖 OpenCode/Claude Code Session，也能由第一方 Agent Runtime 完成 canary；
- 外部 Host Adapter 与第一方 Runtime 共享同一 Agent Action 契约。

### 阶段 P3：Project Software Factory MVP

新增控制面：

- Project Registry
- 项目创建/导入、模板绑定与项目地图
- 面向单项目的 Task/Feature/Requirement/Verification 工作台
- Run Queue 和隔离 Runner
- Artifact/Evidence Store
- Approval Service
- Secrets/Environment Provider
- Release/Deployment 编排
- 项目级 RBAC、审计事件和运行态可观测性
- Web Portal 与 Platform API

此时产品已经是可独立使用的“项目软件工厂系统”。MCP 可以是外部 Agent Gateway，也可以完全不部署；Core 内部服务使用普通平台协议。

退出条件：一个项目可以从创建/导入、需求 Task、实现、验证、审批一直编排到 Release/Deployment，且执行证据完整可审计。

### 阶段 P4：Multi-project & Organization Governance

新增：

- 组织级 Template/Policy 分发
- 项目组合视图
- 多项目队列、配额和 Runner 调度
- 合规证据投影
- CSCI/接口/供应链/SBOM 能力包
- SIT/UAT/设备实验室 Environment Descriptor
- 成本、时延、成功率和返工原因指标

这些能力通过新增 Capability/Policy/Projection 实现，不修改 P0 Task 核心语义。

### 阶段 P5：Adaptive Agent Factory

最后才引入：

- 多 Agent 调度与依赖图；
- 基于风险选择 reviewer/tester；
- 模型路由和预算优化；
- 历史 Evidence 检索；
- Skill/Prompt 建议与自动评估；
- 受控经验沉淀。

自动学习只能先进入 shadow/evaluation：

```text
历史数据
  → 生成候选 Skill/Policy
  → 离线 Eval / TCK
  → 人工批准
  → 新版本发布
```

它不得直接修改当前 Task 的 Gate、审批规则或 Framework Pack。

---

## 12. 对两份参考方案的取舍

### 12.1 `codex意见.md`

保留：

- Project/Task/Session/Attempt 分离；
- 项目级当前事实；
- Task 增量提案；
- JSON 索引、Markdown 正文；
- Git 历史；
- Finalized 后以新 Task 修复；
- Core 决定状态和门禁。

调整：

- “一个 worktree 只允许一个活动 Task”改为 P0 写租约，后续允许多 worktree 并发。
- 工具面不再只按 `status/task/spec/execute/finalize` 粗分，而按 Agent/Operator 信任域分离。
- `execute` 不让模型选择原始模板命令。
- 增加 Context Compiler、Template Port、Evidence、Failure Router 和 Host Pack。
- 不把“外部文件永不管理”写成绝对规则；默认不归档，但项目可显式纳入 Git。
- Release/Delivery 不从终态蓝图删除，只从 P0 自动化范围移出。

### 12.2 `SDLC-Pipeline-最终版设计方案.md`

保留：

- 可插拔跨宿主入口的方向；MCP 只是候选实现；
- Harness 中 AI 生成、规则裁决；
- 模板 Capability；
- Evidence 指针；
- 从单项目向软件工厂演进。

拒绝或调整：

- 不采用 Baseline 快照树。
- 不在 P0 默认引入 Change 聚合和 SQLite。
- 不声称 MCP 协议“零迁移成本”或 v1 即最终协议。
- 不把人类审批设计成模型可调用工具。
- 不把 Integration/E2E 全部推迟；P0 必须至少验证一个真实 start/readiness/functional/cleanup 闭环。
- 不固定每 Project 一个 Core 实例；Project 是权限和状态作用域，不是部署拓扑。
- 不用 MCP 替代 CI、Registry、Runner 和工厂内部 API。

---

## 13. 需要确认的架构决策

进入实现前只需确认以下 7 项：

1. 产品形态采用 **Protocol-neutral Core + Agent Action API + Operator API + Framework Pack + 可替换 Adapter**。
2. MCP、OpenCode Plugin、CLI/SDK 都只可能是过渡 Adapter；终局是第一方 Agent Runtime 和项目软件工厂控制面。
3. P0 不采用 Baseline 快照、Change 聚合和 SQLite。
4. 项目当前事实使用仓库内 Markdown；Git 管历史；Task 保存增量 proposal、状态和 Evidence。
5. P0 Framework Pack 采用声明式 Manifest；模板命令不直接暴露给模型。
6. P0 用 Electron 真实项目验证快速迭代主流程，只选择一个最短 Host Adapter；跨宿主和 MCP 不作为 P0 完成条件。
7. P0 先达到 Delivery Ready；commit、push、release、deploy 始终需要独立 Operator 授权。

确认这些架构决策不是发布授权。后续应先提交：

- Domain vocabulary；
- 状态/事件/失效矩阵；
- 4 类 API Schema；
- Framework Pack Manifest；
- P0 黑盒验收测试；

再开始搭建骨架。

---

## 14. 一手资料

- [Model Context Protocol 2026-07-28 Specification](https://modelcontextprotocol.io/specification/2026-07-28)
- [MCP Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- [MCP Transports](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports)
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [OpenCode MCP Servers](https://opencode.ai/v2/docs/mcp-servers)
- [OpenCode Plugins](https://opencode.ai/v2/docs/build/plugins)
- [OpenCode Skills](https://opencode.ai/v2/docs/skills)
- [OpenCode Permissions](https://opencode.ai/v2/docs/permissions)
- [Claude Code Features Overview](https://code.claude.com/docs/en/features-overview)
- [Claude Code MCP](https://code.claude.com/docs/en/mcp)
- [Claude Code Hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code Subagents](https://code.claude.com/docs/en/sub-agents)
- [Donchitos/Claude-Code-Game-Studios](https://github.com/Donchitos/Claude-Code-Game-Studios)
- [obra/superpowers](https://github.com/obra/superpowers)
- [affaan-m/ECC](https://github.com/affaan-m/ECC)
- [mattpocock/skills](https://github.com/mattpocock/skills)
- [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
- [OpenAI Harness Engineering](https://openai.com/index/harness-engineering/)
