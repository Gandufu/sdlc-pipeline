# Agent Harness 与项目软件工厂技术调研（2026-07-30）

## 结论先行

本调研从目标出发：让不同模型和宿主能够安全、可观察、可验证地完成长周期软件工作，而不是为既有实现寻找依据。结论是：**SDLC Pipeline 2.0 应采用 Core-first、协议可插拔的架构；MCP Server 只是可选的过渡互操作适配器，不能成为领域内核、完整工作流、状态机或最终软件工厂的基础。**

建议的最小架构为：

```text
人 / CI / 任意智能体宿主
        │
        ▼
可替换接入层 ── 宿主插件 / MCP / CLI / SDK
        │
        ▼
协议中立的领域核心 ── 任务、证据、策略、版本化模板
        │
        ├── 代码库与 CI（权威知识和可重复验证）
        └── 软件工厂控制面与第一方智能体运行时（终局）
```

领域核心先定义有明确输入/输出、权限、幂等性和证据的智能体动作，以及独立的人工控制动作。持久状态、审批、异步作业和证据关联由领域核心定义，再按需映射为宿主工具、MCP tools/resources/prompts、CLI 或 SDK，不反向受制于某个宿主、某个插件或实验性扩展。

本文所有“已确认”都链接至一手资料（规范、官方文档、官方仓库/源码）。除特别注明外，访问日期均为 **2026-07-30**。标为“推断/建议”的内容是基于这些已确认事实作出的架构推导，不是上游规范要求。

## 研究边界与判定规则

- **不以现有方案为前提。** 现有 Change、Baseline、SQLite、已有 MCP 表面或宿主插件都不是既定协议；它们至多是后续迁移时需要审计的实现事实。
- **MCP 是互操作层，不是软件工厂的完整语义。** 它定义客户端/服务器怎样发现和调用能力，未替代需求治理、代码评审、测试策略、版本管理、证据保留和发布责任。
- **优先稳定核心，隔离可变边缘。** 当前 MCP 2026、OpenCode V2 beta、各宿主配置表面和社区项目都在快速演进；稳定领域核心与模板包必须不依赖它们的私有事件名或目录结构。
- **验证优先于“代理已完成”的自然语言声明。** 可接受的完成条件必须由独立可执行检查、原始输出和审阅责任共同组成。

## 一手资料核验

### 1. MCP：作为过渡适配器时的能力边界

