# sdlc-pipeline

"需求分析 → 设计 → 编码 → 测试" 四阶段闭环研发流水线插件,按 plugin-dev 与 Claude 官方最佳实践从零设计。

## 核心理念

- **evidence over claims**:可机器校验的约束(追溯矩阵、交接块、状态)全写成校验脚本,不靠 LLM 自觉。
- **路径全派生**:skill/agent 正文零硬编码栈名,一切从 `templates/manifest.json` + 所选脚手架派生。
- **hooks 守纪律**:hooks 只做生命周期确定性控制点(PreToolUse deny 事前拦截 / PostToolUse 注入事实 / SubagentStop 自纠正),不做工作流编排;阶段推进靠用户显式命令 + agent 工具限制。
- **skill 数量与脚手架解耦**:skill 恒定 5 个,加脚手架只改 `templates/` + manifest(数据),不加 skill。

## 前置条件

- Claude Code
- **Python 3.10+**(校验脚本运行时;hooks.json 以 `python` 调用,若你的环境是 `python3`,请相应调整 hooks.json 命令)

## 安装与测试

```bash
# 本地加载测试
claude --plugin-dir D:/workspace/sdlc-plipeline-ref
# 或拷到项目 .claude-plugin/ 内做项目级测试
```

hooks 在会话启动时加载,改 `hooks/hooks.json` 需重启 Claude Code 生效。用 `claude --debug` 查看 hook 执行日志。

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

## 组件

| 类型 | 数量 | 说明 |
|---|---|---|
| user-invoked skill | 5 | 四阶段命令 + init |
| agent | 2 | 编码 agent(工具限制:禁碰 docs)+ 测试 agent(工具限制:禁 Edit 源码) |
| hook handler | 10 | G2/G4 门禁 + agent 写入保护 + H3/H4 交接块自纠正与 merge + H5/H6/H7 派生状态注入 |
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

## 目录结构

```
plugin-root/
  .claude-plugin/plugin.json    # manifest
  rules/                        # 栈级规约(按 manifest stacks 按需 Read)
    java.md spring.md vue.md
  templates/
    manifest.json               # 脚手架注册表(id/stacks/path/conventions)
    docs/                       # 平台统一填充模板(不拷,按需 Read)
    conventions/                # 脚手架级编码约定(与脚手架平级,防误拷)
    <scaffold-id>/              # 脚手架骨架(整目录拷到工程根)
      docs/existing-framework.md
      src/...
  skills/   agents/   hooks/    # 编排(从零设计)
  scripts/                      # 校验脚本 + 共享库 _lib.py
```

## 扩展

| 扩展类型 | 要改的 | 不该动的 |
|---|---|---|
| 新增栈 | `rules/<stack>.md` | skill/agent/manifest 既有条目 |
| 新增脚手架 | `templates/<id>/` + `conventions/<id>.md` + manifest 一条 | rules/、skill/agent 正文 |
| 新增文档模板 | `templates/docs/<name>.md` + 使用处 Read | manifest、脚手架 |

## 参考

设计文档:`docs/design/参照版SDLC流水线插件设计方案.md`(grill 式拷问产出,逐轮决策溯源)。
