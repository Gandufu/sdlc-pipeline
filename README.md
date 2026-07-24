# sdlc-pipeline

“需求分析 → 设计 → 编码 → 测试”四阶段闭环研发流水线插件。插件将可复用脚手架作为资产，通过 Skills、Agents 和 Hooks 约束 AI 按当前项目的架构、目录和编码风格完成开发。

当前版本：`0.2.0`

Claude Code 兼容基线：`2.1.63+`

## 文档导航

- [快速安装与验证](#安装与验证)
- [四阶段技能](#四阶段技能用户显式推进)
- [脚手架与代码风格约束](#脚手架与代码风格约束)
- [状态机与门禁](#状态机与门禁)
- [附录 A：术语表](docs/glossary.md)
- [附录 B：Claude Code 官方资料索引](docs/official-references.md)
- [设计决策溯源](docs/design/参照版SDLC流水线插件设计方案.md)

## 核心理念

- **evidence over claims**:可机器校验的约束(追溯矩阵、交接块、状态)全写成校验脚本,不靠 LLM 自觉。
- **路径全派生**:skill/agent 正文零硬编码栈名,一切从 `templates/manifest.json` + 所选脚手架派生。
- **hooks 守纪律**:hooks 只做生命周期确定性控制点(PreToolUse deny 事前拦截 / PostToolUse 注入事实 / SubagentStop 自纠正),不做工作流编排;阶段推进靠用户显式命令 + agent 工具限制。
- **skill 数量与脚手架解耦**:skill 恒定 5 个,加脚手架只改 `templates/` + manifest(数据),不加 skill。

## 前置条件

- Claude Code `2.1.63+`
- Python `3.10+`：校验脚本运行时；`hooks/hooks.json` 默认调用 `python`
- Git：推荐使用，用于真实改动集校验和可选 worktree 隔离
- 使用 `heli-terminal-client` 资产时需要 Node.js、Corepack；pnpm 版本以模板根 `package.json#packageManager` 为准

## 安装与验证

### 方式一：开发加载

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

### 方式二：本地 marketplace 项目级安装

本仓库提供 `.claude-plugin/marketplace.json`。在目标项目执行：

```powershell
cd D:\workspace\heli-terminal-client-menu
claude plugin marketplace add D:\workspace\sdlc-plipeline-ref --scope project
claude plugin install sdlc-pipeline@sdlc-pipeline-local --scope project
claude plugin details sdlc-pipeline@sdlc-pipeline-local
```

`--scope project` 会把启用声明写入目标项目的 `.claude/settings.json`。本地绝对路径只适用于当前机器；团队共享时应把 marketplace 放到 Git 仓库，并使用 GitHub 或 Git URL 作为 source。

官方说明：[Discover and install plugins](https://code.claude.com/docs/en/discover-plugins)、[Plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)。

### 重载与调试

- 修改插件后，在交互会话执行 `/reload-plugins`，或重启 Claude Code。
- 执行 `/agents`，确认插件提供的 `coder`、`tester` 已被发现。
- 使用 `claude --debug` 查看 Hook 和插件加载日志。
- 不要把插件目录手工复制到业务项目的 `.claude-plugin/`；该目录用于插件/marketplace manifest，不是项目级插件安装目录。

## 四阶段技能(用户显式推进)

插件 skill 按 Claude Code 官方规则自动命名空间化，完整调用名为
`/sdlc-pipeline:<skill>`；下表括号内保留简称，便于阅读。

| 命令 | 触发方 | 职责 | 产物 |
|---|---|---|---|
| `/sdlc-pipeline:init` (`/init`) | 用户 | 选脚手架 → 拷骨架到工程根(不覆盖)→ 追加 `@docs/existing-framework.md` 到 CLAUDE.md | 项目骨架 + 能力清单 |
| `/sdlc-pipeline:requirement` (`/requirement`) | 用户 | 主会话内 grill 式拷问需求,锁定 R-id | `docs/requirement-spec.md` |
| `/sdlc-pipeline:design` (`/design`) | 用户 | 主会话内读需求+rules → 写设计文档,分配 D-id,填 R→D | `docs/design-doc.md` |
| `/sdlc-pipeline:code` (`/code`) | 用户(派单员) | 开 git worktree → 通过 Agent 工具派发编码 agent → 收交接块 | 源码 + 交接块 |
| `/sdlc-pipeline:test` (`/test`) | 用户(派单员) | 通过 Agent 工具派发测试 agent(fresh eye)→ 收双轴走查 | 走查结论 + 交接块 |

典型流程:`/sdlc-pipeline:init` → `/sdlc-pipeline:requirement` →
`/sdlc-pipeline:design` → `/sdlc-pipeline:code` → `/sdlc-pipeline:test`。

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
| user-invoked skill | 5 | 四阶段命令 + init |
| agent | 2 | 编码 agent(工具限制:禁碰 docs)+ 测试 agent(工具限制:禁 Edit 源码) |
| hook event type | 5 | PreToolUse、SubagentStop、PostToolUse、SessionStart、PreCompact；`plugin details` 按事件类型计数 |
| hook command handler | 10 | G2/G4 门禁 + agent 写入保护 + H3/H4 交接块自纠正与 merge + H5/H6/H7 派生状态注入 |
| 校验脚本 | 6 | `gate_code` / `gate_test` / `guard_agent_actions` / `validate_code_handoff` / `validate_test_handoff` / `derive_state` |

## 状态机与门禁

- **派生状态**:无 state 文件,每次从产物存在性 + 矩阵实时派生(`derive_state.py`)。
- **门禁**:G0/G1 由 skill 自查;G2/G4 由 `PreToolUse:Agent` deny 硬拦;G3/G5 由 SubagentStop 自纠正 + `PostToolUse:Agent` merge 双钩。
- **追溯矩阵** `docs/traceability-matrix.md`:agent 在交接块吐映射,H3/H4 脚本 merge 落盘,**零手改**。
- **改动真实性**:git 工程中,H3 会把 handoff `files` 与 tracked/untracked 实际改动文件集精确比对;非 git 工程退化为路径边界与存在性校验。
- **MVP 闭合判据**:R→D→C 三段闭合 + 双轴 review-findings 合规且无 high/medium 阻塞。接口测试/Playwright 行为仍 defer。

## Claude Code 兼容基线

- hook 工具名使用 Claude Code 2.1.63+ 的 `Agent`（旧名 `Task` 仅作为 Claude 内部兼容别名，不用于 matcher）。
- SubagentStop 使用 `agent_type`、`last_assistant_message`，并兼容旧版 `subagent_type`/transcript 输入。
- hook 上下文输出使用 `hookSpecificOutput.hookEventName + additionalContext`。
- tester 通过 `tools` + `disallowedTools` 保持只读；coder 的 docs/ 写入由 PreToolUse 拦截，并由 H3 git diff 复校。
- Agent 文件始终位于插件 `agents/`；安装后由 Claude Code 从插件缓存发现，因此目标业务项目没有 `agents/` 属于正常状态。

## 目录结构

```
plugin-root/
  .claude-plugin/
    plugin.json                 # 插件 manifest
    marketplace.json            # 本地 marketplace 注册表
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
  scripts/                      # 校验脚本 + 共享库 _lib.py
  docs/
    glossary.md                 # 专业术语附录
    official-references.md      # Claude Code 官方资料索引
```

## 扩展

| 扩展类型 | 要改的 | 不该动的 |
|---|---|---|
| 新增栈 | `rules/<stack>.md` | skill/agent/manifest 既有条目 |
| 新增脚手架 | `templates/<id>/` + `conventions/<id>.md` + manifest 一条 | rules/、skill/agent 正文 |
| 新增文档模板 | `templates/docs/<name>.md` + 使用处 Read | manifest、脚手架 |

## 开发者验证

```powershell
# 插件回归测试
python tests\test_pipeline.py

# 同时校验 plugin.json 和 marketplace.json
claude plugin validate D:\workspace\sdlc-plipeline-ref

# 查看插件实际发现的 Skills、Agents 和 Hooks
claude --plugin-dir D:\workspace\sdlc-plipeline-ref plugin details sdlc-pipeline
```

使用 `heli-terminal-client` 初始化出的项目还应执行：

```powershell
corepack pnpm typecheck
corepack pnpm test
corepack pnpm build
```

## 常见问题

### 为什么初始化后的业务项目没有 `agents/`

`agents/` 是插件组件，不是脚手架资产。Claude Code 从启用插件或插件缓存中发现它们；`/init` 只复制 `templates/<id>/` 中的业务工程资产。

### `/code` 为什么有时不创建 worktree

如果需求、设计或矩阵仍有未提交改动，自动创建 worktree 会看不到这些阶段产物。此时技能会在当前工作树编码并说明原因，避免自动提交或 stash 用户文档。

### 为什么没有单独的状态文件

单独状态文件容易与真实文档和代码漂移。本插件在 SessionStart、PreCompact 和相关写入事件后，根据阶段文档与追溯矩阵重新派生状态。

### T-id 为什么还是“后续填充”

当前 MVP 的自动闭环范围是 R→D→C，并要求编译与双轴走查通过。C→T 自动化测试映射是预留扩展，不应把空 T-id 误报为当前流程失败。

## 附录与参考

- [附录 A：术语表](docs/glossary.md)：解释 Plugin、Skill、Agent、Hook、Gate、Handoff、R/D/C/T 等术语。
- [附录 B：Claude Code 官方资料索引](docs/official-references.md)：列出本插件各项实现依据及官方地址。
- [设计决策溯源](docs/design/参照版SDLC流水线插件设计方案.md)：grill 式需求澄清与逐轮决策记录。
- [Claude Code：Create plugins](https://code.claude.com/docs/en/plugins)
- [Claude Code：Plugins reference](https://code.claude.com/docs/en/plugins-reference)
- [Claude Code：Glossary](https://code.claude.com/docs/en/glossary)

## License

[MIT](LICENSE)
