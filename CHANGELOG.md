# Changelog

## 0.12.1 - 2026-07-28

- 清理模板 registry 与活动设计文档中遗留的旧测试术语，统一为 headless functional。

## 0.12.0 - 2026-07-28

- 安装复制排除 `.opencode/node_modules`，并在模板导入后的 init 再次强制合并
  Vitest/ESLint tooling ignore。
- focused check 改为 T-id 与受控文件 selector，成功和失败均按源码/spec 指纹复用。
- code gate 负责 compile/package 与 lint/typecheck policy；test gate 只执行
  start、readiness、无头浏览器 functional case 和 cleanup。
- 删除活动 E2E/smoke/installer 测试契约，新增 Playwright functional 文件约定。
- Python 与 OpenCode adapter 改为异步、可取消的进程树执行；deadline 会 abort session
  并清理子进程。
- `result.ok=false` 在 journal 中记录为 failed；新增 source anchor query 窄接口。

## 0.11.1 - 2026-07-27

- 安装后校验 template registry 与 rule policy，修复 React policy/schema 漂移。
- 自动合并 Vitest/ESLint 插件目录 ignore，并预登记 tooling config 非业务变更路径。
- 支持显式授权的项目外文本来源 copy + SHA-256 SourceEnvelope 摄取。
- coder dispatch 增加独立 deadline、PID lease、heartbeat 和 status 自动 aborted 回收。
- 将“采用推荐”checkpoint 与“确认发布”授权拆成两个明确交互。
- 同步 OpenCode-first 架构设计真值到 0.11.1 的状态机、工具边界与验证语义。

## 0.11.0 - 2026-07-27

- Context pack 改为 progressive brief/resource manifest，不再嵌入源码和完整规则。
- 增加受控 `focused_check`，让 coder 自主选择 Feature Contract 测试键。
- 增加 hash 失效的 Delivery Memory，只派生项目事实、确认决策和已解决失败指纹。
- OpenCode lifecycle Interface 收窄为 init/focused_check/verify_delivery 三个交付意图。
- 提示词以 skill/reference 为单一真值，agent 和 command 只保留权限与阶段路由。
- 将提问数和主流程长度从绝对硬规则下调为可解释 guidance。

## 0.10.0 - 2026-07-27

- 以单功能 Feature Contract 作为唯一模型规格输入，Core 原子投影三类文档。
- 删除 executor 和插件内所谓 E2E，收敛为唯一 coder 与一次 `verify_delivery`。
- 拆分 source/checkpoint/contract 窄工具，移除模型可控 idempotency key。
- Git diff 自动生成代码与测试追溯映射；增加失败分类、重复失败熔断和交付证据缓存。
- 升级安装时删除遗留 `sdlc-executor.md`。

## 0.9.0 - 2026-07-27

- 修复 dirty worktree fingerprint baseline、真实路径映射与 Windows PID identity，避免重试误判和 PID 复用误杀。
- 增加不可变 spec bundle、原子 current pointer、正式 Draft 2020 Schema runtime validator。
- 增加 durable Run Journal：run/phase/step/attempt/event/idempotency、spec grilling checkpoint 与 abandoned attempt 恢复。
- 将 TypeScript、Electron、React 关键规则升级为 machine policy 和受控 lifecycle verifier。
- 增加 SourceEnvelope、原文 anchor、AC-id 与 R/D/T/文件/测试机器 evidence edge。
- 强制 OpenCode adapter 与 Python core 使用 UTF-8，修复 Windows 中文 checkpoint 传输。

## 0.8.3 - 2026-07-27

- init 根据模板 `rules` 显式生成 active rules manifest，status、AGENTS 与 context pack 只暴露
  当前框架规则，不加载无关 Java/Spring/Vue 规则。
- 恢复源自 `mattpocock/skills` 的 grilling 契约：事实先查、决策归用户、一次一问、推荐答案、
  共享理解确认后才发布。
- 增加 spec interview/reference，command、agent、skill 与 README/设计文档统一引用；设计与测试
  Markdown 继续由 Python core 按固定章节原子渲染。

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
