# Electron 栈规约

> 与 `typescript.md`、`react.md` 配合使用；本文件只约束 Electron 主进程、preload 与 IPC 安全边界。

## 1. 进程边界

- renderer 只通过 `contextBridge` 暴露的最小 API 调用主进程，不直接访问 Node.js、文件系统或设备网络。
- BrowserWindow 保持 `contextIsolation: true`、`nodeIntegration: false`；不得为了开发便利关闭隔离。
- preload 暴露的方法使用业务语义命名，不暴露通用 `ipcRenderer.send/invoke/on`。

## 2. IPC

- IPC channel 在 shared 包集中定义，main、preload、renderer 共用同一契约。
- 每个 handler 校验输入、鉴权状态和能力支持情况，并统一转换错误。
- 禁止动态拼接任意 channel、命令或文件路径；新增 channel 必须同步补类型和测试。

## 3. 设备与凭据

- 设备密码、session 和 token 只保留在 main 进程内存，禁止写入日志、renderer store 或持久化存储。
- 设备地址通过受控配置进入主进程，禁止 renderer 直接请求设备。
- 自签名证书放宽仅限明确配置的内网设备目标，不得全局关闭 TLS 校验。

## 4. 生命周期与打包

- BrowserWindow、IPC handler、轮询与事件监听都应有明确创建/销毁时机，避免重复注册。
- 构建产物 `dist/`、`out/`、安装包和 `node_modules/` 不进入源码提交。
- Windows 打包配置与应用版本保持一致；打包前必须通过 typecheck、test 和 build。
