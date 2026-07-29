# Changelog

## Unreleased

- 修复 lifecycle Schema 的 `minProperties` 与 fail-closed 运行时校验器不一致，避免 v1.1
  测试套件项目在 init 读取合约时被错误阻断。
- coder 退出所有测试源码读写；code gate 在 handoff 后统一完成 compile/package/lint/typecheck、
  启动、readiness 和停止。
- `sdlc-tester` 成为唯一测试编写入口，仅可修改 Spec selector 声明的 `tests/**`/`test/**`
  Playwright 脚本；业务源码与测试源码分别绑定指纹，测试编写不会使 code gate 失效。
- `sdlc-tester` 从 primary 阶段入口改为由 `sdlc-main` 派发的独立 subagent；tester 只返回
  test handoff，plugin 校验后再由 Core 执行唯一 `verify_delivery`。
- Playwright package/CLI 是确定性交付验证路径；Playwright MCP 保持可选且不进入 gate 依赖。

## 0.15.4 - 2026-07-28

### Fixed

- 将多 Requirement coder deadline 的增量从每项 1 分钟调整为 2 分钟，仍上限 15 分钟；真实 6 Requirement 设备管理任务在 10 分钟内持续有进度但未能交付 handoff，现获得完整的有界预算。

## 0.15.3 - 2026-07-28

### Fixed

- 审批工具在调用 Core 前拒绝不完整的 `candidate_id`、`content_hash` 或 `confirmed=true`，避免 OpenCode 漏参将 Spec Run 熔断为 `BLOCKED`。
- Core 对 Spec 审批请求在创建 journal 尝试前做结构校验，错误参数不再污染生命周期状态。

## 0.15.2 - 2026-07-28

- coder dispatch 的 deadline 改由 Core 按已发布 Requirement 数确定性派生：基础 5 分钟、每个额外
  Requirement 增加 1 分钟，最多 15 分钟；journal、host timer 和 coder prompt 绑定同一个值。
- 补充 6 个 Requirement 的 Core/host 回归，防止固定 300 秒取消已经开始真实交付的单一 coder。

## 0.15.1 - 2026-07-28

- 删除泛化 OpenCode 回归 runner 及其测试、文档和临时项目。真实验收只在目标功能项目中执行，
  并按阶段审查原始 JSONL、journal、Git diff、规则和 Markdown/JSON 产物。
- 强化 `/sdlc-init` 和 `sdlc-main` 的跨消息边界：没有合同的新项目必须先展示模板并停止，只有
  后续明确的用户选择才可执行 init，单一候选、命令参数和模型推断均不能替代确认。

## 0.15.0 - 2026-07-28

- 不兼容升级到 Storage Layout v3；删除旧 `runs`、内层 `.opencode`、Schema v2 目录、bundle 与
  current mirror，不提供旧现场迁移。
- 新增 Store Module：JSON 仅保存 compact 索引、ID、状态、引用和 hash；会话、Candidate、结果、
  handoff、错误与证据正文改为 Markdown structured record，并在读取时校验 content hash。
- Source 正文只保存一次，Candidate revision 只引用独立 Markdown artifact；批准后发布自包含的
  `docs/sdlc/baselines/<id>`，删除 `work/` 后仍可加载正式 Spec。
- 安装目录统一为 `runtime/contracts/state/work/evidence`，强制升级删除所有旧受管目录和 schema；
  init 不再提前创建 `docs/sdlc`。

## 0.14.16 - 2026-07-28

- 修复 Schema v2 分片的可选 `R/D/T id` 仍会把 Agent 的语义名直接送入正则校验的问题。
  非规范或遗漏的 ID 现在统一由 Core 分配规范序号，保留用户/模型无需为 ID 格式重试的契约。

## 0.14.15 - 2026-07-28

- 修复 CLI `source-query` 已在 Core dispatch 支持、却遗漏 argparse operation 白名单的问题；
  `sdlc_query_source` 现在可按 receipt anchor 正常读取受限原文，不会在真实 spec 阶段静默报 CLI 参数错误。

## 0.14.14 - 2026-07-28

- 修复 `sdlc_ingest_source` 的 file 参数歧义：当调用方将路径填入兼容 `source` 字段而非 `uri` 时，
  插件与 Core 会将其规范化为 file URI，再执行既有的外部复制、大小和 hash 门禁；不再因同一可恢复
  输入错误触发 journal 熔断。

## 0.14.13 - 2026-07-28

