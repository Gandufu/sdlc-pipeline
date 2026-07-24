---
description: Clone 项目、安装 OpenCode adapter 与脚手架，并完成 install/compile/start/verify/stop
agent: sdlc-main
subtask: false
---

执行 SDLC init。参数为：`$ARGUMENTS`

支持两种模式：

1. bootstrap：`<repo> <ref> <target> [template]`。template 未提供时先根据项目类型选择并说明。
2. 当前项目：`--current`。要求当前项目已有 lifecycle/scaffold，调用 init 时不传 repo。

bootstrap 模式调用 `sdlc_lifecycle(action=init)`，传入 repo、ref、target、template。
成功后明确提示用户用 OpenCode 打开 target，再执行 `/sdlc-spec`，不得在插件仓库会话继续后续阶段。
当前项目模式直接对当前 root 执行 init。

OpenCode 桌面版已安装时，
只探测其项目发现能力；不要尝试重复安装 OpenCode。缺少系统工具时先展示精确工具和受控
安装命令，单独询问用户；只有明确确认后才调用 `action=system_install` 且传 `approved=true`，
同时传回 `target_root`，随后在同一 target_root 重新执行 init。
最终展示 init-report 的工具、install、compile、PID、health、artifact hash 与 stop 结果。
