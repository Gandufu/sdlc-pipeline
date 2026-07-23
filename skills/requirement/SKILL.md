---
name: requirement
description: This skill should be used when the user asks to "写需求", "梳理需求", "requirement", "/requirement", or wants to start requirement analysis after /init. It drives a grill-style interrogation in the main session to extract requirements, assigns immutable R-ids, and writes docs/requirement-spec.md. Stays in the main session (not a subagent) because requirement interrogation needs interactive user dialogue.
---

# /requirement — 需求分析

在**主会话**内用 AskUserQuestion 多轮拷问需求,产出 `docs/requirement-spec.md`,锁定不可变的 **R-id**(R1、R2…)。

## 前置检查(G0)
确认 `CLAUDE.md` 含 `@docs/existing-framework.md`(已 /init)。未初始化则停止,提示先执行 `/init`。

## 执行步骤

1. **加载填充模板**:`Read ${CLAUDE_PLUGIN_ROOT}/templates/docs/requirement-spec.md` 取得章节结构。

2. **grill 式拷问**(主会话,AskUserQuestion 为主):
   - 围绕"解决什么问题、服务谁、做什么、不做什么"逐轮追问。
   - 每个候选决策给可选项,push back 模糊回答,直到产出可验收的需求条目。
   - 参考 `@docs/existing-framework.md`(已在上下文):已有能力不要重复提需求。

3. **分配 R-id**:每条独立需求分配唯一 R-id,**锁定后不可变**。需求标题一句话,验收标准明确(可被测试 agent 走查)。

4. **落盘**:把拷问结果按模板结构写为 `docs/requirement-spec.md`。需求清单表格必须含 R-id 列。

5. **同时初始化追溯矩阵**(必做,后续 G1 门禁依赖):写入 `docs/traceability-matrix.md`(可从模板 `templates/docs/traceability-matrix.md` 复制初始结构),R 列已填、D 列待 `/design`。

6. **输出**:返回需求条数、R-id 清单与关键 open questions 的结构化摘要(不返回全文,避免撑爆主会话)。

## 约束
- 需求留在主会话:与用户交互不可,subagent 黑盒不行。
- R-id 一旦写定,后续阶段(设计/编码/测试)只能引用,不能改。

## 完成后
当前派生阶段变为"设计中"。提示可执行 `/sdlc-pipeline:design`。
