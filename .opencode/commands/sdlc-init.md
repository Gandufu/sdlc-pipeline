---
description: 在当前项目目录导入模板并完成 install/compile/start/verify/stop 验收
agent: sdlc-main
subtask: false
---

执行 SDLC init。参数为：`$ARGUMENTS`

始终以当前 OpenCode 项目根目录作为目标目录和 evidence root。不得要求用户切换到插件仓库，
不得接收 target 路径，也不得在其他目录 clone 后再要求打开新会话。
先解析 `$ARGUMENTS`。显式 `--github` 直接使用地址/ref；其他非空参数先读取
`.sdlc-pipeline/templates/manifest.json`，优先按 ID 精确匹配，否则根据
name/description/stacks/capabilities 与用户需求选择。只有唯一匹配时才能自动选择；零个或多个
匹配必须先向用户展示候选并要求确认，不得猜测。选定后只调用一次 init：第一次调用就必须把
template 或 github/ref 放入 options；不得先执行无 options 的 init 来“探测模式”。`.sdlc-pipeline/`
目录本身只代表 adapter 已安装，不能据此判定为已有项目；已有项目必须同时存在项目根目录下的
`.sdlc-pipeline/lifecycle.json` 和 `.sdlc-pipeline/scaffold.json`。
必须由主会话直接调用 `sdlc_lifecycle(action=init)` 完成整个 init，不得改用 bash、Python
runner 或让用户复制任何手工命令。若 `sdlc_lifecycle` 不在当前会话工具表中，应明确报告
插件启动失败并停止；不得伪造门禁证据或提供 runner 降级路径。

支持三种模式：

1. 已登记模板：`<template>`，例如 `/sdlc-init sdlc-electron-scaffold`。调用
   `sdlc_lifecycle(action=init, options={"template":"sdlc-electron-scaffold"})`；runner 从插件
   `templates/manifest.json` 读取 repository/ref，clone 后导入当前空目录并保留模板 Git
   历史。插件只携带数据源元数据，不携带模板源码或模板专属资产。
2. GitHub 模板：`--github <repo> [ref]`，例如
   `/sdlc-init --github https://github.com/acme/service-template.git main`。调用
   `sdlc_lifecycle(action=init, options={"github":"...","ref":"main"})`；将该模板导入当前目录，
   保留 Git 历史。GitHub 模板必须携带 `.sdlc-pipeline/lifecycle.json` 与
   `.sdlc-pipeline/scaffold.json`，不能携带插件的 `.opencode` 或 `opencode.json`。
3. 已有项目：不带参数。要求当前项目已经有 lifecycle/scaffold，调用 init 时不传 options。

OpenCode 桌面版已安装时，只探测其项目发现能力，不尝试重复安装 OpenCode。执行
`/sdlc-init` 即授权 runner 自动探测并安装模板 `lifecycle.json` 明确声明且白名单允许的缺失
系统工具；随后自动继续 install/compile/start/health/artifact/stop，不再要求用户补充命令或
进行第二次确认。模板未声明受控安装命令时必须失败并返回真实日志。

最终展示 `init-report` 的工具、install、compile、PID、health、artifact hash、stop 和 Git
基线；只有所有 mandatory 检查通过才可进入 `/sdlc-spec`。