- 修复大外部来源摄取后将完整 SourceEnvelope 回传给 Agent 的问题：现在只返回有界 receipt（来源 ID、
  分段 anchor、长度、短预览与 hash），正文必须经 `sdlc_query_source` 按段读取。
- 未提供分段的文本来源会自动按 8,000 字符、优先行边界生成可查询 anchor，避免 OpenCode 工具输出截断后
  触发大记录 grep 或回读外部路径。

## 0.14.12 - 2026-07-28

- 修复 `/sdlc-spec <需求或确认文本>` 未将 OpenCode 命令参数注入模板的问题；现在参数通过
  `$ARGUMENTS` 进入受边界约束的用户输入区，避免真实 CLI 流程静默丢失需求或审批确认。
- 新增安装包命令模板回归断言，防止后续移除 `$ARGUMENTS`。

## 0.14.11 - 2026-07-28

- 将 TypeScript hard invariant（`: any`、`as any`、`<any>`）提升到 coder 的
  常驻指令与 context pack，并明确只实现确认的 R/D/T/AC、不得为臆造的无效输入测试使用类型逃逸。

## 0.14.10 - 2026-07-28

- 修复 Spec 将 skill base 误当为项目 reference 路径，以及 `/sdlc-code` 在 code gate 后擅自调用 test 专属
  `verify_delivery`。Spec 指引现固定为项目内 `.sdlc-pipeline/references/spec-interview.md`；code
  command 与主 agent 明确在 code gate 后停止，任何 test lifecycle 仅可由用户随后 `/sdlc-test`
  启动的 `sdlc-tester` 执行。

## 0.14.9 - 2026-07-28

- Core 现在像
  R/AC 一样分配 Feature ID：保留规范 `F-xxxx`，其余缺失或语义 hint 统一分配下一个 `F-xxxx`，避免
  模型格式猜测产生可恢复但不应存在的错误。

## 0.14.7 - 2026-07-28

- 修复真实 spec 写入中 Design 可能猜测非脚手架 extension point、随后被 Candidate 校验拒绝的问题。
  spec reference、主会话与 Design 工具均要求在写入前读取 `scaffold.json`，并逐字使用已声明的
  `extension_points` ID；Core 继续保留未知 ID 拒绝。
- 对齐 README 的 coder 预算为实际 `steps: 16`；Schema v2 ADR 重编号为 ADR-0003。
- plugin 可用 `SDLC_PYTHON` 或 `PYTHON` 指定 Python；未指定时 Windows 用 `python`、其他平台优先
  `python3`。CLI 现为所有 `Exception` 产生含 `error_type` 的结构化 JSON。
- 补充宿主 adapter 可移植边界与团队运行规范；保留 task 参数 `command` 的防御性清理。

## 0.14.6 - 2026-07-28

- 修复 checkpoint 的 `source_refs` 与其他 OpenCode Spec 工具形态不一致造成的中间错误：Core 在
  schema 校验前无损将 `{source_id, anchor}` 规范化为持久化的 `SRC-...#anchor` 字符串，仍拒绝
  其他未知或畸形字段；指引同时说明两种可接受输入。

## 0.14.5 - 2026-07-28

- 修复真实 OpenCode spec 回归中 checkpoint 工具因模型猜测 `stage/decisions/notes` 字段而失败的问题。
  主会话、spec reference 与工具描述现在给出相同的 schema payload、`Q-xxxx` ID 与 `resolved`
  状态约束；Core 仍严格拒绝未知字段，避免静默丢失决策。

## 0.14.4 - 2026-07-28

- 修复 Schema v2 spec 写入会把 agent 提供的无效 AC id 直接送入 schema 校验的问题：AC id
  现在始终由 Core 按 Requirement 和顺序派生，避免可恢复的中间错误污染 Run。
- 修复 unit/integration 等没有 `allow_selector` 的 lifecycle test key 接收 selector 后产生
  路径错误和 candidate 校验错误的问题：Core 在持久化前规范化为 `null`；functional 仍严格要求
  `tests/` 下的项目内相对 selector。
- 补充 spec 主会话和澄清规则，明确 AC/selector 的责任边界，并以回归测试覆盖错误规范化与
  functional 路径防护。

## 0.14.3 - 2026-07-28

- evidence collector 除最近 attempt 外，新增全 Run 的失败分组、次数和首末 attempt，避免长流程将
  早期错误静默挤出诊断报告；最终门禁通过不再掩盖中间失败。

