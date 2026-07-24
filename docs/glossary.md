# 附录 A：术语表

本文解释 `sdlc-pipeline` README、技能、Agent 和门禁输出中使用的专业术语。术语按本插件中的实际含义解释；Claude Code 本身的术语定义以[官方术语表](https://code.claude.com/docs/en/glossary)为准。

## Claude Code 扩展术语

| 术语 | 英文 | 在本插件中的含义 |
|---|---|---|
| 插件 | Plugin | 可安装、可版本化的扩展包。本插件把 Skills、Agents、Hooks、脚本、规则和脚手架资产打包在一起。 |
| 技能 | Skill | 按需加载的工作流说明，位于 `skills/<name>/SKILL.md`。用户通过 `/sdlc-pipeline:<name>` 显式调用。 |
| 子代理 | Subagent / Agent | 在独立上下文中执行专项任务的 AI 工作单元。本插件提供 `coder` 和 `tester`，定义位于插件的 `agents/`，不会复制到业务项目。 |
| 钩子 | Hook | Claude Code 生命周期事件触发的确定性脚本。本插件用它执行门禁、写入保护、交接校验和状态注入。 |
| 清单 | Manifest | 描述插件或脚手架的机器可读配置。`.claude-plugin/plugin.json` 是插件清单；`templates/manifest.json` 是脚手架注册表。 |
| Marketplace | Plugin Marketplace | 插件目录和分发源。`.claude-plugin/marketplace.json` 让当前仓库可作为本地 marketplace 安装。 |
| 项目级安装 | Project scope | 将插件启用声明写入目标项目 `.claude/settings.json`，使该项目默认启用插件。 |
| 开发加载 | Development load | 使用 `claude --plugin-dir <插件目录>` 直接加载未发布插件，不需要先安装，适合开发调试。 |
| `${CLAUDE_PLUGIN_ROOT}` | Plugin root variable | Claude Code 在运行插件时提供的插件根目录变量。Hook 通过它定位安装缓存中的脚本，避免硬编码绝对路径。 |

## 流水线术语

| 术语 | 英文 | 在本插件中的含义 |
|---|---|---|
| 脚手架资产 | Scaffold asset | `templates/<id>/` 下可由 `/init` 复制到新项目的完整工程骨架。它是插件资产，不是插件运行时代码。 |
| 栈规则 | Stack rule | `rules/<stack>.md` 中针对 TypeScript、React、Electron 等技术栈的通用约束。 |
| 脚手架约定 | Scaffold conventions | `templates/conventions/<id>.md` 中针对某个脚手架目录结构、分层和命令的专属规范。 |
| 现有能力清单 | Existing framework inventory | 模板中的 `docs/existing-framework.md`，告诉 AI 已有哪些模块和能力，避免重复造轮子。 |
| 门禁 | Gate | 阶段切换前的硬性校验。条件不满足时，Hook 拒绝派发 Agent，而不是依赖模型自行判断。 |
| 交接块 | Handoff block | Agent 返回的结构化 Markdown 注释块，记录实现文件、D→C 映射、编译结果、走查发现和遗留问题。 |
| 追溯矩阵 | Traceability matrix | `docs/traceability-matrix.md` 中从需求到设计、代码和测试的映射表。H3/H4 脚本负责合并，避免手工漂移。 |
| 派生状态 | Derived state | 不保存独立 `state.json`，而是根据阶段文档、追溯矩阵和验证标记实时计算当前阶段。 |
| 双轴走查 | Two-axis review | Tester 同时检查 Standards（是否符合项目规范）和 Spec（是否满足需求/设计）。 |
| Fresh eye | Fresh-eye review | Tester 使用独立上下文重新阅读需求、设计和代码，减少编码 Agent 的确认偏差。 |
| Worktree | Git worktree | Git 提供的隔离工作目录。`/code` 在前置文档已提交且仓库干净时可用它隔离编码工作。 |
| Evidence over claims | 证据优先 | 以实际 Git diff、文件、矩阵、测试和编译结果作为完成依据，不仅接受 Agent 的文字声明。 |
| MVP | Minimum Viable Product | 本插件当前闭环标准是 R→D→C 完整、编译通过、双轴走查无 high/medium 阻塞；C→T 自动化映射保留为后续扩展。 |

## 追溯标识

| 标识 | 含义 | 产生阶段 | 示例 |
|---|---|---|---|
| R-id | Requirement ID，需求标识 | `/requirement` | `R1`：新增设置入口 |
| D-id | Design ID，设计模块标识 | `/design` | `D1`：菜单扩展 |
| C-id | Code ID，代码实现标识 | `/code` Agent 交接 | `C1 AppLayout` |
| T-id | Test ID，测试用例标识 | 后续测试扩展 | `T1 settings-route` |

一项需求可以映射到多个设计模块，一个设计模块也可以映射到多个代码文件。矩阵中每一行只放一个 R→D 关系，校验脚本再将 D→C 展开并合并。

## 门禁与钩子编号

| 编号 | 作用 |
|---|---|
| G0/G1 | Skill 在派发编码前检查需求、设计和矩阵前置条件。 |
| G2 | `PreToolUse:Agent` 在编码 Agent 启动前执行硬门禁。 |
| G3/H3 | 编码 Agent 停止时校验交接块、实际 Git diff、编译结果和 D→C 映射。 |
| G4 | 测试 Agent 启动前确认编码交接已形成可测试闭环。 |
| G5/H4 | 测试 Agent 停止时校验 Standards/Spec 双轴结果并回写矩阵。 |
| H5/H6/H7 | 在文件写入、会话启动和上下文压缩前后重新派生流水线状态。 |

`G` 表示阶段门禁，`H` 表示由 Hook 执行的校验或状态处理点。编号是本插件内部约定，不是 Claude Code 官方编号。
