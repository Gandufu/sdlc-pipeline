# 现有框架能力清单

> 脚手架 ID：`heli-terminal-client`
>
> `/sdlc-init` 会将本文件随模板复制到目标项目；runner 只在相关 context pack 中按需提供。

## 技术基线

- Electron 30 + React 18 + TypeScript 5.4。
- pnpm 9 workspace：`@heli/shared`、`@heli/main`、`@heli/renderer`。
- Windows 10 x64，electron-builder + NSIS 打包。

## 已有能力

- 安全进程边界：BrowserWindow、preload、contextBridge、IPC handler。
- 设备访问：`HttpClient`、`AuthService`、`DeviceService`。
- 设备抽象：`DeviceAdapter`、`MeetingEyeAdapter`。
- 能力探测与降级：`CapabilityProbe`、`CapabilityMatrix`。
- 共享契约：IPC channels、错误码和跨进程异常。
- React 应用壳：路由、侧边菜单、布局、鉴权 store 和设备 API hook。
- 已有页面：Dashboard、设备/网络、会议占位页、日志占位页。

## 不要重造

- 设备请求复用 `HttpClient` 和 `DeviceService`。
- 新设备型号实现 adapter，不在 renderer 中分支型号。
- IPC 与错误码扩展 shared 契约，不建立平行协议。
- 能力不支持复用 Capability 机制。
- 维持登录态零持久化，不保存密码或 token。

## 验证命令

```bash
pnpm -r run typecheck
pnpm -r run test
pnpm -r run build
```
