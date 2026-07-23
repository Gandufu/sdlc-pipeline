---
name: code
description: >-
  This skill should be used when the user asks to "写代码", "开始编码", "code",
  "/code", or has finished /design and wants to proceed to coding. It acts as
  a dispatcher (派单员): reads the manifest, resolves stack-rules + conventions
  + design-doc paths, opens an isolated git worktree, and dispatches the coder
  agent with those paths embedded in the Agent prompt. Collects the
  machine-parsable handoff block returned by the agent.
---

# /code — 编码(派单员)

约束 #2:agent 拿不到自动加载的 skill 正文。故本 skill 充当**派单员**,把所有资产路径拼进 Agent prompt,编码 agent 启动后**显式 Read**(设计文档 §3.5)。

## 前置
G2 门禁(进入编码前)由 PreToolUse hook H1 在派发编码 agent 时硬拦:`requirement-spec 每个 R-id 在矩阵有 D 映射` 且 `design-doc 必填章节齐`。若被 deny,hook 会以事实陈述告知缺什么,本 skill 不重跑。

## 执行步骤

1. **解析 manifest**:`Read ${CLAUDE_PLUGIN_ROOT}/templates/manifest.json`,按项目所选脚手架(查 CLAUDE.md/上下文或问用户)取得:
   - `stacks` → `${CLAUDE_PLUGIN_ROOT}/rules/<stack>.md` 路径清单
   - `conventions` → `${CLAUDE_PLUGIN_ROOT}/templates/conventions/<id>.md` 路径
   - 项目内路径:`docs/design-doc.md`、`docs/requirement-spec.md`

2. **开 git worktree 隔离**(抄 superpowers,设计文档 §2.3):
   - 在工程内 `git worktree add` 一个隔离工作树(若无 git,跳过此步并告知)。
   - 收益:产物可 `git diff`、可审查、可整体回滚;H3b 可比对 worktree diff 与交接块 `files:` 防谎报。

3. **派发编码 agent**(Agent 工具,subagent_type 指向本插件的编码 agent):
   - Agent prompt **显式列出**需 Read 的路径:design-doc、requirement-spec、各 rules、conventions。
   - **把交接块格式文件路径 `${CLAUDE_PLUGIN_ROOT}/references/handoff-format.md` 拼入 Agent prompt**,让 agent 显式 Read 取得格式定义(agent 不会自动加载 skill 的 references,故必须传路径)。
   - 告知 agent:**只在源码范围 Edit/Write,禁碰 docs/**;插件 PreToolUse 做路径硬拦,H3 用 git diff 复校;交付机器可 parse 的**交接块**。
   - agent 正文零硬编码栈名,路径全由 prompt 派生。

4. **收交接块**:编码 agent 返回交接块(`compiled` / `files:` / `trace:` / `open-issues`)。本 skill 不解析——交由 H3a(SubagentStop 自纠正)+ H3b(PostToolUse merge 矩阵 + 比对 worktree diff)处理。

5. **输出**:把交接块原样呈现给用户,附 worktree 路径,提示用户 review 后 merge 回主树。

## 交接块格式
编码/测试交接块字段定义见插件级共享文件 `${CLAUDE_PLUGIN_ROOT}/references/handoff-format.md`(/code 与 /test 共用)。

## 完成后
H3 通过后,当前派生阶段变为"可测试"。提示可执行 `/sdlc-pipeline:test`。
