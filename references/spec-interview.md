# Spec 拷问与文档风格契约

本契约明确派生自 `mattpocock/skills` 的
[`grilling`](https://github.com/mattpocock/skills/blob/main/skills/productivity/grilling/SKILL.md)、
[`grill-with-docs`](https://github.com/mattpocock/skills/blob/main/skills/engineering/grill-with-docs/SKILL.md)
和 [`to-spec`](https://github.com/mattpocock/skills/blob/main/skills/engineering/to-spec/SKILL.md)。保留其核心：
小而可组合、用户控制决策、先对齐再行动、建立共享语言、围绕测试 seam 形成快速反馈。
本插件的适配是把“拷问”和“文档综合”编排在一个 `/sdlc-spec` 用户阶段内，但以用户确认作为
硬分界；正式产物继续由确定性 Python core 发布，不复制外部项目的 issue-tracker 流程。

## 交互规则

1. 先从项目文件、`sdlc_status`、scaffold、active rules 和 lifecycle tests 查明事实；能查到的事实不得反问用户。
2. 只把产品目标、范围、取舍、验收口径等决策交给用户。一次只问一个问题，等待回答后再沿决策树继续。
3. 每个问题使用 OpenCode `question` 工具，提供 2–3 个互斥候选答案并允许自定义答案。把首选答案的 label 标记为“（推荐）”，description 说明推荐依据和影响；不得替用户决定。
4. 前一答案会改变后一问题时，先更新已确认事实、假设、风险和待决策分支，再提出下一问。不得一次提交问题清单。
5. 覆盖目标、用户与场景、范围/非范围、业务规则、失败路径、安全与数据边界、兼容性、验收标准、设计取舍和测试层级。没有实际分歧的分支直接记录，不制造问题。
6. 所有 blocking 问题解决后，展示共享理解摘要；只有用户明确确认“理解一致并生成 spec”后，才构造并发布正式产物。

## 候选答案格式

- `label`：1–5 个词；推荐项以“（推荐）”结尾。
- `description`：一句话说明适用条件、代价或后续影响。
- `custom`：保持 `true`，允许用户输入不在候选中的答案。
- `multiple`：默认 `false`；只有问题本身允许并列选择时才设为 `true`。

## 正式产物

发布前读取 `.sdlc-pipeline/schemas/spec.schema.json`。把完整原始输入与访谈结论写入一个结构化 payload，设置 `spec_confirmed=true` 后仅调用一次 `sdlc_publish(kind=spec)`。Python core 负责校验并原子生成：

- `docs/sdlc/current/requirements.json` 与 `requirements.md`：原始输入、分析与边界、规范化需求和验收标准；
- `docs/sdlc/current/design.json` 与 `design.md`：R→D、模块、真实 extension point、允许路径、接口与数据模型；
- `docs/sdlc/current/test-plan.json` 与 `test-plan.md`：R/D→T、层级、前置、输入、预期、mandatory 和 lifecycle test 逻辑键。

Markdown 标题、章节顺序和表述风格由 Python renderer 固定，agent 不直接编辑正式 Markdown。正式说明使用中文；原始输入、代码标识、命令、协议字段和用户要求保留的英文保持原样。