## 0.14.2 - 2026-07-28

- 修复 coder 在 8 个 tool step 内只完成全量预读、尚未写入即结束的空交付：manifest 提供首个
  R/D/T 纵向切片，coder 必须在第 4 次工具调用前写入，并将预算提高到 16 steps。
- task hook 不再伪造全量 Schema command；只将主代理的短任务目标附加到唯一 context manifest，
  防止具体 Feature Slice 丢失或上下文重复。

## 0.14.1 - 2026-07-28

- coder handoff 必须包含由 Core 派生的非空业务改动，避免空交付触发 code gate 假绿。
- deadline 先持久化 `task-cancel` 再中止会话，并公开 CLI `task-cancel` operation，避免遗留 running attempt。
- `/sdlc-test` 使用无 task 权限的 `sdlc-tester`，只允许调用一次 `verify_delivery`，不能重入 code 阶段。

## 0.14.0 - 2026-07-28

- 将单体 Feature Contract 主流程升级为 Schema v2 Candidate：Feature Map、Requirement、
  Design、Verification 分片保存，每次修改生成不可变 revision。
- 增加受控项目内相对 `$ref`、跨 artifact R/D/T/AC 校验、preview 与稳定 content hash；
  网络、绝对路径和越出 schema root 的引用全部拒绝。
- OpenCode 改用结构化 begin/put/validate/approve 工具；审批只提交 candidate ID、hash 和
  `confirmed`，不再重新传输完整 JSON。
- 批准后原子发布只包含分片 artifact 的 v2 bundle 和派生导航 index；status 支持从磁盘
  恢复 draft/ready/published Candidate。
- 实际代码映射后移到 code/test 之后，由 Core 根据 Git diff、extension point 和测试结果
  生成带 `direct/scoped/shared` 精度的 Delivery Trace。
- spec bundle pointer/manifest 与 version manifest 升级为 `schema_version: 2.0`。
- 安装器递归校验全部 Schema 和本地引用；补充 v2 回归、ADR 与社区调研文档。
- 删除 Feature Contract schema/module、`sdlc_publish_contract` 和聚合
  requirements/design/test-plan 产物；本版本不提供 Spec v1 兼容路径。

## 0.13.0 - 2026-07-28

- coder 固定低温度与 8 个 agent steps，deadline 收紧为 5 分钟；task hook 覆盖为唯一最小
  context prompt，不再叠加主 agent 展开的长上下文。
- context manifest 限制为 10 个资源、最多 6 个业务实现候选，并排除 Core 源码。
- code 阶段不再向 coder 暴露依赖项目启动的 functional focused check；浏览器验证只由
  test 阶段的 start/readiness/functional/cleanup 链执行。
- Hook 写入边界合并为单次 `write-check`，新增 dispatch/first-write/deadline/completed
  结构化事件；状态机与证据仍由确定性 Core 管理。
- 相同 test key 与 selector 只执行一次，再将结果映射回多个 T-id。

## 0.12.1 - 2026-07-28

- 清理模板 registry 与活动设计文档中遗留的旧测试术语，统一为 headless functional。

## 0.12.0 - 2026-07-28

- 安装复制排除 `.opencode/node_modules`，并在模板导入后的 init 再次强制合并
  Vitest/ESLint tooling ignore。
- focused check 改为 T-id 与受控文件 selector，成功和失败均按源码/spec 指纹复用。
- code gate 负责 compile/package 与 lint/typecheck policy；test gate 只执行
  start、readiness、无头浏览器 functional case 和 cleanup。
- 删除活动 E2E/installer 测试契约，新增 Playwright functional 文件约定。
- Python 与 OpenCode adapter 改为异步、可取消的进程树执行；deadline 会 abort session
  并清理子进程。
- `result.ok=false` 在 journal 中记录为 failed；新增 source anchor query 窄接口。

## 0.11.1 - 2026-07-27

- 安装后校验 template registry 与 rule policy，修复 React policy/schema 漂移。
- 自动合并 Vitest/ESLint 插件目录 ignore，并预登记 tooling config 非业务变更路径。
- 支持显式授权的项目外文本来源 copy + SHA-256 SourceEnvelope 摄取。
- coder dispatch 增加独立 deadline、PID lease、heartbeat 和 status 自动 aborted 回收。
- 将“采用推荐”checkpoint 与“确认发布”授权拆成两个明确交互。
- 同步 OpenCode-first 架构设计真值到 0.11.1 的状态机、工具边界与验证语义。

