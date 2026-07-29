---
name: extract-project-template
description: 分析现有项目并提炼为独立、可运行、可验证的 SDLC 模板。用户要求盘点项目依赖和启动方式、去除业务代码、制作脚手架、修复旧模板、登记模板数据源或复用模板提炼流程时使用。
---

# Extract Project Template

先分析证据，再生成模板。源项目是行为基线；插件中的旧模板、README 声明和缓存产物都不能替代当前源码与真实命令结果。

## 1. 生成项目清单

执行只读 inventory：

```bash
python -X utf8 scripts/inspect_project.py --root <source-project>
```

核对根 manifest、workspace、锁文件、运行时版本、安装/启动/测试/打包命令、入口、测试文件和安全信号。忽略 `node_modules`、构建产物、IDE/agent 本地权限以及凭据。

## 2. 分离模板与业务

把内容分成三类：

- 保留：工具链、进程 seam、错误处理、安全默认值、最小功能示例、可重复验证入口。
- 泛化：项目名、包名、应用 ID、页面、IPC channel、领域 DTO 和示例数据。
- 删除：客户/设备/会议等领域实现、私有地址、默认密码、临时探测脚本、历史 workaround 和本地 agent 配置。

模板应提供小 interface 和深实现：一个安装入口、一个开发启动入口、一个验证入口，以及清晰的 main/preload/renderer/shared seam。不要为单一实现增加虚构 adapter。

## 3. 对照当前官方实现

涉及 Electron、Spring、React 等框架时，只使用当前官方文档和官方模板确认版本支持、安全基线与打包方式。记录源项目已经满足、必须修复和有意不采用的差异，不能仅因“能编译”就认定模板正确。

Electron 项目必须检查：

- 当前受支持的 Electron 版本；
- `contextIsolation`、`nodeIntegration`、sandbox、CSP 和权限策略；
- preload 最小 bridge、IPC sender/参数校验；
- 导航、外链和自定义 protocol 路径约束；
- 真实 Electron 窗口、preload 和 IPC 冒烟，而非只启动 renderer。

## 4. 生成独立模板合约

读取 [references/template-contract.md](references/template-contract.md)。模板仓库拥有全部源码、依赖、文档、`.sdlc-pipeline/contracts/lifecycle.json` 和 `.sdlc-pipeline/contracts/scaffold.json`；插件只登记数据源元数据，不复制模板资产。

生命周期至少覆盖：

```text
install -> compile -> package -> start -> readiness。code gate 保留预览；test gate 先停止预览并确认
端口释放，执行 test_preflight；仅在所选测试套件需要 runtime 时启动、readiness 后再运行测试并清理
```

生命周期合同必须声明测试套件的 selector 路径模式和 `requires_runtime`。test_preflight 在 tester
产出测试脚本后执行 lint、typecheck 与完整 unit test；functional T-id 仅在运行时 readiness 后执行。
空测试集、只检查端口或只匹配 HTML 字符串均算失败。

## 5. 验证并报告

从干净依赖安装开始运行模板声明的命令，记录命令、exit code、关键输出、产物、进程与清理结果。重新计算 scaffold key file 和 lifecycle hash，并用插件的 `verify_scaffold` 验证。

最终报告必须区分：

- 已确认的源项目问题；
- 模板中已修复的问题；
- 因环境或外部依赖未验证的事项；
- 模板依赖、开发启动、打包、测试和真实冒烟命令；
- 插件注册表需要登记的 `id/repository/ref/stacks/rules/capabilities`，其中 `rules` 只能列出
  与模板实际框架匹配、且插件 `rules/<id>.md` 已存在的规则；不得为非 Java 模板登记 Java/Spring。
