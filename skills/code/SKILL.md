---
name: code
description: >-
  This skill should be used when the user asks to "写代码", "开始编码", "code",
  "/code", "$code", or has finished /design and wants to proceed to coding. It acts as
  a dispatcher (派单员): reads the manifest, resolves stack-rules + conventions
  + design-doc paths, chooses the host-appropriate execution root, and dispatches
  a coder subagent with those paths embedded in its prompt. Compatible with
  Claude Code Agent, Codex spawn_agent and OpenCode task.
---

# /code — 编码(派单员)

约束 #2:agent 拿不到自动加载的 skill 正文。故本 skill 充当**派单员**,把所有资产路径拼进 Agent prompt,编码 agent 启动后**显式 Read**(设计文档 §3.5)。

## 前置
G2 门禁(进入编码前)由 PreToolUse hook H1 在派发编码 agent 时硬拦:`requirement-spec 每个 R-id 在矩阵有 D 映射` 且 `design-doc 必填章节齐`。若被 deny,hook 会以事实陈述告知缺什么,本 skill 不重跑。

## 执行步骤

1. **解析 manifest**:`Read ${CLAUDE_PLUGIN_ROOT}/templates/manifest.json`,按项目所选脚手架（查 `CLAUDE.md`、`AGENTS.md`、项目上下文或询问用户）取得:
   - `stacks` → `${CLAUDE_PLUGIN_ROOT}/rules/<stack>.md` 路径清单
   - `conventions` → `${CLAUDE_PLUGIN_ROOT}/templates/conventions/<id>.md` 路径
   - 项目内路径:`docs/design-doc.md`、`docs/requirement-spec.md`

2. **选择执行根并登记现场**:
   - 首先执行 `python "${CLAUDE_PLUGIN_ROOT}/scripts/run_state.py" status --project-root "<项目根>"`。若存在未完成运行且 `execution_root` 仍存在，**复用该现场**并让 coder 先检查已有 diff 后续做；不得再创建一个平行 worktree。若输出含 `unregistered_worktrees`，先把这些未登记现场及路径告知用户，不静默删除。
   - **Claude Code**:先检查 `git status --porcelain`。只有 git 工程且工作树干净时，才用 `git worktree add` 创建隔离工作树；否则退化为当前树，不得自动 commit/stash。
   - **Codex**:复用当前 Codex Local/Worktree chat 的 checkout，**不在 chat 内再嵌套创建手工 worktree**。需要隔离时应由用户在 Codex App 新建 Worktree chat；Codex Handoff 负责在 Local 与 Worktree 间移动 chat 和代码。
   - **OpenCode**:复用当前 OpenCode session 的 checkout，使用项目内 `sdlc-coder` custom agent；不额外创建嵌套 worktree。
   - 无论使用 worktree 还是当前树，都把实际执行根目录明确写入 Agent prompt；后续路径均相对此根目录解析。
   - 确定执行根后、调用子代理前执行 `run_state.py start`。Claude 手工 worktree 使用 `--mode worktree`；Claude 当前树和 Codex 当前 checkout 使用 `--mode current`。
   - 收益:产物可 `git diff`、可审查、可整体回滚;H3b 可比对 worktree diff 与交接块 `files:` 防谎报。

3. **派发编码 agent**:
   - Claude Code 使用 `Agent`，`subagent_type` 指向插件 coder。
   - Codex 使用 `spawn_agent`，`task_name` 固定为 `sdlc_coder`；prompt 首先要求读取 `${CLAUDE_PLUGIN_ROOT}/agents/coder.md` 的正文作为角色规范。Codex 插件当前不把 Claude agent frontmatter 当作 custom agent profile，故以显式读取方式复用同一角色定义。
   - OpenCode 使用 `task` tool，`subagent_type` 固定为 `sdlc-coder`；项目级 adapter 会在 task 前执行 G2、task 后执行 H3。OpenCode 当前不能在 `SubagentStop` 原地恢复同一个子代理，不合规交接会在 task 返回后明确失败并保留现场。
   - 子代理 prompt **显式列出**需 Read 的路径:coder 角色文件、design-doc、requirement-spec、existing-framework、各 rules、conventions。
   - **把交接块格式文件路径 `${CLAUDE_PLUGIN_ROOT}/references/handoff-format.md` 拼入 Agent prompt**,让 agent 显式 Read 取得格式定义(agent 不会自动加载 skill 的 references,故必须传路径)。
   - 告知 agent:**只在源码范围 Edit/Write,禁碰 docs/**;插件 PreToolUse 做路径硬拦,H3 用 git diff 复校;交付机器可 parse 的**交接块**。
   - 告知 agent:读取工程的 package manager 版本真值（如 `packageManager`），按 conventions 使用对应命令；**未在 design-doc 列出的工具链/构建/测试配置不得修改**，验证失败应进入 `open-issues` 而不是放宽门禁。
   - agent 正文零硬编码栈名,路径全由 prompt 派生。

4. **收交接块**:编码 agent 返回交接块(`compiled` / `files:` / `trace:` / `open-issues`)。
   - Claude Code 交由 H3a(SubagentStop 自纠正)+ H3b(PostToolUse merge 矩阵 + 比对 worktree diff)处理。
   - Codex 的 `spawn_agent` 是异步派发，PostToolUse 发生时最终文本尚未返回。`wait_agent` 得到最终交接块后，dispatcher 必须把交接块正文经 stdin 送入 `python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_result.py" code --project-root "<项目根>" --agent-id "<agent-id>" --session-id "<session-id>"`。退出码 0 才算 H3 完成；非 0 时把输出中的事实发送给同一 agent `followup_task` 自纠正，再 wait 并重试，最多 3 次。
   - OpenCode 项目 adapter 在同步 `task` 返回后的 `tool.execute.after` 调用同一 H3 校验。

5. **输出**:把交接块原样呈现给用户,附 run-id/execution root。Claude 手工 worktree 模式按原流程 merge 并执行 `verify-merge`；Codex Worktree chat 使用宿主 Handoff/Create branch 能力，不在 skill 内手工合并。

## 交接块格式
编码/测试交接块字段定义见插件级共享文件 `${CLAUDE_PLUGIN_ROOT}/references/handoff-format.md`(/code 与 /test 共用)。

## 完成后
H3 通过后,当前派生阶段变为"可测试"。Claude Code 插件模式提示 `/sdlc-pipeline:test`（项目原生模式为 `/sdlc-pipeline-test`）；Codex 提示 `$sdlc-pipeline-test`；OpenCode 提示 `/sdlc-test`。
