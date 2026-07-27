---
description: 幂等检查 init，按用户选择的登记模板完成生命周期验收
agent: sdlc-main
subtask: false
---

执行无参数 SDLC init。

第一步调用 `sdlc_status`：

1. `init_state.completed=true`：直接展示已有 init 状态和 evidence 时间并停止，不再调用
   `sdlc_lifecycle`。
2. `init_state.completed=false` 且 `init_state.contracts_present=true`：调用一次
   `sdlc_lifecycle(action=init)`，用于已有项目首次验收或失败后的幂等续跑。
3. `init_state.completed=false` 且 `init_state.contracts_present=false`：读取状态返回的
   `templates` 元数据，向用户展示每个候选的 id、name、description、stacks、rules、capabilities，
   采用问答方式要求用户明确选择。即使只有一个候选也必须等待用户选择，不得自动匹配或猜测。
   用户选择后调用一次
   `sdlc_lifecycle(action=init, options={"template":"<selected-id>"})`。

不得接受 slash command 参数、路径、GitHub 地址或 ref。不得在用户选择前调用 init 做模式探测。
`sdlc_lifecycle` 会继续执行既有的 template import、工具探测与受控安装、
按模板 `rules` 生成 `.sdlc-pipeline/rules/active.json`，再执行
install/compile/start/health/artifact/stop，并生成或保留 `AGENTS.md` 和 `init-report`。
后续 coder/executor 只加载 active rules；发行包中的其他规则文件只是目录，不进入上下文。

最终只展示 init 是否为复用、模板、工具、compile、health、artifact、stop、Git 基线与失败日志；
mandatory 检查通过后进入 `/sdlc-spec`。
