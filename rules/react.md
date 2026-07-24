# React 栈规约

> 由 `/sdlc-spec` 选择 extension point，runner 在 code/test context pack 中按 manifest `stacks` 按需提供。

## 1. 组件与类型

- 使用函数组件和 Hooks，props、事件与异步结果必须有显式 TypeScript 类型。
- 页面负责组合，设备调用和可复用状态逻辑放入 hooks/store。
- 组件保持单一职责，避免把设备访问、业务状态和展示逻辑堆在同一组件。

## 2. 状态与副作用

- 设备数据、全局运行时状态和组件本地 UI 状态分离。
- Zustand 只保存运行时状态；密码、token 等敏感信息不得持久化。
- 定时器、订阅和事件监听必须在 effect cleanup 中释放。

## 3. Electron 边界

- renderer 只调用 preload 暴露的白名单 API，不直接调用 Node.js、Electron 或设备 HTTP API。
- 异步页面显式处理 loading、empty、error 和 capability unsupported 状态。

## 4. 测试

- 优先按用户可见行为测试，不依赖组件内部实现。
- 登录失败、设备离线、能力不支持和请求超时是关键失败路径。
