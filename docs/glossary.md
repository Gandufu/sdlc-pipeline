# 术语表

| 术语 | 含义 |
|---|---|
| Primary agent | `sdlc-main`，与用户交互并编排阶段；不是 subagent |
| Subagent | 独立上下文的 `sdlc-coder` 或 `sdlc-executor` |
| Gate | 阶段切换前由 Python core 执行的硬校验 |
| Lifecycle | install、compile、start、stop、restart、health、artifact、test 的确定性契约 |
| Scaffold | 模板版本、关键 hash、protected path、extension point 与 allowed path 契约 |
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
