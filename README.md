# SDLC Pipeline

> OpenCode-first、证据驱动的项目交付状态机。

当前版本：`0.5.0`。

SDLC Pipeline 用项目脚手架契约、确定性 Python runner、真实编译/启动/测试和 Git
版本证据，把一次需求从澄清推进到可追溯版本。

当前只正式支持 OpenCode，包括 OpenCode 桌面版。Claude Code 与 Codex adapter
已从活动代码中移除。

## 文档导航

- [先理解两种使用场景](#先理解两种使用场景)
- [新项目完整流程](#新项目完整流程推荐)
- [已有项目接入](#已有项目接入)
- [四个用户命令](#四个用户命令)
- [角色与权限](#角色与权限)
- [生命周期与脚手架契约](#生命周期与脚手架契约)
- [产物、追溯与版本](#产物追溯与版本)
- [标准流程与增量流程](#标准流程与增量流程)
- [Token 与上下文控制](#token-与上下文控制)
- [开发验证](#开发验证)
- [常见问题](#常见问题)

架构细节见：

- [OpenCode-first 架构真值](docs/design/参照版SDLC流水线插件设计方案.md)
- [ADR-0001：OpenCode-first 与确定性 core](docs/adr/0001-opencode-first.md)
- [术语表](docs/glossary.md)
- [OpenCode 官方资料索引](docs/official-references.md)

## 核心原则

- **Evidence over claims**：模型说“编译通过”不算证据，必须由 runner 重新执行。
- **JSON 是机器真值**：AI 提交结构化对象，Markdown 由 runner 固定渲染。
- **脚手架不漂移**：关键文件、lifecycle、protected path 和 extension point 均有 hash/契约。
- **固定两个 subagent**：只使用 coder 和 executor，不设置默认 reviewer。
- **真实交付闭环**：code 后必须 compile/restart/health/artifact，test 后才允许创建版本。
- **按影响集加载**：不默认全量扫描源码，不在 SessionStart 注入大段状态。

## 前置条件

基础环境：

- OpenCode 桌面版或 CLI；
- Python 3.10+；
- Git；
- 能访问待 clone 的 Git 仓库。

项目工具链由模板的 lifecycle 声明，例如：

- Spring Boot：Java 17+、Maven 3.9+；
- Electron/React：Node.js 20.11+、Corepack。

runner 的准备优先级固定为：

1. 项目 wrapper；
2. Corepack 与 `packageManager`；
3. 已安装的系统工具；
4. 用户明确批准后的受控系统安装。

OpenCode 桌面版已经安装时，init 不会重复安装 OpenCode。

## 先理解两种使用场景

### 场景 A：创建一个新项目

先在本插件仓库中启动 OpenCode，再通过 `/sdlc-init` clone 业务仓库、安装 adapter、
复制模板并完成首次运行验收。

init 成功后，必须用 OpenCode 打开生成的目标项目，再执行后续命令。

```text
插件仓库中的 OpenCode 会话
  └─ /sdlc-init <repo> <ref> <target> [template]
       ├─ clone 目标仓库
       ├─ 安装项目级 OpenCode adapter
       ├─ 复制脚手架与 lifecycle/scaffold
       └─ install → compile → start → verify → stop

切换到目标项目的 OpenCode 会话
  └─ /sdlc-spec
       └─ /sdlc-code
            └─ /sdlc-test
                 └─ 用户确认 → internal finalize → version
```

### 场景 B：接入一个已有项目

已有项目不需要再次 clone。先为项目准备 lifecycle/scaffold 契约，再安装项目 adapter，
然后在该项目中执行 `/sdlc-init --current`。

```text
已有项目
  ├─ .sdlc-pipeline/lifecycle.json
  ├─ .sdlc-pipeline/scaffold.json
  └─ 安装项目 adapter
       └─ /sdlc-init --current
            └─ /sdlc-spec → /sdlc-code → /sdlc-test
```

`install_project.py` 只负责安装 adapter 和 deterministic core，不会猜测已有项目的启动方式，
也不会自动生成不可信的 lifecycle。

## 新项目完整流程（推荐）

### 1. 获取插件仓库

```powershell
git clone https://github.com/Gandufu/sdlc-pipeline.git
cd sdlc-pipeline
```

用 OpenCode 桌面版打开该仓库。仓库根的 `opencode.json` 会选择 `sdlc-main`，
项目级 plugin、agents、commands 和 skill 位于 `.opencode/`。

### 2. 执行 bootstrap init

```text
/sdlc-init <repo> <ref> <target> [template]
```

示例：

```text
/sdlc-init https://github.com/example/business-app.git main D:\workspace\business-app heli-terminal-client
```

内置模板：

| Template | 技术栈 | 主要产物 |
|---|---|---|
| `spring-boot-full` | Spring Boot 3、Java、Maven | 可执行 JAR、Actuator health |
| `heli-terminal-client` | Electron、React、TypeScript、pnpm | main/renderer/shared build |

init 严格执行：

```text
检查 target 不存在或为空
  → git clone + checkout ref
  → 安装项目级 adapter
  → 复制模板且不覆盖已有文件
  → 校验 lifecycle/scaffold hash
  → 探测工具链和版本
  → install dependencies
  → compile/package
  → start
  → process/HTTP/TCP/file/browser smoke
  → artifact SHA-256
  → stop（除非模板明确要求保持运行）
  → init-report
```

任何 mandatory 步骤失败，init 都返回 blocked/fail，不会生成伪成功报告。

### 3. 打开目标项目

init 完成后，用 OpenCode 桌面版打开 `<target>`，不要继续在插件仓库会话里执行 spec。

目标项目将包含：

```text
.opencode/
  agents/
  commands/
  plugins/
  skills/
.sdlc-pipeline/
  lifecycle.json
  scaffold.json
  scripts/
  schemas/
  templates/
docs/sdlc/
  init-report.json
  init-report.md
```

### 4. 运行交付阶段

在目标项目中依次执行：

```text
/sdlc-spec
/sdlc-code
/sdlc-test
```

测试全部通过后，主会话展示 `Vxxxx` candidate 并询问是否固化。只有明确确认后，
才调用内部 `sdlc_finalize` 创建 Git 版本。

## 已有项目接入

### 1. 声明项目生命周期

已有项目必须先提供：

```text
.sdlc-pipeline/lifecycle.json
.sdlc-pipeline/scaffold.json
```

可以参考：

- `templates/spring-boot-full/.sdlc-pipeline/`
- `templates/heli-terminal-client/.sdlc-pipeline/`
- `schemas/lifecycle.schema.json`
- `schemas/scaffold.schema.json`

### 2. 安装 adapter

从本插件仓库执行：

```powershell
python scripts/install_project.py --target D:\path\to\existing-project
```

升级本插件受管文件：

```powershell
python scripts/install_project.py --target D:\path\to\existing-project --force
```

installer 只写入：

- `.opencode/agents`、`.opencode/commands`、`.opencode/plugins`、`.opencode/skills`；
- `.sdlc-pipeline` 下的 Python core、schema、rules、references 和 templates；
- 缺失时写入 `opencode.json#default_agent`。

非本插件文件不会被删除。没有 `--force` 时，已存在的受管文件也不会覆盖。

### 3. 验收当前项目

用 OpenCode 打开已有项目并执行：

```text
/sdlc-init --current
```

该模式不 clone、不复制新模板，只根据当前项目已有 lifecycle/scaffold 执行
probe → install → compile → start → verify → stop，并生成 init-report。

## 四个用户命令

用户只面对四个阶段命令。

| 命令 | 运行位置 | 用户输入 | 成功门禁 |
|---|---|---|---|
| `/sdlc-init <repo> <ref> <target> [template]` | 插件仓库 | 仓库、ref、目标目录、模板 | clone/install/compile/start/verify/stop |
| `/sdlc-init --current` | 已有目标项目 | 当前 lifecycle/scaffold | install/compile/start/verify/stop |
| `/sdlc-spec` | 目标项目 | 需求、范围、约束、验收标准 | R→D→T 完整且原子发布 |
| `/sdlc-code` | 目标项目 | 已发布 spec | diff 合规且真实 compile/restart/verify |
| `/sdlc-test` | 目标项目 | code evidence | mandatory T-id 全部执行并生成结果 |

### `/sdlc-spec`

requirement 与 design 合并为一次主会话交互，但产物仍然独立：

- `requirements.json/.md`
- `design.json/.md`
- `test-plan.json/.md`

必须满足：

- R/D/T ID 格式固定且唯一；
- 每个 R-id 至少映射一个 D-id 和一个 T-id；
- 每个 D-id 至少被一个 T-id 覆盖；
- design 引用 scaffold 中真实 extension point；
- test 引用 lifecycle 中真实测试命令；
- 修改后的需求创建新 R-id，并通过 `supersedes` 指向旧 ID。

### `/sdlc-code`

```text
检查 init/spec
  → 生成最小 context pack
  → 派发唯一 sdlc-coder
  → 校验 coder handoff 与实际 Git diff
  → 拒绝 protected/out-of-scope path
  → runner 重新 compile
  → stop 旧实例
  → start 新实例
  → health + artifact hash
  → 保存 code evidence 与 D→C/T→test-file
```

coder 返回的 `compiled: pass` 不参与门禁。

### `/sdlc-test`

```text
检查 code evidence 与当前工作树 fingerprint
  → 派发唯一 sdlc-executor
  → runner 执行 test-plan 中的 T-id
  → 校验 executor handoff 与 runner 结果一致
  → 生成 test-results
  → 合并 R→D→C→T
  → 生成 Vxxxx candidate
  → 询问用户是否固化
```

测试失败时保留日志和现场，不创建 tag。

## 内部工具

以下不是用户阶段命令：

| Tool | 用途 | 副作用 |
|---|---|---|
| `sdlc_status` | 返回当前版本、阶段、门禁、PID、缺失产物和增量资格 | 无，只读 |
| `sdlc_publish` | 校验并原子发布 spec/Token 数据 | 写固定格式产物 |
| `sdlc_lifecycle` | 环境、依赖、编译、进程、health、artifact、测试 | 受 lifecycle 控制 |
| `sdlc_finalize` | 固化已通过的 candidate | commit + annotated tag |

用户询问“当前状态”或“还缺什么”时，主会话自动调用 `sdlc_status`，
不需要 `/sdlc-status`。

## 角色与权限

固定角色：

| Role | Mode | 可做 | 禁止 |
|---|---|---|---|
| `sdlc-main` | primary | 澄清、发布 spec、调用 lifecycle、派发两个 subagent | 直接 edit、任意 bash、其他 subagent |
| `sdlc-coder` | subagent | 修改设计允许的生产/测试路径、局部 compile | SDLC 文档、protected path、系统安装、Git 发布 |
| `sdlc-executor` | subagent | 只读检查、调用 `run_tests`、返回逐 T-id 结果 | 修改代码、task、finalize |

没有固定 reviewer：

- R→D→C→T 完整性由 Python core 校验；
- 代码规范由 compile、lint、static analysis 和 test 验证；
- 行为符合性由 executor 按 T-id 验证；
- 额外人工 review 可在高风险项目中另行增加，不进入默认流水线。

## Approval 规则

| 动作 | 是否需要人工确认 |
|---|---|
| 查询状态、发布 spec | 否 |
| 项目 install/compile/start/stop/test | 否，受 lifecycle 白名单控制 |
| 修改 production/test allowed path | 否，但受前后双重 path/diff 校验 |
| 系统级 Java/Node/Maven 安装 | 是，必须先展示缺失项和受控命令 |
| 固化版本 `sdlc_finalize` | 是，测试通过后必须明确确认 |
| push 到远端 | pipeline 不自动执行 |

Python core 会再次检查 `approved/confirmed`，不能只依赖模型文字。

## 生命周期与脚手架契约

### `lifecycle.json`

至少声明：

- 项目类型；
- 系统工具、版本约束和 probe；
- 项目依赖安装；
- compile/start/stop/restart；
- cwd、timeout、background、environment；
- process/HTTP/TCP/command/file/browser health；
- artifact 路径；
- unit/integration/e2e/lint/static-analysis。

命令使用 argv 数组，不保存任意 shell 字符串。可使用的受控变量只有：

- `${PROJECT_ROOT}`
- `${PYTHON}`
- `${PORT}`

### `scaffold.json`

至少声明：

- template ID/version；
- 关键文件 SHA-256；
- protected paths；
- extension points；
- allowed paths；
- lifecycle hash；
- 模板已有能力。

spec 只能引用合法 extension point。coder 写入前会检查路径，任务返回后再用实际 Git diff
复核。lifecycle 或 protected path 变化必须回到 standard 流程。

## 产物、追溯与版本

机器真值：

```text
docs/sdlc/init-report.json
docs/sdlc/current/requirements.json
docs/sdlc/current/design.json
docs/sdlc/current/test-plan.json
docs/sdlc/test-results/Vxxxx.json
docs/sdlc/versions/Vxxxx/manifest.json
```

对应 Markdown 由 runner 固定渲染。

manifest 保存：

- parent version；
- 初始与交付 Git SHA；
- template/scaffold/lifecycle hash；
- 实际工具版本；
- requirements/design/test-plan/test-results hash；
- R/D/C/T 与影响范围；
- compile/restart/health/test evidence；
- artifact hash；
- Token usage；
- full-scan reason；
- open issues；
- commit 与 annotated tag。

版本编号递增：

```text
V0001
V0002
V0003
```

finalize 使用两个 Git commit：

1. `sdlc(Vxxxx): complete <summary>`：固化交付源码和测试结果；
2. `sdlc(Vxxxx): record evidence`：把第一个 commit 的不可变 SHA 写入 manifest。

annotated tag `sdlc/Vxxxx` 指向 evidence commit。这避免 manifest 试图保存其自身 commit SHA
产生不可解的自引用。

pipeline 不自动 push。

## 标准流程与增量流程

默认使用 standard。

以下任一变化强制 standard：

- 公共接口；
- 依赖；
- 数据模型或数据库；
- 安全；
- 架构；
- lifecycle；
- protected path；
- scaffold/key file hash 漂移；
- 父 manifest 缺失或追溯断裂。

incremental 需要同时满足机器条件和用户确认：

- 复用未变化的 R/D/T；
- 只为变化需求创建新 R-id；
- coder 只读取影响集；
- executor 运行相关测试与 mandatory 回归；
- 仍然强制 compile/restart/verify/test/version。

## Token 与上下文控制

- requirement/design/test-plan 在同一主会话生成；
- 没有第三个 reviewer；
- 不做 SessionStart 状态注入；
- coder/executor 只接收影响集和 context pack；
- context pack 超过约 30k 字符时按模块拆分；
- 完整日志落盘，只返回错误片段和受限尾部；
- OpenCode 可提供的 input/output/cache Token 按阶段累计；
- 重复读取字符数单独记录；
- full scan 必须记录原因并进入 manifest。

主要 Token 成本来自真实需求、受影响源码和测试，不来自固定流程文档。

## 目录结构

```text
.opencode/
  agents/
    sdlc-main.md
    sdlc-coder.md
    sdlc-executor.md
  commands/
    sdlc-init.md
    sdlc-spec.md
    sdlc-code.md
    sdlc-test.md
  plugins/
    sdlc-pipeline.js
  skills/
    sdlc-pipeline/SKILL.md
schemas/
scripts/
  install_project.py
  sdlc.py
  sdlc_core/
templates/
  manifest.json
  conventions/
  spring-boot-full/
  heli-terminal-client/
tests/
```

旧 Claude/Codex manifests、hooks 和 adapter 不再维护；历史实现仍可通过 Git 历史追溯。

## 新增或修改模板

1. 在 `templates/<id>` 放入可独立编译和启动的项目。
2. 添加 `.sdlc-pipeline/lifecycle.json`。
3. 添加 `.sdlc-pipeline/scaffold.json`。
4. 在 `templates/manifest.json` 注册 ID、stacks 和 conventions。
5. 计算 lifecycle 与 key-file SHA-256。
6. 增加真实 install/compile/start/health/artifact/stop 测试。
7. 运行完整回归。

模板不能只提供几段示例代码；init 的验收标准是项目真实可运行。

## 开发验证

完整自动化回归：

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
python -m unittest discover -s tests -v
node --check .opencode/plugins/sdlc-pipeline.js
git diff --check
```

当前测试覆盖：

- OpenCode skill/agent/command/plugin 目录发现；
- main/coder/executor 权限矩阵；
- lifecycle/scaffold schema 与 hash；
- wrapper/Corepack 优先级；
- 系统安装确认拒绝和执行失败；
- compile/start/stop/PID；
- process/HTTP/TCP/file/browser health；
- artifact SHA-256；
- spec 原子发布；
- R→D→C→T；
- coder handoff 与 Git diff；
- executor 与 runner 结果；
- stale code evidence；
- standard/incremental；
- 历史 R-id 与 supersedes；
- Token；
- commit/tag；
- 完整 init → spec → code → test → version。

## 常见问题

### init 后为什么不能直接在原会话运行 spec？

bootstrap init 的原会话属于插件仓库，后续项目状态和 `.sdlc-pipeline` 位于新 target。
必须用 OpenCode 打开 target，让项目级 adapter 以目标 Git worktree 为 evidence root。

### 为什么 init 最后停止程序？

init 的目标是证明项目能启动并通过验证，而不是长期占用端口。模板可以通过
`keep_running_after_init` 明确要求保持运行。code 阶段会重新启动最新产物。

### 已安装 OpenCode 桌面版，还需要安装插件吗？

不需要安装另一个 OpenCode 应用。但每个业务项目仍需要项目级 `.opencode` adapter；
bootstrap init 或 `install_project.py` 会负责复制。

### 为什么没有 `/sdlc-status`？

status 不是研发阶段。直接询问“当前状态”即可，`sdlc-main` 会调用只读工具。

### 为什么没有 `/sdlc-finalize`？

finalize 是测试通过后的高风险确认动作，不是独立阶段。用户确认后由主会话调用。

### 为什么没有 reviewer？

默认 reviewer 会增加固定上下文和重复读取。当前把 review 拆成 trace、compile、lint、
static analysis 和按 T-id 的行为测试。需要人工代码审查时使用项目自己的 PR 流程。

### 系统工具安装被拒绝后会怎样？

init 生成 blocked report，列出缺失工具和安装命令，不会跳过 compile/start 制造绿色结果。
人工安装完成后重新运行 init。

### code 通过后又修改了文件会怎样？

code evidence 保存工作树 fingerprint。test 前不一致时会拒绝执行，要求重新
compile/restart/verify。

### 完整日志在哪里？

`.sdlc-pipeline/runs/logs/`。该目录默认不提交 Git。

## License

见 [LICENSE](LICENSE)。
