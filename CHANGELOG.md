# Changelog

## 0.7.0 - 2026-07-25

- spec 增加原始输入、结构化分析与发布前人工确认门禁。
- code 在 coder 派发和 compile/restart 两层拒绝未解决的 blocking 问题。
- requirements Markdown 与版本交付摘要改为 runner 固定渲染。
- context pack 以 hash 投影原始长需求，减少 coder/executor 重复 Token。
- 补充 Schema、门禁、渲染、Token/context-pack 与完整版本闭环回归测试。

## 0.6.1 - 2026-07-25

- 项目 adapter 安装改为可从 GitHub raw 地址下载单文件 installer 后直接执行。
- 单文件 installer 自动拉取指定仓库/ref 的完整发行内容，避免要求用户预先设置
  `SDLC_PIPELINE_ROOT` 或 clone 本插件仓库。

## 0.6.0 - 2026-07-25

- `/sdlc-init` 改为始终在当前项目目录执行，移除 repo/ref/target 跨目录 bootstrap。
- 新项目支持内置模板或携带 lifecycle/scaffold 契约的 GitHub 模板；GitHub 模板保留 Git 历史。
- 内置模板建立 Git 基线，确保后续版本 manifest 有可追溯的起点。
- 更新命令、README、架构真值与回归测试；同步修复两个内置模板的 scaffold hash。

## 0.5.0 - 2026-07-25

- 正式收敛为 OpenCode-only，兼容 OpenCode 桌面版项目发现。
- 固定一个 primary agent 和 coder/executor 两个 subagent。
- 合并 requirement/design 为 `/sdlc-spec`，保留三份独立产物。
- status/finalize 改为内部工具。
- 引入 lifecycle/scaffold 契约、R/D/C/T、固定渲染、Token 和 Vxxxx manifest。
- code 强制真实 compile/restart/health/artifact，test 强制逐 T-id runner 证据。
- 删除 Claude/Codex active manifests、hook 模拟、experimental 注入和旧浅脚本。
