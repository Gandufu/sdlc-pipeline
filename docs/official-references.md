# 附录 B：Claude Code / Codex / OpenCode 官方资料索引

> 核对日期：2026-07-24。三个宿主都会持续更新；发生行为差异时，以官方文档和当前 CLI `--help` 为准。

## 本插件直接依赖的官方约定

| 主题 | 本插件采用的约定 | 官方文档 |
|---|---|---|
| 插件结构 | `.claude-plugin/plugin.json` 描述插件；Skills、Agents、Hooks 位于插件根目录的标准目录中。 | [Create plugins](https://code.claude.com/docs/en/plugins) |
| 插件技术参考 | 插件安装范围、CLI、缓存、路径和组件字段以参考页为准。 | [Plugins reference](https://code.claude.com/docs/en/plugins-reference) |
| 本地开发加载 | 未发布插件使用 `claude --plugin-dir <path>` 测试；修改后可执行 `/reload-plugins`。 | [Test your plugins locally](https://code.claude.com/docs/en/plugins#test-your-plugins-locally) |
| Skill | Plugin Skill 使用 `plugin-name:skill-name` 命名空间，正文按需加载。 | [Extend Claude with skills](https://code.claude.com/docs/en/slash-commands) |
| Agent/Subagent | Plugin Agent 定义保留在插件 `agents/` 中，并在启用插件的项目里通过 `/agents` 发现。 | [Create custom subagents](https://code.claude.com/docs/en/sub-agents) |
| Hook | Hook 在 Claude Code 生命周期事件上执行确定性命令，可用于规则校验和自动化。 | [Automate workflows with hooks](https://code.claude.com/docs/en/hooks-guide) |
| Hook 路径语义 | Hook 输入的 `cwd` 是触发时当前目录；`${CLAUDE_PROJECT_DIR}` 是项目根。本插件不把两者任一单独当作 worktree 身份，而由 `/code` 运行登记绑定 execution root。 | [Hooks reference](https://code.claude.com/docs/en/hooks) |
| Worktree | Claude Code 支持原生 worktree/session/subagent 隔离，也允许直接用 Git 管理 worktree；有改动的 worktree 可能被保留。 | [Run parallel sessions with worktrees](https://code.claude.com/docs/en/worktrees) |
| Marketplace | Marketplace 通过 `.claude-plugin/marketplace.json` 提供插件目录；本地路径可用于安装测试。 | [Create and distribute a plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces) |
| 安装插件 | Marketplace 添加、插件安装、启用、禁用和重载方式。 | [Discover and install plugins](https://code.claude.com/docs/en/discover-plugins) |
| 项目级配置 | `enabledPlugins` 和 `extraKnownMarketplaces` 可写入项目 `.claude/settings.json`。 | [Claude Code settings](https://code.claude.com/docs/en/settings#plugin-settings) |
| 官方术语 | Claude Code 对 Skill、Hook、Subagent、Plugin 等概念的统一定义。 | [Glossary](https://code.claude.com/docs/en/glossary) |

## 官方规则与本仓库实现的对应关系

### 1. 为什么目标项目没有 `agents/`

Claude Code 会从已启用插件自身的 `agents/` 目录发现 Agent。安装插件时，插件内容进入 Claude Code 插件缓存；业务项目只需要启用配置，不需要复制 Agent 文件。

- 本仓库定义：`agents/coder.md`、`agents/tester.md`
- 目标项目配置：`.claude/settings.json`
- 官方依据：[Plugin Subagents](https://code.claude.com/docs/en/sub-agents#choose-the-subagent-scope)

### 2. 为什么开发时使用 `--plugin-dir`

这是官方提供的未安装插件开发加载方式。它直接读取工作目录中的最新插件内容，适合频繁修改和验证；Marketplace 安装则更接近最终用户使用方式。

- 开发验证：`claude --plugin-dir D:/workspace/sdlc-plipeline-ref`
- 项目安装：先添加 marketplace，再执行 `claude plugin install ... --scope project`
- 官方依据：[Test your plugins locally](https://code.claude.com/docs/en/plugins#test-your-plugins-locally)

### 3. 为什么 Hook 使用 `${CLAUDE_PLUGIN_ROOT}`

Marketplace 安装会把插件复制到版本化缓存，插件不能假定自己仍位于源码目录。Hook 命令必须通过 `${CLAUDE_PLUGIN_ROOT}` 定位随插件安装的脚本。

- 本仓库实现：`hooks/hooks.json`
- 官方依据：[Plugins reference](https://code.claude.com/docs/en/plugins-reference)

### 4. 本地 marketplace 的可移植性

本地 `directory` source 适合当前机器验证。如果 `.claude/settings.json` 写入 `D:\...` 绝对路径，换机器或移动目录后需要重新登记。团队共享应使用 GitHub、Git URL 或其他可访问的 Git marketplace。

- 本地验证源：`.claude-plugin/marketplace.json`
- 官方依据：[Plugin marketplace sources](https://code.claude.com/docs/en/plugin-marketplaces#plugin-sources)

## 建议的核对顺序

1. 日常快速回归：`python tests/test_pipeline.py`
2. 插件结构校验：`claude plugin validate <plugin-path>`
3. 组件发现校验：`claude --plugin-dir <plugin-path> plugin details sdlc-pipeline`
4. 业务项目现场诊断：`python scripts/inspect_pipeline.py --project-root <project-path>`
5. 只有涉及 skill/agent 行为或宿主升级时，才在隔离目录完整执行 requirement → design → code → test

## Codex 官方约定

| 主题 | 本插件采用的约定 | 官方文档 |
|---|---|---|
| 插件结构 | `.codex-plugin/plugin.json` 显式指向 `./skills/`；默认位置 `hooks/hooks.json` 由 Codex 自动发现。当前随附 validator 尚不接受显式 `hooks` 字段，故采用默认发现。 | [Build plugins](https://learn.chatgpt.com/docs/build-plugins) |
| Repo marketplace | `$REPO_ROOT/.agents/plugins/marketplace.json`，本地 source path 以 marketplace root 为基准且使用 `./` 前缀。 | [Install a local plugin manually](https://learn.chatgpt.com/docs/build-plugins#install-a-local-plugin-manually) |
| Skill | Codex 支持显式 `$skill-name` 调用和按 description 隐式触发；插件为 skill 提供命名空间。 | [Build skills](https://learn.chatgpt.com/docs/build-skills) |
| Hooks | 插件可打包默认 `hooks/hooks.json`；首次运行或内容变化后必须审核信任。 | [Hooks](https://learn.chatgpt.com/docs/hooks) |
| Hook 根变量 | Codex 提供 `PLUGIN_ROOT`、`PLUGIN_DATA`，并提供 `CLAUDE_PLUGIN_ROOT`、`CLAUDE_PLUGIN_DATA` 兼容变量。 | [Hooks: environment variables](https://learn.chatgpt.com/docs/hooks) |
| 子代理 | Codex 使用 `spawn_agent`；SubagentStart/Stop 提供 agent_id 生命周期事件。 | [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)、[Hooks](https://learn.chatgpt.com/docs/hooks) |
| 编辑 matcher | Codex `apply_patch` 与 `Edit|Write` matcher 兼容，hook 输入仍保留真实 `tool_name=apply_patch`。 | [Hooks: tool matcher compatibility](https://learn.chatgpt.com/docs/hooks) |
| 项目指令 | Codex 从仓库层级加载 `AGENTS.md`。 | [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md) |
| 项目 Skills | 仓库级 skill 位于 `.agents/skills`，适用于团队共享项目工作流。 | [Skills](https://learn.chatgpt.com/docs/skills) |
| 项目 Hooks | trusted 项目可从 `.codex/hooks.json` 加载 hooks；首次或内容变化后需审核信任。 | [Hooks](https://learn.chatgpt.com/docs/hooks) |
| Worktree | Codex App 的 Local/Worktree chat 使用 Git worktree 隔离，Handoff 在两者间移动 chat/代码。 | [Worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees) |

实测补充：Codex `spawn_agent` 是异步派发，派发工具返回时未必已有最终交接正文。
项目 skill 在 wait 后调用 `validate_result.py` 执行共享 H3/H4；这是宿主时序 adapter，
不改变交接协议。

## OpenCode 官方约定

| 本插件实现 | 官方约定 | 官方来源 |
|---|---|---|
| 项目 Plugin | `.opencode/plugins/` 中的本地 JS/TS plugin 会被项目自动加载。 | [Plugins](https://opencode.ai/docs/plugins/) |
| 项目 Skills | `.opencode/skills/<name>/SKILL.md` 是项目级 skill；OpenCode 也兼容 `.agents/skills`。 | [Skills](https://opencode.ai/docs/skills/) |
| 项目 Agents | `.opencode/agents/*.md` 定义 custom agent，并可通过 permission 限制工具。 | [Agents](https://opencode.ai/docs/agents/) |
| 项目 Commands | `.opencode/commands/*.md` 定义 slash command。 | [Commands](https://opencode.ai/docs/commands/) |
| 工具生命周期 | `tool.execute.before/after` 可在 task 前后运行确定性门禁与校验。 | [Plugins](https://opencode.ai/docs/plugins/) |

OpenCode 当前 plugin API 没有与 Claude/Codex `SubagentStop` 完全等价的“阻止
子代理结束并恢复同一上下文”能力。本插件只承诺 task 返回后的证据拒绝与现场保留。

## 三宿主核对顺序

1. `python tests/test_pipeline.py`：快速验证 hook payload、run journal、矩阵和写入边界。
2. `python tests/test_project_install.py`：验证三宿主项目目录和 adapter 契约。
3. Codex plugin validator + `claude plugin validate`：验证发布 manifest。
4. 新业务目录宿主冒烟：验证真实 skill/command/hook 发现。
5. 完整 init→requirement→design→code→test：发布候选执行，不用于每次脚本修改。
