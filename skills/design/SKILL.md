---
name: design
description: This skill should be used when the user asks to "写设计", "出设计文档", "design", "/design", or has finished /requirement and wants to proceed to design. It reads requirement-spec plus stack rules, writes docs/design-doc.md with D-ids, and fills the R→D column of the traceability matrix. Stays in the main session (no implementation code exists yet, so no isolation need for an agent).
---

# /design — 设计

在**主会话**内基于需求与栈规约产出设计文档,分配 **D-id**,完成追溯矩阵的 R→D 映射。

## 前置检查(G1:skill 内自查)
- `docs/requirement-spec.md` 存在且每个 R-id 齐全。
- 必填章节(背景/范围/需求清单/验收标准)非空。
- 任一缺失 → 停止,事实陈述缺什么(不写命令式),提示先补需求。

## 执行步骤

1. **加载资产**:
   - `Read docs/requirement-spec.md`(需求)。
   - `Read ${CLAUDE_PLUGIN_ROOT}/templates/docs/design-doc.md`(填充模板)。
   - 从 `templates/manifest.json` 取所选脚手架的 `stacks`,逐个 `Read ${CLAUDE_PLUGIN_ROOT}/rules/<stack>.md`(如 spring 脚手架 → java.md + spring.md)。**rules 按需 Read,不常驻**。
   - 参考 `@docs/existing-framework.md`(已在上下文):复用已有模块,不重造。

2. **设计**(主会话推理):
   - 模块划分:每个模块分配 **D-id**(D1、D2…),并标注它满足哪个 R-id。
   - 接口/数据模型:列出关键端点、DTO、核心结构。
   - 显式记录取舍与风险。

3. **落盘**:
   - 写 `docs/design-doc.md`,**"模块划分"章节必填**(G1 门禁 + 后续 G2 门禁都查它)。
   - 更新 `docs/traceability-matrix.md` 的 D 列:每个 R 至少映射一个 D(R→D 闭合)。

4. **输出**:返回设计摘要(模块数、R→D 映射表),不返回全文。

## 为何是 skill 不是 agent
设计阶段项目里尚无实现代码,"不该看到实现细节"的隔离理由不成立(设计文档 §2.2)。skill 直接 Write 落盘即可达成"大产物不进主会话"。

## 完成后
当前派生阶段变为"可编码"。提示可执行 `/sdlc-pipeline:code`。G2 门禁(进入编码前的追溯闭合)由 PreToolUse hook 在派发编码 agent 时硬拦。
