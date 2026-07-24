---
name: init
description: This skill should be used when the user asks to "初始化项目", "init project", "/init", "$init", or the project has not been scaffolded yet. It reads the scaffold manifest, lets the user pick a scaffold, copies the skeleton without overwriting files, and connects docs/existing-framework.md through both CLAUDE.md and AGENTS.md for Claude Code, Codex and OpenCode compatibility.
---

# /init — 初始化项目脚手架

四阶段 SDLC 流水线的入口。把所选脚手架的骨架铺到工程根,并接入"现有框架能力清单"常驻上下文。

## 前置检查(G0)
若工程根 `CLAUDE.md` 已含 `@docs/existing-framework.md`，或 `AGENTS.md` 已含 `docs/existing-framework.md` 能力清单说明，说明已初始化。停止并告知用户当前已初始化；如需重选脚手架需人工干预。

## 执行步骤

1. **读取脚手架注册表**:`Read ${CLAUDE_PLUGIN_ROOT}/templates/manifest.json`。得到可选脚手架列表(每条含 `id`/`name`/`description`/`stacks`/`path`/`conventions`)。

2. **选择脚手架**:使用当前宿主可用的交互提问机制让用户从注册表条目中选一个；若没有专用提问工具则直接询问。若只有一条,仍确认。

3. **拷贝骨架**(钉死的拷贝语义,见设计文档 §3.4):
   - 把 `${CLAUDE_PLUGIN_ROOT}/templates/<scaffold-id>/*` **整目录拷到工程根**。
   - **不覆盖**任何已存在文件(目标存在则跳过,跳过项要列给用户)。
   - 骨架内的 `docs/existing-framework.md` 自然落到 `工程/docs/existing-framework.md`。
   - **不要拷** `templates/conventions/`、`templates/docs/`(它们是按需 Read 的资产,不进项目)。

4. **接入能力清单（三宿主共享项目事实）**:
   - 检查工程根 `CLAUDE.md`；仅当下列引用尚不存在时才在末尾追加，避免重复执行 `/init` 产生重复标记:
   ```
   @docs/existing-framework.md
   ```
     Claude Code 的 `@` 引用会使其在会话启动时自动加载。
   - 检查工程根 `AGENTS.md`；仅当能力清单段尚不存在时追加：
     ```
     ## SDLC Pipeline 能力清单
     执行 requirement、design、code、test 阶段前，读取 docs/existing-framework.md，并优先复用其中已有能力。
     ```
     Codex 自动加载 `AGENTS.md`；具体能力清单仍由各 skill 显式读取，避免依赖宿主的 Markdown include 语法。

5. **输出**:列出拷贝了哪些文件、跳过了哪些,以及所选脚手架的 `stacks`(后续 `/design`、`/code` 据此 Read 对应 rules)。

## 约束
- 零硬编码栈名:不预设"spring",一切从 manifest `id` 派生路径。
- 不覆盖已有文件(贴设计文档"不覆盖已有"不变量)。

## 完成后
告知用户当前派生阶段为"需求中"：
- Claude Code 插件模式执行 `/sdlc-pipeline:requirement`；项目原生安装执行 `/sdlc-pipeline-requirement`。
- Codex 项目 skill 执行 `$sdlc-pipeline-requirement`。
- OpenCode 执行 `/sdlc-requirement`，该 command 会调用项目内 `sdlc-pipeline-requirement` skill。
