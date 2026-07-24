# sdlc-pipeline

“需求分析 → 设计 → 编码 → 测试”四阶段闭环研发流水线插件。插件将可复用脚手架作为资产，通过 Skills、Agents 和 Hooks 约束 AI 按当前项目的架构、目录和编码风格完成开发。

当前版本：`0.4.0`

支持宿主：Claude Code `2.1.63+`、Codex desktop / CLI、OpenCode。三者共享同一套
templates/rules/scripts/skills 核心，各自使用宿主原生的项目级适配层。

## 文档导航

- [快速安装与验证](#安装与验证)
- [四阶段技能](#四阶段技能用户显式推进)
- [快速验证技能](#快速验证技能)
- [脚手架与代码风格约束](#脚手架与代码风格约束)
- [状态机与门禁](#状态机与门禁)
- [附录 A：术语表](docs/glossary.md)
- [附录 B：Claude Code / Codex / OpenCode 官方资料索引](docs/official-references.md)
- [设计决策溯源](docs/design/参照版SDLC流水线插件设计方案.md)

## 核心理念

- **evidence over claims**:可机器校验的约束(追溯矩阵、交接块、状态)全写成校验脚本,不靠 LLM 自觉。
- **路径全派生**:skill/agent 正文零硬编码栈名,一切从 `templates/manifest.json` + 所选脚手架派生。
- **hooks 守纪律**:hooks 只做生命周期确定性控制点(PreToolUse deny 事前拦截 / PostToolUse 注入事实 / SubagentStop 自纠正),不做工作流编排;阶段推进靠用户显式 skill + agent 工具限制。
- **可观测而非黑盒**:阶段真值、活动 run、execution root、worktree、基线改动与合并指纹均可由诊断脚本直接查看；确定性机制由快速回归覆盖。
- **阶段 skill 数量与脚手架解耦**:阶段 skill 恒定 5 个,加脚手架只改 `templates/` + manifest(数据),不加阶段 skill；另有 1 个非阶段 `verify` skill 用于机制验证和宿主冒烟。

## 前置条件

- Claude Code `2.1.63+`、支持项目 Skills/Hooks 的当前 Codex desktop / CLI，或支持项目 plugins/skills/agents/commands 的 OpenCode
- Python `3.10+`：校验脚本运行时；`hooks/hooks.json` 默认调用 `python`
- Git：推荐使用，用于真实改动集校验和可选 worktree 隔离
- 使用 `heli-terminal-client` 资产时需要 Node.js、Corepack；pnpm 版本以模板根 `package.json#packageManager` 为准

## 安装与验证

### 推荐：安装到具体业务项目

本插件默认是**项目级**的。安装器只写目标业务项目，不写
`~/.codex`、`~/.claude` 或 OpenCode 全局配置：

```powershell
python D:\workspace\sdlc-plipeline-ref\scripts\install_project.py `
  --target D:\workspace\my-business-project `
  --host all
```

也可以重复 `--host` 只安装需要的宿主。安装后共享运行时在
`.sdlc-pipeline/`，Claude Code adapter 在 `.claude/`，Codex adapter 在
`.agents/skills/` 与 `.codex/hooks.json`，OpenCode adapter 在 `.opencode/`。
升级受管文件使用 `--force`。

Codex 会复用现有登录态：安装器**不创建隔离 `CODEX_HOME`，不需要 device
login**。首次读取项目 hook 时仍需通过 `/hooks` 审核内容；这是代码信任，不是
账号登录。

### Codex：发布形态与仓库内开发

本仓库同时提供 Codex manifest：`.codex-plugin/plugin.json`，以及 repo-scoped marketplace：`.agents/plugins/marketplace.json`。在 Codex desktop 中打开本仓库、重启应用后，可从 **Plugins** 选择 `sdlc-pipeline-local` 并安装；安装或 hook 内容变化后，使用 `/hooks` 审核并信任插件 hooks。

CLI 可用于登记和检查 marketplace：

```powershell
codex plugin marketplace add D:\workspace\sdlc-plipeline-ref
codex plugin marketplace list
codex plugin add sdlc-pipeline@sdlc-pipeline-local
codex plugin list
```

Codex 的 skill 显式调用形式为 `$sdlc-pipeline:init`、`$sdlc-pipeline:requirement` 等。Codex App 中推荐直接使用当前 Local/Worktree checkout；需要隔离时新建 Worktree chat，不在 skill 内嵌套创建 worktree。

上面的 marketplace 路径只用于发布/插件开发验证。Codex plugin manager 当前把
启用状态记录在用户配置中，所以**项目级使用推荐安装器**：项目 skill 名为
`$sdlc-pipeline-init`、`$sdlc-pipeline-requirement` 等，项目必须被 Codex 标记为
trusted 才会加载 `.codex/hooks.json`。

官方说明：[Build plugins](https://learn.chatgpt.com/docs/build-plugins)、[Hooks](https://learn.chatgpt.com/docs/hooks)、[Worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)。

### Claude Code：开发加载

在**目标业务项目目录**启动 Claude Code，并让 `--plugin-dir` 指向插件源码目录：

```powershell
cd D:\workspace\heli-terminal-client-menu
claude --plugin-dir D:\workspace\sdlc-plipeline-ref
```

这种方式直接加载未发布插件，不会把插件的 `agents/`、`skills/` 或 `hooks/` 复制到业务项目。可用以下命令检查组件发现结果：

```powershell
claude --plugin-dir D:\workspace\sdlc-plipeline-ref plugin details sdlc-pipeline
```

官方说明：[Test your plugins locally](https://code.claude.com/docs/en/plugins#test-your-plugins-locally)。

### Claude Code：本地 marketplace 项目级安装

本仓库提供 `.claude-plugin/marketplace.json`。在目标项目执行：

```powershell
cd D:\workspace\heli-terminal-client-menu
claude plugin marketplace add D:\workspace\sdlc-plipeline-ref --scope project
claude plugin install sdlc-pipeline@sdlc-pipeline-local --scope project
claude plugin details sdlc-pipeline@sdlc-pipeline-local
```

`--scope project` 会把启用声明写入目标项目的 `.claude/settings.json`。本地绝对路径只适用于当前机器；团队共享时应把 marketplace 放到 Git 仓库，并使用 GitHub 或 Git URL 作为 source。

官方说明：[Discover and install plugins](https://code.claude.com/docs/en/discover-plugins)、[Plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)。

### Claude Code：重载与调试

- 修改插件后，在交互会话执行 `/reload-plugins`，或重启 Claude Code。
- 执行 `/agents`，确认插件提供的 `coder`、`tester` 已被发现。
- 使用 `claude --debug` 查看 Hook 和插件加载日志。
- 不要把插件目录手工复制到业务项目的 `.claude-plugin/`；该目录用于插件/marketplace manifest，不是项目级插件安装目录。

### OpenCode：项目原生适配

执行安装器的 `--host opencode` 后，OpenCode 自动发现项目内 plugin、skills、
commands 和 agents，无需修改全局 `opencode.json`。阶段命令为 `/sdlc-init`、
`/sdlc-requirement`、`/sdlc-design`、`/sdlc-code`、`/sdlc-test`；
快速验证命令为 `/sdlc-verify`。

OpenCode adapter 在 `task` 前运行门禁，在 task 返回后运行相同的 H3/H4
证据校验。OpenCode 当前没有与 Claude Code/Codex `SubagentStop` 完全相同的
“阻止结束并让同一子代理继续”语义，因此不合规交接会在 task 返回后失败并保留
现场，重试需重新派发。这是明确的降级模式。

## 四阶段技能(用户显式推进)

发布插件模式和项目原生模式的名称略有不同，但执行同一份共享 skill：

| 阶段 | Claude 项目原生 | Codex 项目原生 | OpenCode | 职责 |
|---|---|---|---|---|
| init | `/sdlc-pipeline-init` | `$sdlc-pipeline-init` | `/sdlc-init` | 选脚手架并接入项目指令 |
| requirement | `/sdlc-pipeline-requirement` | `$sdlc-pipeline-requirement` | `/sdlc-requirement` | 澄清需求，锁定 R-id |
| design | `/sdlc-pipeline-design` | `$sdlc-pipeline-design` | `/sdlc-design` | 分配 D-id，填 R→D |
| code | `/sdlc-pipeline-code` | `$sdlc-pipeline-code` | `/sdlc-code` | 派发 coder，收 D→C 证据 |
| test | `/sdlc-pipeline-test` | `$sdlc-pipeline-test` | `/sdlc-test` | fresh-eye 双轴走查 |

Claude marketplace/`--plugin-dir` 模式仍使用 `/sdlc-pipeline:<skill>`。三种
宿主执行同一条 `init → requirement → design → code → test` 流程。

## 快速验证技能

`verify` 是非阶段 skill，不推进需求、设计、编码或测试产物。它给 Claude Code、
Codex 和 OpenCode 一个统一的“机制验证/可观测诊断”入口，适合日常修改 hooks、
skills、安装器或 adapter 后快速确认接线：

| 宿主 | 项目原生入口 | 发布/开发入口 | 用途 |
|---|---|---|---|
| Claude Code | `/sdlc-pipeline-verify` | `/sdlc-pipeline:verify` | 说明 Claude 跑法，执行 L1/L1b/L3，检查 skills/agents/hooks 发现 |
| Codex | `$sdlc-pipeline-verify` | `$sdlc-pipeline:verify` | 执行机制测试、安装契约和 `inspect_pipeline.py` |
| OpenCode | `/sdlc-verify` | 项目 `.opencode/` adapter | 执行同一套机制验证，检查 command/agent/plugin 接线 |

日常优先执行：

```powershell
python tests\test_pipeline.py
python tests\test_project_install.py
python scripts\inspect_pipeline.py --project-root D:\path\to\business-project
```

宿主冒烟只在 adapter/hook/agent 接线变化后，在新的临时业务项目里运行；完整
`init → requirement → design → code → test` 只作为发布候选验证。

## 脚手架与代码风格约束

`/init` 选择脚手架后，后续 AI 生成代码时使用四层约束：

1. `templates/manifest.json`：声明脚手架、技术栈、资产路径和专属 conventions。
2. `rules/<stack>.md`：加载 TypeScript、Electron、React 等栈级规则。
3. `templates/conventions/<scaffold-id>.md`：加载当前脚手架的分层、命名、目录和交付命令。
4. `<scaffold>/docs/existing-framework.md`：告诉 AI 已有模块、IPC、错误体系和 UI 结构，避免重复造轮子。

编码 Agent 还必须：

- 先阅读需求、设计、栈规则、脚手架约定和现有能力清单；
- 以根 `package.json#packageManager` 为工具链版本真值；
- 不得为了适配本机环境擅自修改 workspace、Vite、TypeScript 等工具配置；
- 在交接块中报告真实文件、D→C 映射、编译结果和遗留问题；
- 接受 H3 对 Git diff、代码路径、映射闭合和编译事实的复校。

这些机制不能数学意义上保证任何模型输出都完美，但能把风格要求从“提示建议”提升为“明确输入 + 写入边界 + 可机器校验门禁”。`heli-terminal-client` 的具体约定见 [`templates/conventions/heli-terminal-client.md`](templates/conventions/heli-terminal-client.md)。

## 组件

| 类型 | 数量 | 说明 |
|---|---|---|
| user-invoked phase skill | 5 | 四阶段命令 + init |
| diagnostic skill | 1 | `verify`：快速机制验证、宿主冒烟说明、可观测诊断 |
| agent role | 2 | Claude Agent、Codex `spawn_agent`、OpenCode `task` 共享角色正文 |
| hook event type | 6 | PreToolUse、SubagentStart、SubagentStop、PostToolUse、SessionStart、PreCompact |
| hook command handler | 11 | 门禁、身份绑定、写入保护、交接自纠正/merge、派生状态注入 |
| 确定性脚本 | 11 | 门禁/交接/状态、Codex 异步结果适配、run journal、原子发布、快速诊断和子代理登记 |

## 状态机与门禁

- **派生状态**:无 state 文件,每次从产物存在性 + 矩阵实时派生(`derive_state.py`)。
- **运行现场**:`/code` 另有一份不入业务分支的原子运行登记，记录 run-id、execution root、宿主模式、编码前改动基线、agent_id 和已走查文件指纹；它不决定阶段，只用于中断接管和证据根绑定。
- **崩溃恢复**:阶段之间由 SessionStart 重算；agent 中断后诊断会显示活动 run 和 execution root，可复用现场继续或明确 abandon。它不是 token 级恢复，而是可发现、可接管的阶段内现场。
- **门禁**:G0/G1 由 skill 自查；G2/G4 由派发前门禁；G3/G5 使用同一套 validate/merge 脚本。Claude 由 SubagentStop + PostToolUse 调用；Codex 在异步 wait 后由 `validate_result.py` 调用；OpenCode 在同步 task 的 `tool.execute.after` 调用。
- **追溯矩阵** `docs/traceability-matrix.md`:R→D 由 `/design` 生成并做结构门禁；agent 在交接块吐 D→C/走查证据，由 H3/H4 脚本校验后 merge。
- **改动真实性**:git 工程中,H3 会把 handoff `files` 与 tracked/untracked 实际改动文件集精确比对;非 git 工程退化为路径边界与存在性校验。
- **MVP 闭合判据**:R→D→C 三段闭合 + 双轴 review-findings 合规且无 high/medium 阻塞。接口测试/Playwright 行为仍 defer。

## 宿主适配

| 能力 | Claude Code | Codex | OpenCode |
|---|---|---|---|
| 发布入口 | `.claude-plugin` | `.codex-plugin` | `package.json` + `.opencode/plugins` |
| 项目入口 | `.claude/` | `.agents/skills` + `.codex/hooks.json` | `.opencode/` |
| 子代理 | `Agent` | `spawn_agent` | `task` + custom agent |
| 事前门禁 | PreToolUse | PreToolUse | `tool.execute.before` |
| 事后证据 | SubagentStop + PostToolUse | wait 后 `validate_result.py` | `tool.execute.after` |
| 阶段内自纠正 | 支持 | 支持 | 返回后拒绝并重新派发 |
| 隔离 | 手工 worktree/当前树 | App Local/Worktree | 当前 session checkout |

### Claude Code 兼容基线

- hook 工具名使用 Claude Code 2.1.63+ 的 `Agent`（旧名 `Task` 仅作为 Claude 内部兼容别名，不用于 matcher）。
- SubagentStop 使用 `agent_type`、`last_assistant_message`，并兼容旧版 `subagent_type`/transcript 输入。
- hook 上下文输出使用 `hookSpecificOutput.hookEventName + additionalContext`。
- tester 通过 `tools` + `disallowedTools` 保持只读；coder 的 docs/ 写入由 PreToolUse 拦截，并由 H3 git diff 复校。
- Agent 文件始终位于插件 `agents/`；安装后由 Claude Code 从插件缓存发现，因此目标业务项目没有 `agents/` 属于正常状态。

### Codex 兼容基线

- Codex manifest 显式声明 `skills`；hooks 放在默认位置 `hooks/hooks.json` 由宿主自动发现。当前随附 validator 尚不接受显式 `hooks` 字段。
- Codex 为插件 hooks 同时提供 `PLUGIN_ROOT` 与兼容变量 `CLAUDE_PLUGIN_ROOT`，因此两宿主共用同一份命令配置。
- Codex 的 `apply_patch` 会命中 Edit/Write matcher，但 hook 输入保留 `tool_name=apply_patch`；保护脚本会解析 patch 目标路径。tester 拒绝编辑与含变更信号的 shell、允许只读 shell，H4 再用代码指纹复核；coder 拒绝修改 `docs/` 但可读取阶段文档。
- Codex 插件不依赖 Claude Agent frontmatter 被自动注册为 custom agent；`code`/`test` skill 使用 `spawn_agent`，要求子代理显式读取共享角色正文。
- Codex `spawn_agent` 立即返回 agent id，最终文本在后续 wait 才到达；dispatcher 在 wait 后调用 `validate_result.py`，失败时 follow-up 同一 agent，成功后才 merge。
- Codex plugin hooks 首次安装或内容变化后需要通过 `/hooks` 审核信任。

### OpenCode 兼容基线

- 项目本地 plugin 使用 `tool.execute.before/after` 映射现有 Python 门禁与交接校验。
- `.opencode/agents/sdlc-tester.md` 通过 permission 禁止 edit/bash/task；H4 再复核交接块。
- `experimental.chat.messages.transform` 注入实时派生状态，阶段真值仍来自磁盘产物。
- OpenCode 无等价 SubagentStop 续回语义；task 返回后拒绝并保留现场，不承诺原 agent 续跑。

## 目录结构

```
plugin-root/
  .codex-plugin/
    plugin.json                 # Codex 插件 manifest
  .claude-plugin/
    plugin.json                 # 插件 manifest
    marketplace.json            # 本地 marketplace 注册表
  .agents/plugins/
    marketplace.json            # Codex repo-scoped marketplace
  .opencode/
    plugins/sdlc-pipeline.js     # OpenCode 项目 adapter
    INSTALL.md
  rules/                        # 栈级规约(按 manifest stacks 按需 Read)
    java.md spring.md vue.md
    typescript.md electron.md react.md
  templates/
    manifest.json               # 脚手架注册表(id/stacks/path/conventions)
    docs/                       # 平台统一填充模板(不拷,按需 Read)
    conventions/                # 脚手架级编码约定(与脚手架平级,防误拷)
    <scaffold-id>/              # 脚手架骨架(整目录拷到工程根)
      docs/existing-framework.md
      src/...
  skills/   agents/   hooks/    # 编排(从零设计)
  scripts/                      # 安装、校验、运行登记、原子发布和诊断脚本
  docs/
    glossary.md                 # 专业术语附录
    official-references.md      # Claude Code / Codex / OpenCode 官方资料索引
```

## 扩展

| 扩展类型 | 要改的 | 不该动的 |
|---|---|---|
| 新增栈 | `rules/<stack>.md` | skill/agent/manifest 既有条目 |
| 新增脚手架 | `templates/<id>/` + `conventions/<id>.md` + manifest 一条 | rules/、skill/agent 正文 |
| 新增文档模板 | `templates/docs/<name>.md` + 使用处 Read | manifest、脚手架 |

## 开发者验证

日常机制验证不需要重跑完整 LLM 流水线。分层如下：

| 层级 | 命令 | 覆盖 | 何时执行 |
|---|---|---|---|
| L1 快速回归 | `python tests\test_pipeline.py` | 门禁、交接、diff、矩阵、恢复、Codex agent_id/apply_patch、双 manifest | 每次脚本/skill/hook 修改 |
| L1b 安装契约 | `python tests\test_project_install.py` | 三宿主项目目录、skills/hooks/agents、verify skill、OpenCode JS、安装后诊断 | adapter/安装器修改 |
| L2 结构校验 | `$plugin-creator` 校验、`claude plugin validate` | manifest、目录、skill frontmatter、hook 配置 | 发布前或结构变化 |
| L3 现场诊断 | `inspect_pipeline.py` | 当前阶段、活动 run、execution root、worktree、未完成项 | 故障排查/中断接管 |
| L4 宿主冒烟 | 隔离目录执行一次目标阶段 | 真实 skill 触发、子代理和 hook 接线 | 宿主升级或接线变化 |
| L5 全流程 E2E | init → requirement → design → code → test | LLM 行为和完整用户体验 | 发布候选，不作为日常回归 |

```powershell
# 插件回归测试
python tests\test_pipeline.py
python tests\test_project_install.py

# 快速查看某个业务项目的派生阶段、残留运行和 worktree
python scripts\inspect_pipeline.py --project-root D:\path\to\business-project

# 同时校验 plugin.json 和 marketplace.json
claude plugin validate D:\workspace\sdlc-plipeline-ref

# 查看插件实际发现的 Skills、Agents 和 Hooks
claude --plugin-dir D:\workspace\sdlc-plipeline-ref plugin details sdlc-pipeline

# Claude Code 内快速验证入口
/sdlc-pipeline:verify

# 将三宿主 adapter 安装到另一个项目
python scripts\install_project.py --target D:\path\to\business-project --host all

# 项目原生安装后，三端验证入口分别为：
# Claude Code: /sdlc-pipeline-verify
# Codex: $sdlc-pipeline-verify
# OpenCode: /sdlc-verify
```

Codex manifest/skill 结构校验使用内置 `$plugin-creator`；项目级验证直接在新的
业务项目中运行安装器并使用现有 Codex 登录态，不创建隔离 `CODEX_HOME`。

使用 `heli-terminal-client` 初始化出的项目还应执行：

```powershell
corepack pnpm typecheck
corepack pnpm test
corepack pnpm build
```

## 常见问题

### 为什么项目根没有裸 `agents/`

`agents/` 是插件源码组件，不是业务骨架。项目原生安装会把宿主 adapter 分别放到
`.claude/agents/` 与 `.opencode/agents/`；Codex 由 skill 调用 `spawn_agent` 并
读取 `.sdlc-pipeline/agents/`。`/init` 只复制业务脚手架资产。

### `/code` 为什么有时不创建 worktree

Claude Code 下，如果需求、设计或矩阵仍有未提交改动，自动创建 worktree 会看不到这些阶段产物，此时技能会在当前工作树编码并说明原因。Codex 下由 App 的 Local/Worktree task 管理隔离；OpenCode 复用当前 session checkout，两者都不创建嵌套 worktree。

### 为什么没有单独的状态文件

阶段真值没有单独状态文件，因为它容易与真实文档和代码漂移。本插件确实维护一份运行 journal，但只记录可丢弃的现场事实，不参与阶段判定。

### agent 中途崩溃后能否续跑

不能恢复模型内部思考或 token 位置，但不会再把半成品变成不可见残留。重启后 `inspect_pipeline.py` 会显示活动 run、execution root 和 worktree；重复启动同一 run 会复用登记，用户可以检查现场后继续，或执行 `python scripts\run_state.py abandon --project-root <项目根>` 明确放弃。合并完成还会按已走查文件指纹核验目标树，避免“矩阵闭环但代码没合并”。

### 为什么 Codex 与 OpenCode 的 agent 入口不同

Codex skill 使用 `spawn_agent` 并让子代理读取共享角色正文；OpenCode 使用
`.opencode/agents` 的 custom agent frontmatter。两者的角色内容都由安装器从同一
`agents/coder.md`、`agents/tester.md` 生成。

### T-id 为什么还是“后续填充”

当前 MVP 的自动闭环范围是 R→D→C，并要求编译与双轴走查通过。C→T 自动化测试映射是预留扩展，不应把空 T-id 误报为当前流程失败。

## 附录与参考

- [附录 A：术语表](docs/glossary.md)：解释 Plugin、Skill、Agent、Hook、Gate、Handoff、R/D/C/T 等术语。
- [附录 B：Claude Code / Codex / OpenCode 官方资料索引](docs/official-references.md)：列出本插件各项实现依据及官方地址。
- [设计决策溯源](docs/design/参照版SDLC流水线插件设计方案.md)：grill 式需求澄清与逐轮决策记录。
- [Claude Code：Create plugins](https://code.claude.com/docs/en/plugins)
- [Claude Code：Plugins reference](https://code.claude.com/docs/en/plugins-reference)
- [Claude Code：Glossary](https://code.claude.com/docs/en/glossary)
- [Codex：Build plugins](https://learn.chatgpt.com/docs/build-plugins)
- [Codex：Hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex：Worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)

## License

[MIT](LICENSE)
