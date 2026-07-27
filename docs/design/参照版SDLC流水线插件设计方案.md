# SDLC Pipeline OpenCode-first 架构真值

- 对应版本：`0.11.1`
- 状态：当前实现

## 定位

SDLC Pipeline 是项目交付状态机，不是通用 prompt/skill 工具箱。正式宿主只有 OpenCode。
设计目标是 evidence over claims：任何 agent 自述都不能替代 runner 产生的编译、进程、
health、artifact、测试和 Git 证据。

## 状态机

```text
uninitialized
  └─ init(pass)
      └─ spec(source/checkpoint/candidate)
          └─ explicit publish confirmation
              └─ published Feature Contract + atomic three-view bundle
                  └─ code(coder dispatch + diff/handoff valid)
                      └─ test(verify_delivery + all mandatory pass)
                          └─ candidate
                              └─ explicit finalize confirmation
                                  └─ closed version
```

init 与后续研发阶段始终位于同一个 OpenCode 项目会话。用户先创建空项目目录，从本仓库
raw 地址下载 `scripts/install_project.py` 并执行；该单文件入口自动 clone 指定 ref 的完整
发行内容后安装项目 adapter。安装器在写入 installation marker 前验证 template registry 与全部
rule policy，并把 `.opencode/**`、`.sdlc-pipeline/**` 合并进可识别的 Vitest/ESLint ignore
数组；无法安全合并的配置通过 `tooling_ignore.unresolved` 明确报告。随后在该目录执行无参数
`/sdlc-init`。命令先幂等检查 init evidence；
没有 lifecycle/scaffold 时返回 registry 元数据并以问答方式让用户选择，即使只有一个候选也不
自动选择。选定模板从 `templates/manifest.json` 解析 Git repository/ref，在临时目录
clone/checkout 后连同 Git 历史导入当前目录。后续直接执行
`/sdlc-spec → /sdlc-code → /sdlc-test`。

模板必须提供 lifecycle/scaffold 契约；`.opencode`、`opencode.json`、runner 和运行现场由插件
统一管理。已有项目已经具备 lifecycle/scaffold 时，`/sdlc-init` 直接执行首次验收或失败续跑。

## 模板资产边界

插件是流程与数据源适配器，不是模板资产包：

- 插件的 `templates/` 目录只允许保存 `manifest.json` 注册元数据；
- 模板源码、依赖、锁文件、文档、测试、lifecycle/scaffold 契约均由独立 Git 仓库维护；
- init 展示 `id/name/description/stacks/rules/capabilities` 并要求用户明确选择；
- 即使 registry 只有一个候选也不得静默选择；
- 导入报告记录 template ID、repository、请求 ref 和解析后的 commit SHA。
- init 把所选模板声明的规则写入 `.sdlc-pipeline/rules/active.json` 并记录 hash；规则目录只是
  catalogue，coder 只加载 active manifest，非 Java 模板不得加载 `java.md`。

