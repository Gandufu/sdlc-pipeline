---
name: test
description: >-
  This skill should be used when the user asks to "走查代码", "测试", "test",
  "/test", "$test", or has finished /code and wants a requirement-conformance review.
  It dispatches the tester agent as a fresh-eye reviewer (carrying requirement
  + design + code, deliberately NOT seeing the coder's internal plan), and
  collects a two-axis (standards/spec) review-findings handoff. MVP scope:
  requirement-conformance review only; interface/Playwright execution is
  deferred.
---

# /test — 测试(派单员, MVP 走查 only)

派发**测试 agent**做需求符合性走查(fresh eye)。本版 MVP:只行使走查,接口测试/Playwright 的写入与执行能力均 **defer**(设计文档 §5.6)。

## 前置
G4 门禁(进入测试前)由 PreToolUse hook H2 硬拦:G3 已通过(D→C 全映射、compiled=pass)。若被 deny,事实陈述告知上一门禁缺什么,本 skill 不重跑。

## 执行步骤

1. **解析 manifest**(同 `/code`):读取 `${CLAUDE_PLUGIN_ROOT}/templates/manifest.json`，取得 rules/convention 路径、项目内 design-doc / requirement-spec 路径。**不**传编码 agent 的 plan 思路(fresh eye)。

2. **派发测试 agent**:
   - Claude Code 使用 `Agent`，`subagent_type` 指向插件 tester；Codex 使用 `spawn_agent`，`task_name` 固定为 `sdlc_tester`，并要求子代理先读取 `${CLAUDE_PLUGIN_ROOT}/agents/tester.md` 正文；OpenCode 使用 `task` tool，`subagent_type` 固定为 `sdlc-tester`。
   - Agent prompt **显式列出**需 Read 的路径:requirement-spec、design-doc、各 rules、被 review 的源码(worktree 或主树)、`${CLAUDE_PLUGIN_ROOT}/templates/docs/test-plan.md`。
   - **把交接块格式文件路径 `${CLAUDE_PLUGIN_ROOT}/references/handoff-format.md` 拼入 Agent prompt**,让 agent 显式 Read 取得双轴 review-findings 的格式定义(测试 agent 交接块章节)。
   - Claude tester frontmatter 仅开放 Read/Grep/Glob；Codex 侧由 SubagentStart 记录 agent_id，项目 hook 硬拦 `apply_patch`/Write/Edit 和含文件变更信号的 Bash，允许 Get-Content/rg/git diff 等只读 Bash，H4 以代码指纹复核；OpenCode tester agent 用 permissions 禁止 edit，并由 H4 在 task 返回后复核交接证据；交付双轴 review-findings 交接块。
   - 明确 MVP 任务边界:只做需求符合性走查(Read/Grep 判断代码是否对题),**不**写/跑接口或 E2E 测试。

3. **收交接块**:测试 agent 返回 `review-findings`(standards 轴 + spec 轴)。
   - Claude Code 交由 H4a/H4b hooks 处理。
   - Codex 的最终文本在异步 wait 后才到达；dispatcher 必须把交接块正文经 stdin 送入 `python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_result.py" test --project-root "<项目根>" --agent-id "<agent-id>" --session-id "<session-id>"`。退出码 0 才算 H4/指纹复核/矩阵 merge 完成；非 0 时 follow-up 同一 tester 自纠正，最多 3 次。
   - OpenCode 由同步 `task` 返回后的 `tool.execute.after` 执行 H4。

4. **输出**:把 review-findings 原样呈现给用户,标注严重度分布与 spec 偏离点。Claude 手工 worktree 模式通过后进入 `merge_pending` 并要求 `verify-merge`；Codex/OpenCode 当前 checkout 通过后标记 complete，后续移动代码使用宿主的分支/worktree 能力。

## 双轴走查语义(抄 mattpocock/code-review)
- **standards 轴**:代码是否符合 rules/<stack>.md 与 conventions。
- **spec 轴**:代码是否满足 requirement-spec / design-doc(偏离标注对应 R-id/D-id)。
- 两轴都必须非空(H4a 校验)。
- 交接块字段定义见 `${CLAUDE_PLUGIN_ROOT}/references/handoff-format.md`(与 /code 共享)。

## 完成后
H4 通过且没有 high/medium finding 后,MVP 闭合判据达成,当前派生阶段为"闭环"。存在 high/medium finding 时派生为"测试未通过",由用户决定回到设计还是编码。
