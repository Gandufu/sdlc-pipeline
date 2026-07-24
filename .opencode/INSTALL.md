# OpenCode 安装

推荐使用仓库根目录的项目安装器：

```bash
python path/to/sdlc-pipeline/scripts/install_project.py --target . --host opencode
```

它只写当前项目的 `.sdlc-pipeline/` 与 `.opencode/`，不修改用户级
OpenCode 配置。OpenCode 会自动加载 `.opencode/plugins/`、skills、commands
和 agents。

安装后可在 OpenCode 中执行 `/sdlc-verify`，先跑机制验证和当前流水线诊断，再按需
执行 `/sdlc-init`、`/sdlc-requirement`、`/sdlc-design`、`/sdlc-code`、
`/sdlc-test`。日常 adapter 修改优先跑 verify，不必每次完整端到端重跑。

OpenCode 当前没有与 Claude Code/Codex `SubagentStop` 完全等价的“阻止子代理
结束并让原子代理继续自纠正”语义。适配器会在 `task` 返回后运行相同的 H3/H4
证据校验并拒绝不合规交接；这是明确的降级模式，不会假装具备原地续跑能力。