当前参考模板为
[`sdlc-electron-scaffold`](https://github.com/Gandufu/sdlc-electron-scaffold)，本地维护目录是
`D:\sdlc-electron-scaffold`。它采用纯通用模板方案：删除 Heli、设备和会议业务，只保留安全
main/preload/typed IPC 示例、React 页面、测试和完整生命周期；打包工具单轨使用 Electron
Forge，不保留 electron-builder。

失败不会跳过门禁：

- init 缺少系统工具时生成 blocked report；
- spec 的“采用推荐”只保存 checkpoint，只有“确认发布”才原子发布 Feature Contract 和三视图；
- code 失败保留 diff、heartbeat、deadline、日志和运行现场，回到 code/spec；
- test 失败保存逐 T-id 结果，不创建 tag；
- finalize 没有明确确认、ready candidate 或完整 trace 时拒绝。

## OpenCode seam

项目级 plugin 的外部 interface 只有六个窄工具：

- `sdlc_status`：只读状态。
- `sdlc_ingest_source`：摄取 inline、项目内文件或显式授权复制的项目外文本来源。
- `sdlc_save_checkpoint`：保存可恢复的 spec 决策。
- `sdlc_publish_contract`：只发布用户明确确认的 Feature Contract。
- `sdlc_lifecycle`：只暴露 `init`、`verify_delivery` 两个意图。
- `sdlc_finalize`：确认后的版本固化。

plugin 是薄 adapter：转换 OpenCode 输入输出、注册正式 before/after hook、约束 task 目标。
所有状态、校验和副作用在 Python core 内。没有 experimental 消息注入、SessionStart 状态
灌入、Claude hook payload 模拟或 SubagentStop 恢复协议。

## 角色

`sdlc-main` 是 primary agent，负责用户交互和阶段编排，不创建额外会话。它只允许派发：

- `sdlc-coder`：实现当前 Feature Slice 与登记的 functional 文件，不启动项目或执行浏览器测试。
- 确定性 Core：在 test 阶段按当前指纹一次执行 `verify_delivery`。

只有一个 coder subagent，没有 executor 或固定 reviewer。coder 固定低温度与最多 8 个
agent steps；需求符合性由 trace 校验，
规范由编译/lint/static analysis，行为由测试计划验证。未来高风险人工 review 是可选策略，
不进入默认流水线。

## Python core

| Module | 隐藏的实现 | 对外 leverage |
|---|---|---|
| `feature_contracts` / `artifacts` | Feature Contract、schema、原子 bundle、固定 Markdown | 一次发布三视图 |
| `sources` | SourceEnvelope、anchor、受控外部复制、SHA-256 | 原始来源可追溯且不直接信任外部路径 |
| `trace` | scaffold hash、path、R/D/C/T、增量资格 | 一次判断漂移和影响 |
| `lifecycle` | argv、timeout、PID、health、log、artifact、tests | 一个 action 返回证据 |
| `runs` | active PID、日志、Token、恢复现场 | 状态跨 agent 保持 |
| `journal` | run/attempt/event、owner lease、deadline、heartbeat、熔断 | 断连后可判定 aborted，而不是遗留 running |
| `policies` | hard invariant 与 lifecycle verifier | lint/static analysis 不伪装成功能测试 |
| `memory` | 由 hash 约束的项目事实、决策和已解决失败 | 不保存聊天，不跨契约漂移复用 |
| `versions` | parent、manifest、commit、annotated tag | 一次确认完成固化 |
| `adapter` | progressive context、write guard、handoff/diff 一致性 | OpenCode hook 只传 role/output |

模块 interface 同时是测试 seam；不再为每个门禁维护一个浅脚本。

## Spec 与追溯

`/sdlc-spec` 同一会话生成一个模型编写的 Feature Contract；Core 将它原子投影为
requirements、design、test-plan 三份机器/Markdown 视图。校验规则：

- 交互设计明确派生自 [`mattpocock/skills`](https://github.com/mattpocock/skills)：保持技能小而
  可组合，事实从环境获取、决策交给用户，沿决策树一次只问一个问题，每问给推荐答案，达成
  共享理解前不发布；
- `grilling` 负责对齐，固定 spec 综合负责发布；本插件把二者编排在一个用户阶段，但以明确
  确认作为硬边界；
- “采用推荐”只记录选项、理由与 checkpoint；展示完整候选后，只有“确认发布”才调用
  `sdlc_publish_contract`；
- 每题由 OpenCode `question` 提供 2–3 个候选、推荐依据和自定义答案；共享术语、模块 seam 与
  测试 seam 在访谈中逐步收敛；
- command/agent/skill 只负责编排，Python Core 确定性生成统一风格的
  requirements/design/test-plan JSON 与 Markdown；

- Feature/验收 ID 使用 `F-xxxx`、`AC-xxxx`，投影视图中的 `R-xxxx`、`D-xxxx`、`T-xxxx`
  由 Core 确定性生成；
- SourceEnvelope 的 content、segment 与 anchor 绑定 SHA-256；
- 项目外文本文件默认拒绝，只有显式 `allow_external_copy=true` 才复制到
  `.sdlc-pipeline/runs/source-assets/`，单文件上限 10 MiB；
- 每个 R 至少映射一个 D 和一个 T；
- 每个 D 至少被一个 T 覆盖；
- design.extension_point 必须存在于 scaffold；
- design.allowed_paths 与 scaffold.allowed_paths 共同形成写入白名单；
- 常见 `vitest.config.*`、`eslint.config.*` 预登记为 tooling paths，允许作为非业务变更，
  但不计入 design-to-code 功能证据；
- 每个 T 指定 level、前置、输入、预期、mandatory 和 lifecycle command。

修改需求生成新 R-id，并以 supersedes 指向旧 R-id。原 ID 永不复用。

## Lifecycle

契约只保存 argv 数组，不保存 shell 字符串。环境准备优先级：

1. 项目 wrapper；
2. Corepack/packageManager；
3. 已安装系统工具；
4. 模板 lifecycle 已声明且 runner 白名单允许的自动系统安装。

init 的成功标准是 install、compile、start、health、artifact 全部通过，并完成 stop（除非模板
明确 keep running）。code 阶段不运行依赖项目启动的 functional 测试；coder 只实现业务代码和
登记的 functional 文件。handoff 后执行 compile/package 与 lint/typecheck policy 并绑定源码
指纹。test 阶段由主会话只调用一次
`verify_delivery`，Core 校验 code evidence 后执行 start → readiness → mandatory headless
functional tests → cleanup。

health 支持 process、HTTP、TCP、command 和 file；页面功能验证只由 functional T-id
通过真实无头浏览器执行，不把 HTTP 文本匹配伪装成浏览器测试。
以无 UI HTTP 页面探针实现；需要真实交互的模板把受控 integration 命令登记为 command。当前
Electron 模板的 integration 检查应启动打包后的真实窗口，并验证 preload bridge 与 typed IPC，
不能用 renderer HTTP 可达代替。

## Coder deadline 与可观测性

coder task-before hook 建立一个跨进程 journal attempt，owner 绑定 OpenCode PID，并设置独立
5 分钟 deadline。coder 的 edit/apply_patch 会通过单次 write-check 追加 `attempt.heartbeat`；
event JSONL 每次写入都 flush/fsync。正常 task-after 校验 handoff 后才把 attempt 置为
succeeded。owner 退出或 deadline 到期时，下一次 status 将 attempt 和 run 标为 aborted。

插件不能替调用者强制设置 OpenCode CLI 参数，也不能通过当前 hook API 硬杀正在运行的模型任务。
Headless 调用方应使用 `opencode run --format json` 实时消费宿主事件；journal 负责独立的项目内
持久证据和恢复判断。

## 标准与增量

默认 standard。incremental 必须同时满足：

- 父 manifest 完整；
- scaffold/lifecycle/key file 无漂移；
- 不改变公共接口、依赖、数据模型、安全、lifecycle、protected path；
- 用户确认使用增量。

增量复用未变化 R/D/T，只把影响集送给 coder；mandatory 回归仍由 Core 运行。任一条件失败
自动回到 standard。

## Token 与上下文

- spec 在一个主会话生成，不拆 requirement/design agent；
- 固定一个 coder subagent，无 executor/reviewer；
- context pack 是 progressive brief/resource manifest，只包含 ID、目标、验收、允许路径、
  tooling paths、资源路径、hash、tier 和读取理由；
- coder 先读 brief，只在实现需要时读取具体 resource，不预读全部源码或完整规则；
- 完整日志落盘，只返回失败尾部；
- OpenCode event 中可取得的 input/output/cache Token 按阶段累计；
- 重复读取字符数和 full-scan reason 进入 telemetry/manifest；
- Token telemetry 失败不阻塞交付门禁。

## 版本

通过测试产生 `Vxxxx` candidate。用户明确确认后 finalize：

1. 复核 candidate、mandatory tests、scaffold 和 R→D→C→T；
2. 生成 manifest；
3. 创建 `sdlc(Vxxxx): complete <summary>` 交付 commit；
4. 用一个小型 evidence commit 写入不可自引用的交付 SHA；
5. 创建指向 evidence commit 的 `sdlc/Vxxxx` annotated tag。

不自动 push。发布到远端仍由项目自己的 GitHub 流程负责。

## 不在当前范围

- Claude Code/Codex 功能等价 adapter；
- 通用 memory、持续学习、MCP 工具箱；
- 每个小任务一个 subagent；
- 默认双 review 或强制 brainstorm；
- 未声明的任意 shell 与系统安装。

若未来扩展宿主，只在稳定 Python core 外新增薄 adapter，不复制状态机实现。
