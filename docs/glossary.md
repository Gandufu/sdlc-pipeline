# 术语表

| 术语 | 含义 |
|---|---|
| Primary agent | `sdlc-main`，与用户交互并编排阶段；不是 subagent |
| Subagent | 独立上下文的 `sdlc-coder` 或 `sdlc-executor` |
| Gate | 阶段切换前由 Python core 执行的硬校验 |
| Lifecycle | install、compile、start、stop、restart、health、artifact、test 的确定性契约 |
| Scaffold | 模板版本、关键 hash、protected path、extension point 与 allowed path 契约 |
| Template asset | 独立 Git 仓库维护的模板源码、依赖、文档、测试和 lifecycle/scaffold 契约 |
| Template registry | 插件 `templates/manifest.json` 中包含 ID、技术栈、active rules、能力和 Git 数据源的元数据目录 |
| Registered template | 用户在无参数 `/sdlc-init` 问答中选择、随后由 registry 解析并导入的条目，不代表插件内嵌源码 |
| Active rules | init 根据所选模板生成的 `.sdlc-pipeline/rules/active.json`；只有其中规则进入 agent context |
| Grilling | 逐分支、一次一问的需求决策访谈；事实先查环境，每题给推荐答案，用户确认共享理解前不行动 |
| Seam | 模块或系统可被稳定验证的边界；设计和测试优先复用最高层、最少数量的既有 seam |
| Extension point | 设计允许扩展而不修改脚手架核心的 seam |
| Protected path | 默认禁止 coder 修改、需要升级为 standard 流程的路径 |
| Context pack | 按影响集生成、约 30k 字符分包的最小 agent 输入 |
| Run | `.sdlc-pipeline/runs` 中的 PID、日志、handoff、Token 和候选现场 |
| Manifest | `docs/sdlc/versions/Vxxxx/manifest.json` 的版本证据 |
| Evidence over claims | 以 runner/Git 证据为准，不采信 agent 的完成声明 |

追溯 ID：

| ID | 含义 | 格式 |
|---|---|---|
| R-id | Requirement | `R-0001` |
| D-id | Design | `D-0001` |
| C | 实际代码路径集合；不另造易漂移 C-id | `src/...` |
| T-id | Test case | `T-0001` |
