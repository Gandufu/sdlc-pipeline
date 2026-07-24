---
name: verify
description: This skill should be used when the user asks to "验证插件", "跑插件测试", "快速验证", "可观测诊断", "Claude 怎么跑", "OpenCode 怎么验证", "/verify", "$verify", or wants a fast host wiring check without rerunning the full SDLC end-to-end flow. It explains Claude Code project-level execution and runs deterministic mechanism checks before optional host smoke tests.
---

# /verify — 插件机制验证与宿主冒烟

这是一个非阶段 skill。它不推进 `init → requirement → design → code → test`,
不修改需求、设计、矩阵或业务代码；它只验证插件机制、项目级安装接线和当前流水线
可观测状态。

## 目标

- 快速回答“插件是不是可调试、可观察、可复跑”。
- 给 Claude Code、Codex、OpenCode 一个统一验证入口。
- 避免每次修改 hook/skill/adapter 都重跑完整 LLM E2E。

## 必做验证(L1/L1b/L3)

在插件源码仓库中执行：

```bash
python tests/test_pipeline.py
python tests/test_project_install.py
python scripts/inspect_pipeline.py --project-root .
```

若安装到业务项目后验证，把第三条的 `--project-root .` 换成业务项目根目录。
业务项目内也可以直接使用项目运行时：

```bash
python .sdlc-pipeline/scripts/inspect_pipeline.py --project-root .
```

## Claude Code 怎么跑

Claude 有三种常用方式，优先级如下：

1. 项目原生安装，适合验证业务项目接线：

   ```bash
   python <插件源码目录>/scripts/install_project.py --target . --host claude --force
   claude
   ```

   进入项目后调用 `/sdlc-pipeline-verify`。阶段入口是
   `/sdlc-pipeline-init`、`/sdlc-pipeline-requirement`、
   `/sdlc-pipeline-design`、`/sdlc-pipeline-code`、`/sdlc-pipeline-test`。

2. 源码开发加载，适合看插件源码结构是否被 Claude 发现：

   ```bash
   claude --plugin-dir <插件源码目录>
   claude --plugin-dir <插件源码目录> plugin details sdlc-pipeline
   ```

   这种模式使用插件命名空间入口 `/sdlc-pipeline:verify`。

3. 本地 marketplace 项目级安装，适合模拟发布形态：

   ```bash
   claude plugin marketplace add <插件源码目录> --scope project
   claude plugin install sdlc-pipeline@sdlc-pipeline-local --scope project
   claude plugin details sdlc-pipeline@sdlc-pipeline-local
   ```

   仍然在目标项目内运行，`--scope project` 写入项目配置。

建议用 `claude --debug` 观察 hook 输入里的 `cwd`、`CLAUDE_PROJECT_DIR`、
`agent_type` 和交接块校验结果。修改插件后执行 `/reload-plugins` 或重启 Claude。

## OpenCode 怎么验证

在目标业务项目执行：

```bash
python <插件源码目录>/scripts/install_project.py --target . --host opencode --force
opencode
```

进入 OpenCode 后调用 `/sdlc-verify`。阶段入口是 `/sdlc-init`、
`/sdlc-requirement`、`/sdlc-design`、`/sdlc-code`、`/sdlc-test`。

OpenCode 当前没有 Claude/Codex 等价的 SubagentStop 原地自纠正语义；验证时要把
不合规 task 返回后的失败视为预期降级，而不是伪装成同一 agent 续跑。

## 可选宿主冒烟(L4)

只在宿主 adapter、hook matcher 或 agent 接线变化后做。新建一个临时项目，不要在
插件源码目录里跑业务流程：

```bash
mkdir D:/workspace/sdlc-pipeline-smoke
cd D:/workspace/sdlc-pipeline-smoke
git init
python <插件源码目录>/scripts/install_project.py --target . --host all
```

然后分别在目标宿主中调用 verify，再只跑一个最小阶段或只检查发现结果。完整
`init → requirement → design → code → test` 属于 L5 发布候选验证，不作为日常回归。

## 输出格式

向用户报告：

- L1/L1b 命令是否通过。
- `inspect_pipeline.py` 当前 `phase`、`missing_steps`、活动 run、execution root、
  worktree 残留是否异常。
- Claude/OpenCode 发现了哪些 skill/command/agent/hook。
- 若跳过 L4/L5，说明原因。
