# OpenCode 官方资料索引

核对日期：2026-07-26。当前正式宿主只有 OpenCode；桌面版与 CLI 均读取项目级配置。

| 本插件实现 | 官方约定 | 官方来源 |
|---|---|---|
| 项目 plugin | `.opencode/plugins/` 中的 JS/TS 自动加载 | [Plugins](https://opencode.ai/docs/plugins/) |
| 自定义工具 | plugin 通过 `tool()` 注册带 schema 的工具 | [Custom tools](https://opencode.ai/docs/plugins/#custom-tools) |
| 正式门禁 hook | `tool.execute.before/after` 可修改参数或拒绝执行 | [Plugin hooks](https://opencode.ai/docs/plugins/) |
| 项目 skill | `.opencode/skills/<name>/SKILL.md` 按需加载 | [Skills](https://opencode.ai/docs/skills/) |
| primary/subagent | `.opencode/agents/*.md` 定义模式、prompt 和 permission | [Agents](https://opencode.ai/docs/agents/) |
| slash command | `.opencode/commands/*.md` 定义命令、agent 与 subtask | [Commands](https://opencode.ai/docs/commands/) |
| task 权限 | permission 可只允许指定 subagent，并拒绝其余目标 | [Permissions](https://opencode.ai/docs/permissions/) |
| 结构化问答 | primary agent 允许 `question`，每问包含 header、options 和自定义答案 | [Question tool](https://opencode.ai/docs/tools/#question) |

本插件不使用 `experimental.chat.messages.transform`，也不依赖与 Claude/Codex
SubagentStop 等价的同上下文恢复。task 校验失败时返回结构化错误，由主会话重新派发。

模板资产不属于 OpenCode plugin 组件：插件只在 `templates/manifest.json` 保存模板数据源
元数据，模板源码、依赖、生命周期契约和测试由独立 Git 仓库维护。当前登记的参考实现是
[`sdlc-electron-scaffold`](https://github.com/Gandufu/sdlc-electron-scaffold)。

需求阶段的方法来源不是 OpenCode API，而是
[`mattpocock/skills`](https://github.com/mattpocock/skills)：
[`grilling`](https://github.com/mattpocock/skills/blob/main/skills/productivity/grilling/SKILL.md)
提供逐分支、一次一问、每问推荐答案和共享理解门禁；
[`grill-with-docs`](https://github.com/mattpocock/skills/blob/main/skills/engineering/grill-with-docs/SKILL.md)
强调在访谈中形成共享语言与决策文档；
[`to-spec`](https://github.com/mattpocock/skills/blob/main/skills/engineering/to-spec/SKILL.md)
提供问题、方案、实现决策、测试决策和 out-of-scope 的 spec 风格。本插件保留这些设计原则，
但使用自身 R→D→T schema 和 Python 固定 renderer，不复制 issue tracker 接口。

推荐核对顺序：

1. `python -m unittest discover -s tests -v`
2. `node --check .opencode/plugins/sdlc-pipeline.js`
3. 用 OpenCode 桌面版打开一个 installer 生成的临时项目，核对 skill/agent/command/plugin 发现
4. 在隔离 Git 仓库执行完整 init → spec → code → test → version
