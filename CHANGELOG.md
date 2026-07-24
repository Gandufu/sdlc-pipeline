# Changelog

## 0.5.0 - 2026-07-25

- 正式收敛为 OpenCode-only，兼容 OpenCode 桌面版项目发现。
- 固定一个 primary agent 和 coder/executor 两个 subagent。
- 合并 requirement/design 为 `/sdlc-spec`，保留三份独立产物。
- status/finalize 改为内部工具。
- 引入 lifecycle/scaffold 契约、R/D/C/T、固定渲染、Token 和 Vxxxx manifest。
- code 强制真实 compile/restart/health/artifact，test 强制逐 T-id runner 证据。
- 删除 Claude/Codex active manifests、hook 模拟、experimental 注入和旧浅脚本。