| 主题 | 已确认事实 | 对 2.0 的含义 |
| --- | --- | --- |
| 协议主线 | [MCP 2026-07-28 规范](https://modelcontextprotocol.io/specification/2026-07-28)以 JSON-RPC 2.0 为基础；该版转向无状态、自包含请求和每请求 capability 协商。 | Server 不能依赖某一条长连接的隐含会话状态；每次调用应可由工作单元 ID、调用者身份、策略版本和输入重建授权判断。 |
| 工具 | [Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)规定 `tools/list`/`tools/call`、JSON Schema 输入；若声明 `outputSchema`，服务端必须返回符合它的 `structuredContent`。工具由模型控制，但规范仍建议人可拒绝。 | 将产生副作用或读取重要状态的工程动作做成窄而类型化的工具；工具结果必须输出机器可读状态和证据指针，而不只是 Markdown 叙述。 |
| 资源 | [Resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)提供 `resources/list`/`resources/read`、唯一 URI、文本或 base64 二进制，资源可随权限变化并带 TTL/cache scope/订阅。较早的[控制权说明](https://modelcontextprotocol.io/specification/2025-11-25)明确资源由应用决定怎样取用。 | 用资源公开工作单元摘要、模板目录、策略、证据索引和按锚点切分的规范；不把全量会话、整库文档或不可信记忆自动塞入模型上下文。 |
| 提示 | [Prompts](https://modelcontextprotocol.io/specification/2025-11-25/server/prompts)是带参数的消息模板；与模型控制的 tools 不同，它是用户控制的工作流入口。2026 仍保留 prompts 原语（[2026 总览](https://modelcontextprotocol.io/specification/2026-07-28)）。 | 模板接口可通过 prompts 提供“创建工作单元/审阅计划/交接/发布复核”等显式入口；模板本体仍是服务器管理的版本化工件，不能只藏在某宿主 slash command 中。 |
| 传输 | [Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)在 2026 移除了协议 session 和独立 GET stream；JSON-RPC 经 POST，要求协议 HTTP 元数据并要求校验 Origin。`stdio` 仍是官方标准传输（[transport 总览](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)）。 | 本地单用户/CI 首选 stdio，服务化或跨机才用 Streamable HTTP；本地 HTTP 仅绑定 loopback，远端必须有 TLS、Origin 校验、认证和资源隔离。不要设计一套依赖 SSE 长连的核心状态同步。 |
| 授权 | [Authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)将受保护 Server 视为 OAuth 2.1 Resource Server，要求 RFC 9728 Protected Resource Metadata 和 resource indicator/audience 约束；Dynamic Client Registration 已弃用，优先 Client ID Metadata 或预注册。 | 宿主 token 不能等同于工程权限。领域策略应将身份、仓库/工作区、工具动作和审批范围组合授权；远端部署再把 OAuth 当作传输层身份与委托机制。 |
| 人机补充 | [Elicitation](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation)可请求 form 或 URL；form 禁止请求密码、API key、token、支付凭据，客户端必须允许拒绝/取消，URL 必须完整展示并经同意。 | 对缺失的非敏感业务选择（目标环境、模板参数、是否继续）使用 elicitation；秘密和凭据只应由宿主/密钥管理系统注入，绝不让工具把它们当普通表单字段。 |
| Sampling | [Sampling](https://modelcontextprotocol.io/specification/2026-07-28/client/sampling)允许 server 经 client 请求 LLM，但该机制已弃用，新实现应直接连接 LLM provider，保留期至少 12 个月。 | 不以 server 发起 sampling 为核心编排机制。2.0 应服务于多个既有 Agent Host；若某业务确需内部模型调用，应是独立的、可审计的 provider adapter，而非 MCP 调用链的隐含递归。 |
| 长任务 | [Tasks extension](https://modelcontextprotocol.io/extensions/tasks/overview)是独立、实验性的扩展，不是 core；双端需协商 `io.modelcontextprotocol/tasks`，以 durable task ID、轮询和协作式取消表达 `working`/`input_required`/`completed` 等状态。 | 领域核心必须先拥有自己的可恢复作业/工作单元模型。可将其映射为 Tasks，**但不能要求客户或 SDK 已支持它，更不能让“任务扩展存在”成为正确性的唯一依据**。 |

#### SDK 核验

- **已确认：** [TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk/blob/main/README.md)当前 `main` 是 v2 stable，支持 2026-07-28；官方 [2026 支持迁移说明](https://ts.sdk.modelcontextprotocol.io/v2/migration/support-2026-07-28)说明 version negotiation 需要显式选用，且 v2 对旧 Tasks 仅保留废弃的互操作类型，入站 `tasks/*` 返回 `-32601`。因此 TypeScript v2 不能被假定为新 Tasks extension 的成熟实现。
- **已确认：** [Python SDK](https://github.com/modelcontextprotocol/python-sdk/blob/main/README.md)为 current stable，支持 2026-07-28 与旧版本，提供 tool/resource 装饰器及 stdio、Streamable HTTP、SSE；[官方教程目录](https://py.sdk.modelcontextprotocol.io/get-started/)列出 tools/resources/prompts、elicitation、多轮交互、sampling、authorization、transports、subscriptions/extensions。现有一手资料不足以确认它已提供新 Tasks extension 的稳定高阶 API。
- **推断/建议：** 若领域核心已有 Python，优先以 Python SDK 实现首个 Server，先覆盖稳定 primitives；若未来需要 Node/Bun 生态，再维持同一 JSON Schema 和黑盒契约测试的第二实现。不要因为某 SDK 的便捷装饰器而把领域模型绑死在 SDK 类型中。

### 2. Agent Host：可借鉴的是“分层和最小权限”，不是私有表面

#### OpenCode

- **已确认：** [MCP servers 文档](https://opencode.ai/docs/mcp-servers)支持本地和远端 MCP、OAuth、按 agent 启用/禁用 MCP 工具，并明确警告 MCP tool 会消耗上下文、过多 server 会超限。它还显示本地 server 的命令、cwd、环境变量和 tool-fetch timeout 都是宿主配置。
- **已确认：** [Agents](https://opencode.ai/docs/agents)提供 primary/subagent、Markdown frontmatter 配置和细粒度 permission；[Skills](https://opencode.ai/docs/skills)把 `SKILL.md` 作为按需加载的可复用指令，且可按 agent 控制；[Commands](https://opencode.ai/docs/commands)将 slash command 作为 prompt 文件；[Permissions](https://opencode.ai/docs/permissions)把 read/edit/bash/task/skill/MCP tool 等动作分为 `allow`/`ask`/`deny`。
- **已确认但需隔离：** [Plugins](https://opencode.ai/docs/plugins)可截获事件、添加自定义工具；[V2 Plugins](https://opencode.ai/v2/docs/build/plugins)明确标注为 beta，入口、hooks、draft shapes 和 config 可能变更。
- **可借鉴：** 仅为 OpenCode 写一个薄 adapter：安装/发现 MCP、把宿主权限提示映射到 Server 的明确拒绝或审批请求、把宿主日志关联到工作单元。按 agent 少量启用 MCP 工具，避免工具目录污染上下文。
- **不应照搬：** 不将 `.opencode` 目录、插件事件名、command frontmatter 或 V2 API 当成领域协议；不让插件 hook 推进不可逆业务状态。OpenCode 的 beta 表面尤其只能是替换层。

#### Claude Code / Claude Agent SDK

- **已确认：** [Claude Code subagents](https://code.claude.com/docs/en/sub-agents)为每个子代理提供独立上下文、系统提示、工具和权限；支持工作树隔离、MCP scope、hooks、预载 skills 与 persistent memory。文档特别说明子代理适合隔离搜索结果、日志等噪声，并警告并行写会带来冲突和协调成本。
- **已确认：** [Hooks](https://code.claude.com/docs/en/hooks)、[MCP](https://code.claude.com/docs/en/mcp)和[Skills](https://code.claude.com/docs/en/skills)分别是生命周期自动化、工具连接和可发现工作流指令；三者职责不同。
- **已确认：** 官方仓库 [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-typescript)称其为可编程使用 Claude Code 能力的 SDK；仓库明确“Claude Code SDK 已更名为 Claude Agent SDK”。
- **可借鉴：** 采用“主线程保存需求、决策和最终输出；子代理隔离调研/测试/日志；仅返回摘要”的上下文工程，以及 worktree 隔离的并行写策略。
- **不应照搬：** 不把 Claude 的 agent 文件、hook event、settings 或持久记忆格式定义为跨宿主标准；插件 subagent 有特定限制，证明宿主能力并不等于可移植能力。

#### Codex / OpenAI

- **已确认：** 官方 [Codex 长周期工作指南](https://learn.chatgpt.com/docs/long-running-work.md)要求目标包含 outcome、constraints、verification；不清楚时先计划；并建议并行写任务使用 worktree，避免多个 agent 写同一来源。
- **已确认：** 同一官方手册的 [subagent 说明](https://learn.chatgpt.com/docs/agent-configuration/subagents.md)将 context pollution/context rot 视为可靠性风险，推荐将调研、测试、日志分析放到独立子代理，只返回摘要；并行写操作要谨慎。
- **已确认：** [non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode.md)的 `codex exec --json` 可输出包括 tool calls、文件改动、plan updates、错误在内的 JSONL 事件流；默认只读，并支持明确 sandbox 配置。这是将执行记录接入 CI/证据收集器的可用宿主能力。
- **已确认：** OpenAI 的 [Harness engineering](https://openai.com/index/harness-engineering/)报告把仓库知识作为 system of record：短 `AGENTS.md` 作为目录，结构化 `docs/` 为深层权威；用 linters/CI 验证文档的更新、链接和结构，并以 doc-gardening 清理漂移。其结论是人类负责意图、优先级、验收，agent 执行。
- **已确认：** [Codex-maxxing for long-running work](https://cdn.openai.com/pdf/8a9f00cf-d379-4e20-b06f-dd7ba5196a11/OAI_WhitePaper_Codex-maxxing26.pdf)把“可验证的目标、约束、验收条件”列为长周期连续性的基础；[Codex Security](https://help.openai.com/en/articles/20001107-codex-security)展示了“识别 → 沙箱复现验证 → 最小修复 → 人审/PR → 修复后再验证”的闭环。
- **可借鉴：** 将目标、任务分解、设计、可执行验证和决策日志沉淀为仓库资产；每个长周期工作都有可观察状态与明确停止条件；用独立环境和新鲜上下文审阅构成闭环。
- **不应照搬：** 不把当前 Codex app/CLI 的 Goal、线程、JSONL event 名称或订阅机制写进领域核心；这些是良好的 adapter 输入，不是通用的软件工厂协议。

### 3. 社区项目：有价值的机制与不应复制的规模

| 项目（仓库身份已核验） | 已确认的可借鉴机制 | 不应照搬的部分 |
| --- | --- | --- |
| [Donchitos/Claude-Code-Game-Studios](https://github.com/Donchitos/Claude-Code-Game-Studios) | README 当前声明 49 agents、73 skills、12 hooks，且有纵向委派、横向咨询、领域边界、升级路径和质量 gate；也强调 Ask → options → draft 的人保持控制流程。可借鉴“角色以责任边界和交接条件定义”及审计 trail。 | 这是面向游戏开发的 Claude Code 配置包，不是通用执行内核。大规模角色/命令目录会增加发现、上下文和维护成本；不要将 49 个角色、游戏域词汇或 hook 脚本当成软件工厂的必需拓扑。 |
| [obra/superpowers](https://github.com/obra/superpowers) | 它以设计确认 → 计划 → worktree → TDD → 子代理实现/两阶段审阅 → 收尾为基本链路，并把“evidence over claims”作为原则；发布说明还表明它测试 skill 的触发和端到端行为。可借鉴小步反馈、红绿重构、规格审阅与代码审阅分离。 | 它是跨 harness 的方法/skills 包，不是 MCP Server。技能描述能否被模型触发并非确定性机制，且跨宿主实现不同；将关键审批、权限和发布只托付给提示文本是反模式。 |
| [affaan-m/ECC](https://github.com/affaan-m/ECC) | **身份更正：** 用户提到的 `affaan-m/everything-claude-code` 当前重定向/对应的官方源仓库是 `affaan-m/ECC`，README 将其称为 agent harness operating system，而不是仅“ECC 配置包”。它主张 plan → test → implement → fresh-context review → verify → remember → improve，并区分 skills、agents、hooks；Memory Vault 文档还明确 memory 是未审阅上下文，重要结论须回查权威来源，不能把 memory 当可执行策略。可借鉴可检查的 memory/hand-off、可选 MCP、fresh-context review 和工具目录节制。 | README 同时暴露大量 agents/skills/commands、多个 harness adapter、可选 SQLite/observer 等。其本身也提醒不要双重安装、不要自动启用所有 MCP。2.0 不应复制其安装矩阵、目录树、默认 connector、状态存储或“持续学习”主张；先证明每一个能力的安全性、成本和可验证性。 |
| [mattpocock/skills](https://github.com/mattpocock/skills) | README 将技能定位为小、可组合、可改造的工程纪律；强调共享语言/ADR 减少语义歧义，红绿重构、诊断循环、纵向小切片和“反馈率是速度上限”。其 `research`、`tdd`、`code-review` 是清晰的工作流分工。 | 这是方法库，不是强制运行时。不能仅因装入 SKILL.md 就认为动作已执行；需要由工具输出、CI 与交接契约证明。 |
| [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | **身份已确认：** 这正是 `NousResearch/hermes-agent`。README 声称具备技能自建/改进、会话搜索、隔离子代理、RPC 脚本和多后端；并列出 MCP、skills、memory、security 文档。可借鉴“可移植工具网关/后端”和“记忆须显式检索”的方向。 | 自我改进、长期用户模型和跨消息平台会大幅扩大权限、注入、隐私和可重复性风险。软件工厂核心不应自动把经验升格为规则或技能；每次提升为模板/策略都要走评审、版本、测试和回滚。 |

## 独立推导：2.0 应建立的可移植契约

以下是设计建议，并非任一上游项目要求。

### A. 以“工作单元”而不是“会话”作为长周期边界

工作单元应能跨模型、跨宿主、跨中断恢复；至少包含：目标与验收条件、范围/权限、输入来源及版本、决策、当前阶段、允许的下一步、失败/停止原因、验证计划、证据清单和责任人/调用者。这些是领域语义，储存实现可替换；不预设 SQLite、目录布局或 MCP Tasks。

每个工作单元状态转移应由核心验证，而非由模型口头声明或宿主 hook 隐式推进。长运行工具应立刻返回一个可查询引用，任务完成后可复读相同引用得到状态、原始证据和下一步；如果客户端协商了 MCP Tasks，可增加 Tasks 映射，但状态真相仍在核心。

### B. 先建立协议中立接口，再按需映射 MCP

1. **查询与发现接口**：模板目录、策略版本、仓库地图、工作单元摘要、输入锚点、证据索引、失败诊断。必须可分页/按锚点读取；在 MCP 中可映射为 resources 与只读 tools。
2. **智能体动作接口**：创建/更新工作单元、获取候选模板、启动可恢复执行、记录验证、请求交接。每个动作的 input/output JSON Schema 是正式契约；输出含 `status`、`next_actions`、`evidence_refs`、`policy_version` 和稳定错误码；在 MCP 中映射为 tools。
3. **人工控制接口**：批准、拒绝、取消、接管、风险例外和发布决定。该接口与模型动作分开授权、分开审计；可由门户、CLI 或宿主交互层调用，不要求经由 MCP。
4. **用户启动的模板入口**：用于把自然语言需求转成结构化候选、规划审阅、交接和验收复核；可表现为 MCP prompts、slash commands、skills 或平台表单，但改变状态仍必须调用受控接口。

**避免：** `run_everything`、`advance_phase` 这类把规划、写代码、测试、审批、发布混在一个黑盒 tool 的接口。它们无法明确权限、幂等/恢复边界和失败证据，也无法在不同宿主保留人类控制。

### C. 模板应是产品化接口，而非宿主提示的副本

一个模板包至少应有：稳定模板 ID 与版本、参数 JSON Schema、可读说明、阶段/停止条件、要求的工具和最小权限、输入/输出工件类型、可执行验证清单，以及兼容矩阵。模板正文和长规格放在可审查 Markdown；索引只保留 ID、版本、摘要、hash 和引用，避免将大型对话塞进 JSON。

模板升级应先产生候选，再经过明确人审并留下版本/证据绑定。这样不同 host 可以把同一模板表现为 MCP prompt、slash command、skill 或 CI 参数，但核心模板不会随任一表现层漂移。

### D. 宿主适配器只负责“翻译”，不拥有生命周期真相

适配器允许做：启动/发现 MCP、映射当前工作区和身份、显示审批/elicitation、把 tool 调用和 JSONL/日志关联到工作单元、调用宿主的 sandbox/worktree/子代理能力、渲染结果。

适配器不应做：绕过 Server 直接改状态、以 hook 自动批准、把宿主会话 ID 当成业务 ID、把私有事件格式持久化为领域证据、或把 host 的记忆直接提升为项目政策。若适配器离线，人工/CI 仍能通过 Server API 查询工作单元、复验产物和恢复受控执行。

### E. 用“证据闭环”定义完成，而不是更多角色

每个变更至少连接下列可检验关系：

```text
验收条件 → 计划/设计决定 → 改动集合 → 独立验证命令与原始输出
        ↘ 风险/例外 → 人工决定、权限与时间 → 复验/发布判断
```

执行循环采用：发现/复现 → 最小可验证切片 → 实施 → 运行静态检查、单测和功能验证 → 新鲜上下文审阅 → 修复发现 → 再验证 → 人工决定是否交付。证据需记录命令、退出码、输入版本、环境摘要、输出位置/哈希和执行时间；失败/超时也是证据，不能被后续“绿色”结果覆盖。

### F. 渐进的软件工厂路线

| 阶段 | 目标 | 首要交付 | 不做什么 |
| --- | --- | --- | --- |
| 0：核心闭环探针 | 证明领域契约与快速迭代闭环可行 | 协议中立动作接口、参考适配器、一个最短宿主适配器、契约测试 | 不建设平台；MCP 只做限时可选兼容探针。 |
| 1：可验证工作单元 | 让一次变更可恢复、可审计 | 核心状态/证据模型、计划与验证工具、CI/本地复验 | 不自动发布，不依赖单一宿主 hook。 |
| 2：模板产品化 | 让批准的流程跨宿主复用 | 版本化模板包、参数 schema、prompt/skill/command adapters | 不复制所有社区角色和命令。 |
| 3：有限并行 | 提高读密集与独立切片的吞吐 | worktree/隔离执行、明确输入输出交接、冲突检测 | 不让多个写代理修改同一 checkout。 |
| 4：受控工厂 | 在证据闭环成熟后扩大自治 | 风险分级、权限升级、人审队列、度量与回归评估 | 不将自动学习或记忆直接变为生产规则。 |

## 明确反模式与设计约束

- **反模式：把 MCP 当作万能状态机。** 约束：MCP 负责能力互操作；工作单元、审批、恢复、证据和审计由核心定义。
- **反模式：预设实验 Tasks/已弃用 Sampling 可用。** 约束：Tasks 是 optional experimental；Sampling 已弃用；所有核心路径必须有普通 tool + resource 查询回退。
- **反模式：把所有工具、文档、规则和记忆灌入上下文。** 约束：短入口 + 索引 + 按需资源读取；按角色/任务启用最少工具；对上下文大小和新鲜度设预算。
- **反模式：巨型 AGENTS.md 或巨型提示词是唯一知识库。** 约束：短导航文件，版本化 docs/、ADR、模板、验收和证据作为权威；以 CI 检查链接、结构、所有者和陈旧性。
- **反模式：角色数量代替可靠性。** 约束：每个角色必须有明确输入、允许工具、输出、停止条件和验证责任；没有测量收益的角色/skill 不进入默认目录。
- **反模式：hook 既监控又决定。** 约束：hook 可做日志、提醒、格式/安全前置检查；不可静默审批、隐式推进或吞没失败。关键判断必须能由核心重新计算。
- **反模式：记忆就是事实或策略。** 约束：记忆只是待核验线索；升级为模板、规则、架构决定前，必须人审、版本化、测试并可回滚。
- **反模式：并行写同一工作树。** 约束：读工作可并行；写工作按 worktree/租约隔离，合并前以独立验证和冲突审查收敛。
- **反模式：把“模型说完成”当完成。** 约束：完成需要可重复验证、原始证据、新鲜审阅和明确的人工发布/例外决定。

## 下一步：进入设计前必须回答的问题

1. 工作单元的最小状态、失败语义、幂等键和恢复边界分别是什么？哪些必须由人批准？
2. 第一版真正需要的 3–5 个智能体动作与人工控制动作是什么？每个动作的副作用、权限、输入/输出 schema、证据和取消语义是什么？若做 MCP 兼容探针，再决定它们怎样映射为 tools/resources。
3. P0 选择哪个最短宿主适配器验证闭环？若额外验证 MCP，本地 stdio、远端 Streamable HTTP 只选择哪一种，并明确暂不支持什么？
4. 模板包的所有权、兼容策略、升级/回滚和验证 harness 如何定义？
5. 哪些验证是权威 gate，哪些只是观察/建议？失败、超时、人工阻塞怎样保留并呈现？
6. 哪些 host-specific 能力（OpenCode hook、Claude worktree、Codex JSONL）只作为加速适配，而不会改变正确性？

只有这些问题经设计审阅后，才应进入实现选择（存储、具体 state schema、首个宿主适配器、可选 MCP SDK、插件目录和迁移方案）。

## 来源索引

### 规范与 SDK

- [MCP Specification 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28)
- [MCP Tools 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- [MCP Resources 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)
- [MCP Streamable HTTP 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)
- [MCP Authorization 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
- [MCP Elicitation 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation)
- [MCP Sampling 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/client/sampling)
- [MCP Tasks extension](https://modelcontextprotocol.io/extensions/tasks/overview)
- [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

### 宿主与软件工厂资料

- [OpenCode official docs](https://opencode.ai/docs/)
- [Claude Code official docs](https://code.claude.com/docs/en/)
- [Claude Agent SDK official repository](https://github.com/anthropics/claude-agent-sdk-typescript)
- [Codex manual: long-running work](https://learn.chatgpt.com/docs/long-running-work.md)
- [OpenAI: Harness engineering](https://openai.com/index/harness-engineering/)
- [OpenAI: Codex-maxxing for long-running work](https://openai.com/index/codex-maxxing-long-running-work/)
- [OpenAI: Codex Security](https://help.openai.com/en/articles/20001107-codex-security)

### 社区项目的官方仓库

- [Donchitos/Claude-Code-Game-Studios](https://github.com/Donchitos/Claude-Code-Game-Studios)
- [obra/superpowers](https://github.com/obra/superpowers)
- [affaan-m/ECC](https://github.com/affaan-m/ECC)
- [mattpocock/skills](https://github.com/mattpocock/skills)
- [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
