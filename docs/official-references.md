# 附录 B：Claude Code 官方资料索引

> 核对日期：2026-07-24。Claude Code 功能会持续更新；发生行为差异时，以官方文档和当前 CLI `--help` 为准。

## 本插件直接依赖的官方约定

| 主题 | 本插件采用的约定 | 官方文档 |
|---|---|---|
| 插件结构 | `.claude-plugin/plugin.json` 描述插件；Skills、Agents、Hooks 位于插件根目录的标准目录中。 | [Create plugins](https://code.claude.com/docs/en/plugins) |
| 插件技术参考 | 插件安装范围、CLI、缓存、路径和组件字段以参考页为准。 | [Plugins reference](https://code.claude.com/docs/en/plugins-reference) |
| 本地开发加载 | 未发布插件使用 `claude --plugin-dir <path>` 测试；修改后可执行 `/reload-plugins`。 | [Test your plugins locally](https://code.claude.com/docs/en/plugins#test-your-plugins-locally) |
| Skill | Plugin Skill 使用 `plugin-name:skill-name` 命名空间，正文按需加载。 | [Extend Claude with skills](https://code.claude.com/docs/en/slash-commands) |
| Agent/Subagent | Plugin Agent 定义保留在插件 `agents/` 中，并在启用插件的项目里通过 `/agents` 发现。 | [Create custom subagents](https://code.claude.com/docs/en/sub-agents) |
| Hook | Hook 在 Claude Code 生命周期事件上执行确定性命令，可用于规则校验和自动化。 | [Automate workflows with hooks](https://code.claude.com/docs/en/hooks-guide) |
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

1. `claude plugin validate <plugin-path>`
2. `claude --plugin-dir <plugin-path> plugin details sdlc-pipeline`
3. 在目标项目执行 `/agents`，确认 `coder`、`tester`
4. 执行 `/sdlc-pipeline:init`
5. 完整执行 requirement → design → code → test
6. 检查 `docs/traceability-matrix.md` 和项目测试结果
