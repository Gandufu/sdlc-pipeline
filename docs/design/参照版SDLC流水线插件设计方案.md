# SDLC Pipeline OpenCode-first 架构真值

- 对应版本：`0.8.3`
- 状态：当前实现

## 定位

SDLC Pipeline 是项目交付状态机，不是通用 prompt/skill 工具箱。正式宿主只有 OpenCode。
设计目标是 evidence over claims：任何 agent 自述都不能替代 runner 产生的编译、进程、
health、artifact、测试和 Git 证据。

## 状态机

```text
uninitialized
  └─ init(pass)
      └─ spec(R→D→T valid)
          └─ code(diff valid + compile/restart/verify pass)
              └─ test(all mandatory pass)
                  └─ candidate
                      └─ explicit confirmation
                          └─ closed version
```

init 与后续研发阶段始终位于同一个 OpenCode 项目会话。用户先创建空项目目录，从本仓库
raw 地址下载 `scripts/install_project.py` 并执行；该单文件入口自动 clone 指定 ref 的完整
发行内容后安装项目 adapter。随后在该目录执行无参数 `/sdlc-init`。命令先幂等检查 init evidence；
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
  catalogue，coder/executor 只加载 active manifest，非 Java 模板不得加载 `java.md`。

当前参考模板为
[`sdlc-electron-scaffold`](https://github.com/Gandufu/sdlc-electron-scaffold)，本地维护目录是
`D:\sdlc-electron-scaffold`。它采用纯通用模板方案：删除 Heli、设备和会议业务，只保留安全
main/preload/typed IPC 示例、React 页面、测试和完整生命周期；打包工具单轨使用 Electron
Forge，不保留 electron-builder。

失败不会跳过门禁：

- init 缺少系统工具时生成 blocked report；
- spec 发布前整体校验，三份产物不会出现半完成状态；
- code 失败保留 diff、日志和运行现场，回到 code/spec；
- test 失败保存逐 T-id 结果，不创建 tag；
- finalize 没有明确确认、ready candidate 或完整 trace 时拒绝。

## OpenCode seam

项目级 plugin 的外部 interface 只有四个工具：

- `sdlc_status`：只读状态。
- `sdlc_publish`：发布 spec 或 Token telemetry。
- `sdlc_lifecycle`：环境、依赖、进程、验证和测试。
- `sdlc_finalize`：确认后的版本固化。

plugin 是薄 adapter：转换 OpenCode 输入输出、注册正式 before/after hook、约束 task 目标。
所有状态、校验和副作用在 Python core 内。没有 experimental 消息注入、SessionStart 状态
灌入、Claude hook payload 模拟或 SubagentStop 恢复协议。

## 角色

`sdlc-main` 是 primary agent，负责用户交互和阶段编排，不创建额外会话。它只允许派发：

- `sdlc-coder`：实现 D→C 与 T→测试文件。
- `sdlc-executor`：独立按 T-id 运行测试。

没有固定 reviewer。需求符合性由 trace 校验，规范由编译/lint/static analysis，行为由
测试计划验证。未来高风险人工 review 是可选策略，不进入默认流水线。

## Python core

| Module | 隐藏的实现 | 对外 leverage |
|---|---|---|
| `artifacts` | schema、唯一 ID、原子写、固定 Markdown | 一次发布完整 spec |
| `trace` | scaffold hash、path、R/D/C/T、增量资格 | 一次判断漂移和影响 |
| `lifecycle` | argv、timeout、PID、health、log、artifact、tests | 一个 action 返回证据 |
| `runs` | active PID、日志、Token、恢复现场 | 状态跨 agent 保持 |
| `versions` | parent、manifest、commit、annotated tag | 一次确认完成固化 |
| `adapter` | context pack、write guard、handoff/diff 一致性 | OpenCode hook 只传 role/output |

模块 interface 同时是测试 seam；不再为每个门禁维护一个浅脚本。

## Spec 与追溯

`/sdlc-spec` 同一会话生成三份独立机器产物。校验规则：

- 交互设计明确派生自 [`mattpocock/skills`](https://github.com/mattpocock/skills)：保持技能小而
  可组合，事实从环境获取、决策交给用户，沿决策树一次只问一个问题，每问给推荐答案，达成
  共享理解前不行动；
- `grilling` 负责对齐，固定 spec 综合负责发布；本插件把二者编排在一个用户阶段，但以明确
  确认作为硬边界；
- 每题由 OpenCode `question` 提供 2–3 个候选、推荐依据和自定义答案；共享术语、模块 seam 与
  测试 seam 在访谈中逐步收敛；
- command/agent/skill 只负责编排，Python `artifacts` 模块确定性生成统一风格的
  requirements/design/test-plan JSON 与 Markdown；

- `R-xxxx`、`D-xxxx`、`T-xxxx` 唯一且格式固定；
- 每个 R 至少映射一个 D 和一个 T；
- 每个 D 至少被一个 T 覆盖；
- design.extension_point 必须存在于 scaffold；
- design.allowed_paths 与 scaffold.allowed_paths 共同形成写入白名单；
- 每个 T 指定 level、前置、输入、预期、mandatory 和 lifecycle command。

修改需求生成新 R-id，并以 supersedes 指向旧 R-id。原 ID 永不复用。

## Lifecycle

契约只保存 argv 数组，不保存 shell 字符串。环境准备优先级：

1. 项目 wrapper；
2. Corepack/packageManager；
3. 已安装系统工具；
4. 模板 lifecycle 已声明且 runner 白名单允许的自动系统安装。

init 的成功标准是 install、compile、start、health、artifact 全部通过，并完成 stop（除非模板
明确 keep running）。code 阶段重复执行 compile → stop old → start new → health/artifact，
因此文档落盘或 coder 的 compiled 声明不能过门。

health 支持 process、HTTP、TCP、command、file 和 browser smoke。browser smoke 在 core 中
以无 UI HTTP 页面探针实现；需要真实交互的模板必须把受控 E2E 命令登记为 command。当前
Electron 模板的 `test:e2e` 会启动打包后的真实窗口，并验证 preload bridge 与 typed IPC，
不能用 renderer HTTP 可达代替。

## 标准与增量

默认 standard。incremental 必须同时满足：

- 父 manifest 完整；
- scaffold/lifecycle/key file 无漂移；
- 不改变公共接口、依赖、数据模型、安全、lifecycle、protected path；
- 用户确认使用增量。

增量复用未变化 R/D/T，只把影响集送给 coder/executor；mandatory 回归仍运行。任一条件失败
自动回到 standard。

## Token 与上下文

- spec 在一个主会话生成，不拆 requirement/design agent；
- 固定两个 subagent，无 reviewer；
- context pack 只含当前 R/D/T、契约和设计允许的相关文件；
- 单包约 30k 字符，超限按模块拆分；
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
