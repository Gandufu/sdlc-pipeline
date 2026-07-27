# SDLC Pipeline

> OpenCode-first、证据驱动的项目交付状态机。

当前版本：`0.8.1`。

SDLC Pipeline 用项目脚手架契约、确定性 Python runner、真实编译/启动/测试和 Git
版本证据，把一次需求从澄清推进到可追溯版本。

当前只正式支持 OpenCode，包括 OpenCode 桌面版。Claude Code 与 Codex adapter
已从活动代码中移除。

## 文档导航

- [一个项目目录，一个会话](#一个项目目录一个会话)
- [从模板创建新项目](#场景-a从模板创建新项目)
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

## 一个项目目录，一个会话

`/sdlc-init` 始终在**项目目录内**执行；当前 OpenCode worktree 就是唯一的项目根、
日志根和版本证据根。它不接受 target 目录，不要求先打开插件仓库，也不会在 init 后要求
切换到另一个会话。

### 场景 A：从模板创建新项目

1. 创建并进入一个空目录，例如 `D:\workspace\business-app`。
2. 在该目录从仓库下载 installer 并执行。脚本会自动拉取完整发行内容到临时目录，再安装到
   当前项目；无需预先 clone 本插件或设置本地环境变量：

   ```powershell
   curl.exe -fsSL https://raw.githubusercontent.com/Gandufu/sdlc-pipeline/main/scripts/install_project.py | python - --target .
   ```

3. 用 OpenCode 桌面版打开同一目录，执行已登记数据源或临时 GitHub 模板 init。

```text
空项目目录（也是 OpenCode 会话）
  └─ 安装 SDLC 插件
       └─ /sdlc-init <模板数据源 ID>
          或 /sdlc-init --github <repo> [ref]
             └─ import → adapter/scaffold → install → compile → start → verify → stop
                  └─ /sdlc-spec → /sdlc-code → /sdlc-test → 用户确认 → version
```

已登记模板数据源：

| Template | 技术栈 | 数据源 |
|---|---|---|
| `sdlc-electron-scaffold` | Electron Forge、React、Vite、TypeScript | `https://github.com/Gandufu/sdlc-electron-scaffold.git` |

已登记数据源示例：

```text
/sdlc-init sdlc-electron-scaffold
```

也可以描述技术需求；主 agent 会读取已安装的 registry，按
`name/description/stacks/capabilities` 选择唯一候选。没有唯一匹配时必须让用户确认，不能
静默猜测模板。

GitHub 模板示例：

```text
/sdlc-init --github https://github.com/acme/service-template.git main
```

已登记模板和显式 GitHub 模板都会在临时目录完成 clone/checkout 后导入**当前项目目录**，
并保留原仓库的
`.git` 历史。它必须提供 `.sdlc-pipeline/lifecycle.json` 和
`.sdlc-pipeline/scaffold.json`；`.opencode`、`opencode.json`、runner 与运行现场由插件管理，
不得随 GitHub 模板携带。

init 严格执行：

```text
检查当前目录为空或只含已安装插件文件
  → 根据数据源元数据解析 repository/ref，或使用显式 GitHub 地址
  → clone 到临时目录再导入当前目录
  → 安装/复用项目级 adapter
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

模板统一复用导入仓库的 HEAD 作为 Git 基线，并在 init-report 中记录数据源 ID、
repository、请求 ref 与解析后的 commit SHA。任何
mandatory 步骤失败，init 都返回 blocked/fail，不会生成伪成功报告。

init 成功后，**就在同一 OpenCode 会话**继续执行 `/sdlc-spec`、`/sdlc-code`、`/sdlc-test`。
项目将包含：

```text
.opencode/
  package.json
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

## 场景 B：接入已有项目

### 1. 声明项目生命周期

已有项目必须先提供：

```text
.sdlc-pipeline/lifecycle.json
.sdlc-pipeline/scaffold.json
```

可以参考 `sdlc-electron-scaffold` 独立模板仓库，以及
`schemas/lifecycle.schema.json`、`schemas/scaffold.schema.json`。

### 2. 安装 adapter

在已有项目根目录安装 adapter：

```powershell
curl.exe -fsSL https://raw.githubusercontent.com/Gandufu/sdlc-pipeline/main/scripts/install_project.py | python - --target .
```

升级本插件受管文件：

```powershell
curl.exe -fsSL https://raw.githubusercontent.com/Gandufu/sdlc-pipeline/main/scripts/install_project.py | python - --target . --force
```

升级后重启 OpenCode，使项目级 plugin/agent 定义重新加载。`0.8.1` 将 executor 动作改为
`execute_test_plan`，主会话结果记录动作改为 `record_test_results`；Python core 暂时兼容旧动作名，
但新 plugin 不再向 agent 暴露旧名称。

installer 只写入：

- `.opencode/agents`、`.opencode/commands`、`.opencode/plugins`、`.opencode/skills`；
- `.sdlc-pipeline` 下的 Python core、schema、rules、references 和 templates；
- 缺失时写入 `opencode.json#default_agent`。

非本插件文件不会被删除。没有 `--force` 时，已存在的受管文件也不会覆盖。

### 3. 验收当前项目

用 OpenCode 打开同一已有项目并执行：

```text
/sdlc-init
```

该模式不导入模板，只根据当前项目已有 lifecycle/scaffold 执行
probe → install → compile → start → verify → stop，并生成 init-report。

## 四个用户命令

用户只面对四个阶段命令。

| 命令 | 运行位置 | 用户输入 | 成功门禁 |
|---|---|---|---|
| `/sdlc-init <template>` | 当前空项目目录 | 已登记模板数据源 ID | resolve/import/install/compile/start/verify/stop |
| `/sdlc-init --github <repo> [ref]` | 当前空项目目录 | GitHub 模板与 ref | import/install/compile/start/verify/stop |
| `/sdlc-init` | 当前已有项目 | 当前 lifecycle/scaffold | install/compile/start/verify/stop |
| `/sdlc-spec` | 当前项目 | 需求、范围、约束、验收标准 | 用户确认且 R→D→T 完整后原子发布 |
| `/sdlc-code` | 当前项目 | 已发布且无 blocking 问题的 spec | diff 合规且真实 compile/restart/verify |
| `/sdlc-test` | 当前项目 | code evidence | mandatory T-id 全部执行并生成结果 |

### `/sdlc-spec`

requirement 与 design 合并为一次主会话交互，但产物仍然独立：

- `requirements.json/.md`
- `design.json/.md`
- `test-plan.json/.md`

必须满足：

- 保存与当前版本相关的用户原始输入，并与 AI 规范化需求分开；
- 分析明确区分已确认事实、影响范围、假设、待确认问题、风险和决策；
- 发布前向用户展示候选摘要、允许修改路径、风险和 blocking 问题；
- 只有用户明确确认后，Python core 才接受 `spec_confirmed=true` 并原子发布；
- R/D/T ID 格式固定且唯一；
- 每个 R-id 至少映射一个 D-id 和一个 T-id；
- 每个 D-id 至少被一个 T-id 覆盖；
- design 引用 scaffold 中真实 extension point；
- `test_plan.items[].command` 引用 lifecycle tests 逻辑键，例如 `unit`；
  不得填写 `pnpm test`、`npm test` 等 shell 命令；
- 修改后的需求创建新 R-id，并通过 `supersedes` 指向旧 ID。

### `/sdlc-code`

```text
检查 init/spec 与 blocking 问题
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
任何 `blocking=true` 且未解决的问题都会被 Python core 拒绝，不能只靠命令提示绕过。

### `/sdlc-test`

```text
检查 code evidence 与当前工作树 fingerprint
  → 派发唯一 sdlc-executor
  → executor 调用 execute_test_plan，runner 执行 test-plan 中的 T-id
  → 校验 executor handoff 与 runner 结果一致
  → 主会话调用 record_test_results，生成 test-results
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
| `sdlc-executor` | subagent | 只读检查、调用 `execute_test_plan`、返回逐 T-id 结果 | 修改代码、`record_test_results`、task、finalize |

没有固定 reviewer：

- R→D→C→T 完整性由 Python core 校验；
- 代码规范由 compile、lint、static analysis 和 test 验证；
- 行为符合性由 executor 按 T-id 验证；
- 额外人工 review 可在高风险项目中另行增加，不进入默认流水线。

## Approval 规则

| 动作 | 是否需要人工确认 |
|---|---|
| 查询状态 | 否 |
| 发布 spec | 是，必须先确认候选 spec |
| 项目 install/compile/start/stop/test | 否，受 lifecycle 白名单控制 |
| 修改 production/test allowed path | 否，但受前后双重 path/diff 校验 |
| init 中模板声明的 Java/Node/Maven 安装 | 否，执行 `/sdlc-init` 即授权受控安装 |
| init 之外的系统级工具安装 | 是，必须明确确认 |
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

`tests` 的属性名是测试逻辑键，值才是受控 argv。例如：

```text
unit -> ["pnpm", "test"]
```

spec 中 `test_plan.items[].command` 必须填写 `unit`，不能填写 `pnpm test`。发布 spec 时
Python core 会与当前项目 lifecycle 交叉校验，并在错误中列出允许的逻辑键。

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
docs/sdlc/versions/Vxxxx/summary.md
```

对应 Markdown 由 runner 固定渲染。
`summary.md` 由 manifest 和测试/运行证据确定性生成，便于直接查看交付范围、commit/tag、
compile/restart/health/test、artifact 和 open issues；它不是新的机器真值。

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
- 原始需求完整保存在正式 artifact 中，context pack 只传 source、字符数和 SHA-256，
  避免 coder/executor 重复消费长篇原始输入；
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
    extract-project-template/
schemas/
scripts/
  install_project.py
  sdlc.py
  sdlc_core/
templates/
  manifest.json
tests/
```

`.opencode/package.json` 声明本地插件运行所需的 `@opencode-ai/plugin`。
安装器会自动创建或合并该依赖，并通过系统已有的 npm（或 bun）完成安装和落盘验证，
以规避部分 OpenCode Desktop 版本无法正确准备本地插件依赖的问题。用户无需手工执行
包管理命令；安装完成后可直接重启 OpenCode 并执行 `/sdlc-init`。

旧 Claude/Codex manifests、hooks 和 adapter 不再维护；历史实现仍可通过 Git 历史追溯。

## 新增或修改模板数据源

1. 在独立 Git 仓库维护可 clone、编译、启动和测试的模板项目。
2. 模板仓库添加 `.sdlc-pipeline/lifecycle.json` 与 `scaffold.json`，并计算
   lifecycle 与 key-file SHA-256。
3. 模板仓库增加真实 install/compile/start/readiness/smoke/stop 测试。
4. 在插件 `templates/manifest.json` 只登记
   `id/name/description/stacks/capabilities/source(repository/ref)`。
5. 用 `$extract-project-template` 生成 inventory，运行模板门禁和插件完整回归。

插件发布包不包含模板源码或模板专属 assets。模板不能只提供几段示例代码；init 的验收标准
是从数据源导入后项目真实可运行。

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
- init 自动安装模板声明的缺失系统工具；
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

### init 后在哪里运行 spec？

仍在执行 init 的同一个项目目录、同一个 OpenCode 会话运行 `/sdlc-spec`。当前 worktree
从开始就是 evidence root，不存在插件仓库会话到目标项目会话的交接。

### 为什么 init 最后停止程序？

init 的目标是证明项目能启动并通过验证，而不是长期占用端口。模板可以通过
`keep_running_after_init` 明确要求保持运行。code 阶段会重新启动最新产物。

### 已安装 OpenCode 桌面版，还需要安装插件吗？

不需要安装另一个 OpenCode 应用。但每个业务项目仍需要 SDLC Pipeline 的项目级 adapter；
在项目根执行上面的 GitHub installer 命令会负责拉取发行内容并写入受管文件。

### 为什么没有 `/sdlc-status`？

status 不是研发阶段。直接询问“当前状态”即可，`sdlc-main` 会调用只读工具。

### 为什么没有 `/sdlc-finalize`？

finalize 是测试通过后的高风险确认动作，不是独立阶段。用户确认后由主会话调用。

### 为什么没有 reviewer？

默认 reviewer 会增加固定上下文和重复读取。当前把 review 拆成 trace、compile、lint、
static analysis 和按 T-id 的行为测试。需要人工代码审查时使用项目自己的 PR 流程。

### init 缺少系统工具时会怎样？

`/sdlc-init` 会让 runner 按模板 `lifecycle.json` 中的白名单命令自动安装并重新探测，然后
继续 install/compile/start/verify/stop。模板没有声明受控安装方式或安装失败时，init 返回
真实失败日志；AI 不会让用户复制 Python runner 命令，也不会跳过门禁制造绿色结果。

### code 通过后又修改了文件会怎样？

code evidence 保存工作树 fingerprint。test 前不一致时会拒绝执行，要求重新
compile/restart/verify。

### 完整日志在哪里？

`.sdlc-pipeline/runs/logs/`。该目录默认不提交 Git。

## License

见 [LICENSE](LICENSE)。