## 0.11.0 - 2026-07-27

- Context pack 改为 progressive brief/resource manifest，不再嵌入源码和完整规则。
- 增加受控 `focused_check`，让 coder 自主选择 Feature Contract 测试键。
- 增加 hash 失效的 Delivery Memory，只派生项目事实、确认决策和已解决失败指纹。
- OpenCode lifecycle Interface 收窄为 init/focused_check/verify_delivery 三个交付意图。
- 提示词以 skill/reference 为单一真值，agent 和 command 只保留权限与阶段路由。
- 将提问数和主流程长度从绝对硬规则下调为可解释 guidance。

## 0.10.0 - 2026-07-27

- 以单功能 Feature Contract 作为唯一模型规格输入，Core 原子投影三类文档。
- 删除 executor 和插件内所谓 E2E，收敛为唯一 coder 与一次 `verify_delivery`。
- 拆分 source/checkpoint/contract 窄工具，移除模型可控 idempotency key。
- Git diff 自动生成代码与测试追溯映射；增加失败分类、重复失败熔断和交付证据缓存。
- 升级安装时删除遗留 `sdlc-executor.md`。

## 0.9.0 - 2026-07-27

- 修复 dirty worktree fingerprint baseline、真实路径映射与 Windows PID identity，避免重试误判和 PID 复用误杀。
- 增加不可变 spec bundle、原子 current pointer、正式 Draft 2020 Schema runtime validator。
- 增加 durable Run Journal：run/phase/step/attempt/event/idempotency、spec grilling checkpoint 与 abandoned attempt 恢复。
- 将 TypeScript、Electron、React 关键规则升级为 machine policy 和受控 lifecycle verifier。
- 增加 SourceEnvelope、原文 anchor、AC-id 与 R/D/T/文件/测试机器 evidence edge。
- 强制 OpenCode adapter 与 Python core 使用 UTF-8，修复 Windows 中文 checkpoint 传输。

## 0.8.3 - 2026-07-27

- init 根据模板 `rules` 显式生成 active rules manifest，status、AGENTS 与 context pack 只暴露
  当前框架规则，不加载无关 Java/Spring/Vue 规则。
- 恢复源自 `mattpocock/skills` 的 grilling 契约：事实先查、决策归用户、一次一问、推荐答案、
  共享理解确认后才发布。
- 增加 spec interview/reference，command、agent、skill 与 README/设计文档统一引用；设计与测试
  Markdown 继续由 Python core 按固定章节原子渲染。

## 0.7.0 - 2026-07-25

- spec 增加原始输入、结构化分析与发布前人工确认门禁。
- code 在 coder 派发和 compile/restart 两层拒绝未解决的 blocking 问题。
- requirements Markdown 与版本交付摘要改为 runner 固定渲染。
- context pack 以 hash 投影原始长需求，减少 coder/executor 重复 Token。
- 补充 Schema、门禁、渲染、Token/context-pack 与完整版本闭环回归测试。

## 0.6.1 - 2026-07-25

- 项目 adapter 安装改为可从 GitHub raw 地址下载单文件 installer 后直接执行。
- 单文件 installer 自动拉取指定仓库/ref 的完整发行内容，避免要求用户预先设置
  `SDLC_PIPELINE_ROOT` 或 clone 本插件仓库。

## 0.6.0 - 2026-07-25

- `/sdlc-init` 改为始终在当前项目目录执行，移除 repo/ref/target 跨目录 bootstrap。
- 新项目支持内置模板或携带 lifecycle/scaffold 契约的 GitHub 模板；GitHub 模板保留 Git 历史。
- 内置模板建立 Git 基线，确保后续版本 manifest 有可追溯的起点。
- 更新命令、README、架构真值与回归测试；同步修复两个内置模板的 scaffold hash。

## 0.5.0 - 2026-07-25

- 正式收敛为 OpenCode-only，兼容 OpenCode 桌面版项目发现。
- 固定一个 primary agent 和 coder/executor 两个 subagent。
- 合并 requirement/design 为 `/sdlc-spec`，保留三份独立产物。
- status/finalize 改为内部工具。
- 引入 lifecycle/scaffold 契约、R/D/C/T、固定渲染、Token 和 Vxxxx manifest。
- code 强制真实 compile/restart/health/artifact，test 强制逐 T-id runner 证据。
- 删除 Claude/Codex active manifests、hook 模拟、experimental 注入和旧浅脚本。
