# ADR-0002：模板资产独立维护

- 状态：Accepted
- 日期：2026-07-26

## 决策

SDLC Pipeline 插件不再携带模板源码或模板专属约定。插件的 `templates/` 目录只维护
`manifest.json` 数据源注册表；每个模板作为独立 Git 仓库维护完整源码、依赖、锁文件、文档、
测试以及 `.sdlc-pipeline/lifecycle.json`、`.sdlc-pipeline/scaffold.json`。

`/sdlc-init <template-id>` 从 registry 解析 repository/ref，在临时目录 clone/checkout 后导入
当前空项目并保留模板 Git 历史。`/sdlc-init --github <repo> [ref]` 使用同一导入路径。init
报告必须记录数据源 ID、仓库、请求 ref 和实际 commit SHA。

## 当前参考实现

- 模板 ID：`sdlc-electron-scaffold`
- 仓库：<https://github.com/Gandufu/sdlc-electron-scaffold.git>
- 本地目录：`D:\sdlc-electron-scaffold`
- 内容：去除 Heli、设备和会议领域代码的纯通用 Electron 模板
- 工具链：Electron Forge、React、Vite、TypeScript
- 保留能力：安全 main/preload、typed IPC、React 示例、单元测试、真实 Electron 冒烟和完整生命周期

## 原因

模板与插件具有不同的发布节奏和职责。资产外置后，插件只负责模板发现、选择、导入和门禁，
模板仓库独立验证依赖、构建、启动、测试及产物，可避免陈旧内嵌模板无法运行，也避免 demo
业务被误当作通用脚手架。

## 约束

- 禁止重新向插件加入模板源码、锁文件或模板专属业务文档。
- registry 没有唯一匹配时必须要求用户确认。
- 模板必须携带可验证的 lifecycle/scaffold 契约。
- 发布模板前必须验证安装、打包、启动、health、artifact、测试和停止流程。
