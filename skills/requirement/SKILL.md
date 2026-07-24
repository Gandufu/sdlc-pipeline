---
name: requirement
description: This skill should be used when the user asks to "写需求", "梳理需求", "requirement", "/requirement", "$requirement", or wants to start requirement analysis after init. It drives a grill-style interrogation in the main session, assigns immutable R-ids, and atomically publishes docs/requirement-spec.md. Compatible with Claude Code, Codex and OpenCode.
---

# /requirement — 需求分析

在**主会话**内使用宿主可用的交互提问机制多轮拷问需求,产出 `docs/requirement-spec.md`,锁定不可变的 **R-id**(R1、R2…)。

## 前置检查(G0)
确认 `CLAUDE.md` 或 `AGENTS.md` 已接入 `docs/existing-framework.md`。未初始化则停止，提示先执行对应宿主的 init skill。

## 执行步骤

1. **加载填充模板**:`Read ${CLAUDE_PLUGIN_ROOT}/templates/docs/requirement-spec.md` 取得章节结构。

2. **grill 式拷问**(主会话；有专用提问工具时使用，否则直接询问):
   - 围绕"解决什么问题、服务谁、做什么、不做什么"逐轮追问。
   - 每个候选决策给可选项,push back 模糊回答,直到产出可验收的需求条目。
   - 显式 `Read docs/existing-framework.md`:已有能力不要重复提需求。

3. **分配 R-id**:每条独立需求分配唯一 R-id,**锁定后不可变**。需求标题一句话,验收标准明确(可被测试 agent 走查)。

4. **落盘**:先把完整内容写为 `docs/requirement-spec.md.sdlc-tmp`，再执行 `python "${CLAUDE_PLUGIN_ROOT}/scripts/publish_artifact.py" --project-root "<项目根>" --source "docs/requirement-spec.md.sdlc-tmp" --target "docs/requirement-spec.md"` 原子发布。需求清单表格必须含 R-id 列；写临时文件中断时，旧正式文件不会变成半文件。

5. **同时初始化追溯矩阵**(必做,后续 G1 门禁依赖):按同样方式先写 `docs/traceability-matrix.md.sdlc-tmp`，再用 `publish_artifact.py` 原子发布到 `docs/traceability-matrix.md`；R 列已填、D 列待 `/design`。

6. **输出**:返回需求条数、R-id 清单与关键 open questions 的结构化摘要(不返回全文,避免撑爆主会话)。

## 约束
- 需求留在主会话:与用户交互不可,subagent 黑盒不行。
- R-id 一旦写定,后续阶段(设计/编码/测试)只能引用,不能改。

## 完成后
当前派生阶段变为"设计中"。Claude Code 插件模式提示 `/sdlc-pipeline:design`（项目原生模式为 `/sdlc-pipeline-design`）；Codex 提示 `$sdlc-pipeline-design`；OpenCode 提示 `/sdlc-design`。
