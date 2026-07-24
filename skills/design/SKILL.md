---
name: design
description: This skill should be used when the user asks to "写设计", "出设计文档", "design", "/design", "$design", or has finished requirement analysis. It reads requirement-spec, framework inventory, and stack rules; atomically publishes design-doc with D-ids and fills R→D. Compatible with Claude Code, Codex and OpenCode.
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
   - 从 `${CLAUDE_PLUGIN_ROOT}/templates/manifest.json` 取所选脚手架的 `stacks`,逐个 `Read ${CLAUDE_PLUGIN_ROOT}/rules/<stack>.md`(如 spring 脚手架 → java.md + spring.md)。**rules 按需 Read,不常驻**。
   - 显式 `Read docs/existing-framework.md`:复用已有模块,不重造。

2. **设计**(主会话推理):
   - 模块划分:每个模块分配 **D-id**(D1、D2…),并标注它满足哪个 R-id。
   - 接口/数据模型:列出关键端点、DTO、核心结构。
   - 显式记录取舍与风险。

3. **落盘**:
   - 把完整设计先写为 `docs/design-doc.md.sdlc-tmp`，再用 `${CLAUDE_PLUGIN_ROOT}/scripts/publish_artifact.py` 原子发布为 `docs/design-doc.md`;**"模块划分"章节必填**(G1 门禁 + 后续 G2 门禁都查它)。
   - 把更新后的矩阵完整写为 `docs/traceability-matrix.md.sdlc-tmp`，再原子发布到正式矩阵；D 列中每个 R 至少映射一个 D(R→D 闭合)。
   - **矩阵一行只写一个 D-id**。一个 R 对应多个 D 时展开为多行（如 `R1 | D1`、`R1 | D3`），禁止把 `D1、D3` 或 `D1, D3` 写在同一单元格。校验脚本会兼容并展开旧格式，但新产物必须使用规范格式。

4. **输出**:返回设计摘要(模块数、R→D 映射表),不返回全文。

## 为何是 skill 不是 agent
设计阶段项目里尚无实现代码,"不该看到实现细节"的隔离理由不成立(设计文档 §2.2)。skill 直接 Write 落盘即可达成"大产物不进主会话"。

## 完成后
当前派生阶段变为"可编码"。Claude Code 插件模式提示 `/sdlc-pipeline:code`（项目原生模式为 `/sdlc-pipeline-code`）；Codex 提示 `$sdlc-pipeline-code`；OpenCode 提示 `/sdlc-code`。G2 门禁由各宿主适配器在派发编码 agent 时硬拦。
