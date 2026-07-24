---
description: Clone 项目、安装 OpenCode adapter 与脚手架，并完成 install/compile/start/verify/stop
agent: sdlc-main
subtask: false
---

执行 SDLC init。参数为：`$ARGUMENTS`

必须解析为 `<repo> <ref> <target> [template]`；template 未提供时先根据项目类型选择并说明。
调用 `sdlc_lifecycle(action=init)`，传入 repo、ref、target、template。OpenCode 桌面版已安装，
只探测其项目发现能力；不要尝试重复安装 OpenCode。缺少系统工具时先展示精确工具和受控
安装命令，单独询问用户；只有明确确认后才调用 `action=system_install` 且传 `approved=true`，
同时传回 `target_root`，随后在同一 target_root 重新执行 init。
最终展示 init-report 的工具、install、compile、PID、health、artifact hash 与 stop 结果。
