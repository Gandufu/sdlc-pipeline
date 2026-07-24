# heli-terminal-client 脚手架编码约定

> 本文件不拷入目标项目。`/code` 从 `${CLAUDE_PLUGIN_ROOT}` 读取，并与
> `rules/typescript.md`、`rules/electron.md`、`rules/react.md` 一起传给编码 agent。

## Monorepo 边界

```text
packages/
  shared/    # IPC channel、DTO、错误码、跨进程异常
  main/      # Electron 主进程、设备访问、应用服务、IPC、preload
  renderer/  # React 页面、布局、hooks、运行时 UI 状态
```

- 依赖方向固定为 `renderer/main -> shared`，shared 不反向依赖。
- 跨包能力从公共入口暴露，不跨包深层导入内部实现。

## 主进程分层

```text
renderer -> preload/contextBridge -> ipc -> DeviceService
                                      -> DeviceAdapter
                                      -> device/api -> HttpClient -> 设备
```

- `DeviceService` 是 renderer 的应用层入口。
- 新设备型号通过实现 `DeviceAdapter` 扩展。
- 功能降级统一使用 `CapabilityProbe` / `CapabilityMatrix`。

## IPC 与错误

- channel 统一定义在 `packages/shared/src/ipc-channels.ts`。
- 新调用同步修改 shared 契约、preload、handler 与 renderer 类型。
- 错误统一映射为 shared 错误码，不跨进程传递 Axios/Electron 原始异常。

## Renderer

- 页面位于 `packages/renderer/src/pages/<Domain>/`。
- 菜单和路由集中维护，菜单项必须有对应可达路由。
- 登录态只保存在内存，禁止把密码或 token 写入 localStorage。

## 交付门槛

```bash
corepack pnpm -r run typecheck
corepack pnpm test
corepack pnpm -r run build
```

- Node.js 20.11+，pnpm 9.x。
- 以根 `package.json#packageManager` 为版本真值；在未确认全局 pnpm 版本时使用 `corepack pnpm`，禁止为适配本机更高版本 pnpm 改写 workspace 配置。
- `node_modules/`、`dist/`、`out/` 和安装包不进入源码提交。
- 未在 design-doc 中明确列出的 `package.json`、`pnpm-workspace.yaml`、Vite、TypeScript、Vitest 和打包配置不得修改；工具链失败应写入 `open-issues`，不得通过放宽或跳过门禁来制造绿色结果。
