# Feature Contract 澄清规则

先读取项目、scaffold、active policy、lifecycle 与已摄取来源；能从事实得到的答案不询问用户。

只把以下情况视为阻塞决策：

1. 会改变功能范围或非范围；
2. 会改变可观察验收结果；
3. 会改变公开接口、数据来源或错误语义。

一次只问一个问题，通常在三题内完成。若仍有会改变范围、验收或公开接口的阻塞决策，可以继续，
但必须向用户说明影响。每次回答后保存 checkpoint。非阻塞未知项写入 assumptions 或 risks。

候选 Feature Contract 以一个可交付功能为单位，必须简明包含：目标、角色、范围、非范围、
领域数据、简洁主流程、必要异常流程、AC、模块、接口字段、data contract、extension point
和 AC 到 unit/integration 逻辑测试键的验证映射。功能和验收 ID 使用 `F-xxxx`、`AC-xxxx`。
正式文档使用项目配置语言（默认中文），代码标识、协议字段和原文保持原样。

推荐方案与正式发布是两个独立动作：

1. 用户说“采用推荐”时，只把选项和理由保存到 checkpoint，继续生成候选；
2. 展示完整候选及其 source refs、范围、AC、接口与验证映射；
3. 只有用户明确说“确认发布”时，才把 checkpoint 标为 confirmed 并调用 publish。

不得把“采用推荐”“继续”“没问题”等局部答复推断为发布授权。发布前读取
`.sdlc-pipeline/schemas/feature-contract.schema.json`，然后只调用一次
`sdlc_publish_contract`。Core 负责 Schema 校验、来源 anchor 校验和
requirements/design/test-plan 三视图原子投影。
