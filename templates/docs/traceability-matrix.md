# 追溯矩阵 (Traceability Matrix)

> **填充模板/初始状态**。`/design` 落盘时建立 R→D 列;H3/H4 校验脚本**只写不手改**地把 C、T 列 merge 进来。
> 当前 MVP 闭合判据:**R→D→C 三段闭合** + 双轴 review-findings 合规且没有 high/medium finding。T 列结构保留、内容空。

| R-id (需求) | D-id (设计) | C-id (代码模块/文件) | T-id (测试用例) | 状态 |
|---|---|---|---|---|
| R1 | _(待 /design 填)_ | _(待 H3 merge)_ | _(后续填充)_ | |
| R2 | | | | |

## 全链闭合说明
- **R→D**:`/design` 阶段填写(每个 R 都有至少一个 D 映射)。
- **D→C**:编码 agent 交接块吐出,H3 脚本 merge。
- **R→D→C**:MVP 闭合判据(H4 校验)。
- **C→T**:接口/Playwright 测试落地后由测试 agent 交接块 merge(本版 defer)。
