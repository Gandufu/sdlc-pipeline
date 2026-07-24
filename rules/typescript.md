# TypeScript 栈规约

> 由 `/sdlc-spec` 选择 extension point，runner 在 code/test context pack 中按 manifest `stacks` 按需提供。

## 1. 类型边界

- 保持 `strict` 模式，禁止用 `any` 绕过类型系统；外部输入先按 `unknown` 接收并在边界完成校验或收窄。
- 跨进程、跨包、网络响应和持久化数据必须有显式类型，不依赖隐式结构约定。
- 共享契约放在 shared 包；main 与 renderer 不各自复制 IPC payload、错误码或 DTO。

## 2. 错误模型

- 可预期业务失败使用带稳定错误码的领域异常，未知异常统一转换后再跨 IPC 返回。
- 不吞异常，不直接把 Axios、Node.js 或 Electron 的原始异常对象暴露给 renderer。
- `catch` 变量按 `unknown` 处理，完成类型判断后再读取属性。

## 3. 模块与依赖

- 使用显式导出控制公共 API；不要跨目录深层导入其他模块的内部文件。
- 保持单向依赖，shared 不依赖 main/renderer，renderer 不依赖 main 的实现。
- 新依赖必须说明用途，优先复用现有库，避免为简单逻辑引入重型依赖。

## 4. 测试

- 业务分支、错误码映射、边界值和失败路径必须有单元测试。
- 外部 HTTP、Electron API 和时间/环境变量通过可替换边界隔离，测试不得依赖真机或公网。
- 修复缺陷时先增加能复现问题的测试，再修改实现。
