# SDLC Pipeline

OpenCode-first、Windows 友好的确定性交付编排器。当前版本：`0.19.1`。

插件采用薄宿主 adapter + Python Core：OpenCode JavaScript 只注册工具、执行 hook 和记录宿主事件；
状态机、审批、路径门禁、进程、测试与证据校验都由 Python Core 负责。Core 不依赖 OpenCode 会话模型，
未来增加宿主时应复用同一 Core，而不是复制流程。

## 安装与升级

在目标项目根目录执行：

```powershell
curl.exe -fsSL https://raw.githubusercontent.com/Gandufu/sdlc-pipeline/main/scripts/install_project.py | python - --target .
```

开发阶段升级直接采用当前 Layout v3，不兼容旧布局：

```powershell
curl.exe -fsSL https://raw.githubusercontent.com/Gandufu/sdlc-pipeline/main/scripts/install_project.py | python - --target . --force
```

`--force` 会删除插件曾管理的旧 `.sdlc-pipeline/runs`、内层 `.opencode`、顶层
`scripts/templates/rules/references/schemas`、旧合同和 Schema v2 文件。不要用它迁移需要保留的旧运行现场。
安装器会准备 `@opencode-ai/plugin`、校验发行包 Schema/模板/rule policy，并更新常见
Vitest/ESLint ignore。安装后重启 OpenCode，只执行 `/sdlc-init`。未导入合同的新项目会先展示模板并停止等待
用户下一轮明确选择；即使只有一个候选也不会自动初始化。

## 整体流程

1. `/sdlc-init`
   选择 registry 中的脚手架，导入 `.sdlc-pipeline/contracts`，执行
   install → compile → package → start → health → artifact → stop。init 只写 evidence，不创建
   `docs/sdlc`。
2. `/sdlc-spec`
   摄取原型、协议和需求为 Source Markdown；一次只处理阻塞决策；按 R/D/T 分片构建 Candidate。
   “采用推荐”只保存临时 spec work；validate 后展示 revision/hash；只有“确认发布”才按
   `candidate_id + content_hash` 发布不可变 baseline。
3. `/sdlc-code`
   原生 task 只派发 `sdlc-coder`。coder 不使用固定秒数或 agent 轮次上限，读取一个渐进式 context manifest，
   在 allowed paths 内只实现业务代码，禁止读取或修改测试脚本。task-after 校验真实 Git diff 和
   handoff，Core 再执行 compile/package/lint/typecheck、启动与 readiness，并保留预览进程，
   返回模板声明的访问地址供用户检查当前页面。
   若 `/sdlc-test` 的已记录失败明确归因为业务代码，用户可显式执行 `/sdlc-code 返工 <原因>`；Core 会
   记录 `run.rework_started` 并重新完成完整 code gate。该入口不能用于跳过测试、修改测试脚本或重复已通过的
   普通 code 阶段。
   首次 code gate 的确定性业务代码失败会保留错误 evidence，并允许一次同 phase 的聚焦 coder retry；第二次
   相同失败或 Run blocked 必须停止报告。
4. `/sdlc-test`
   `sdlc-main` 只派发一次 `sdlc-tester` 子 agent；tester 仅在 Spec selector 声明的路径内编写
   unit 或 functional 脚本并返回 handoff。plugin 校验 handoff 后，Core 停止 coder 预览并确认端口
   释放，执行合同 `test_preflight`，再只为声明 `requires_runtime: true` 的测试套件启动运行时并完成
   readiness。Core 记录每次测试、中间错误和 Delivery Trace；最终成功不能覆盖此前失败 attempt。

Playwright MCP 不是 pipeline 的必需依赖。权威 gate 通过 lifecycle contract 直接调用项目已安装的
Playwright package/CLI；MCP 仅适合未来可选的探索式浏览器交互，不能代替可重复执行的测试脚本。
5. 用户确认后由 `sdlc_finalize` 固化版本、摘要、证据 commit 和 tag。

相同输入指纹的成功 attempt 可幂等复用；同一失败连续出现两次时 Run 会进入 `blocked`，防止死循环。
原始 OpenCode JSONL 应保存在目标项目的同级 evidence 目录，不写进项目工作树。

## OpenCode 技能与命令

项目安装以下技能：

- `sdlc-pipeline`：init/spec/code/test 主流程、审批边界和恢复规则。
- `extract-project-template`：提取独立脚手架仓库的合同与模板元数据。

用户命令为 `/sdlc-init`、`/sdlc-spec`、`/sdlc-code`、`/sdlc-test`。插件提供的窄工具包括：

- `sdlc_status`
- `sdlc_ingest_source` / `sdlc_query_source`
- `sdlc_save_spec_work` / `sdlc_query_spec_work`
- `sdlc_begin_candidate`
- `sdlc_put_requirement` / `sdlc_put_design` / `sdlc_put_verification`
- `sdlc_validate_candidate` / `sdlc_approve_candidate`
- `sdlc_lifecycle`
- `sdlc_finalize`

模型不能编辑正式 baseline、构造 idempotency key 或绕过确认边界。

## 目录规范（Layout v3）

```text
.opencode/
  plugins/                    # 唯一 OpenCode adapter
  agents/                     # primary sdlc-main + coder/tester subagents
  commands/                   # 四个用户命令
  skills/                     # 项目技能

.sdlc-pipeline/
  installation.json           # 安装版本与 layout_version
  runtime/
    scripts/                  # Python Core 与验证脚本
    schemas/                  # 当前 Schema；无 v2 兼容目录
    rules/                    # 可选规则和 policy
    references/               # spec 访谈等运行参考
    templates/                # registry 与 R/D/T/Decision Markdown 模板
  contracts/
    lifecycle.json            # 脚手架生命周期合同
    scaffold.json             # protected/allowed/extension points
    active-rules.json         # 本项目启用规则的 hash 索引
  state/                      # compact JSON 索引；含 publication receipt
  work/                       # Source/Candidate/temporary spec work/context/handoff Markdown
  evidence/                   # init/code/test/error/log 等 Markdown 证据

docs/sdlc/
  current.json                # 只指向当前 baseline
  baselines/<baseline-id>/
    manifest.json             # compact 索引
    spec.md                   # 从正式文档生成的评审汇总
    candidate.md              # Candidate 标题正文
    decisions/Q-xxxx.md       # 发布前阻塞决策的正式固化
    sources/<source-id>/       # 已冻结来源 Markdown 与索引
    requirements/R-xxxx.md
    designs/D-xxxx.md
    verification/T-xxxx.md
  test-results/Vxxxx/
    index.json                # compact 索引
    result.md                 # 完整测试结果
  versions/Vxxxx/
    manifest.json             # compact 索引
    details.md                # 完整版本证据
    summary.md
```

约束：

- JSON 索引不得保存 title、prompt、answer、content、text、summary、result、error 等正文；单个索引上限
  32 KiB，单字符串上限 512 字符。
- Spec Work 只保存已解决决策和提炼后的事实、假设、风险，不保存聊天全文；validate 将 resolved
  decision 冻结进 Candidate hash，发布后再清理 Spec Work 和 Candidate。
- R/D/T 使用 frontmatter 加固定标题文法的原生 Markdown，不嵌入 JSON fenced block。
- 同一内容只存一次；Candidate revision 引用 artifact Markdown，不复制完整目录。
- `.sdlc-pipeline/state`、`work`、`evidence` 是本地现场并默认忽略；正式批准的 baseline 和版本文档进入
  `docs/sdlc`。
- 不存在 `.sdlc-pipeline/opencode`、`.sdlc-pipeline/runs` 或 `docs/sdlc/current/` 镜像。

## 合同与门禁

`lifecycle.json` 用 argv 数组分别声明 compile、package、start、health/artifact、test_preflight
和测试套件。v1.1 的每个测试套件声明 `requires_runtime` 与 `selector_patterns`，使 Electron、Web 和
未来 Spring Boot 都能作为同一 Core 的合同适配器。start 产生的后台进程由 Core 记录 PID 与创建身份
并统一停止，模板不重复实现 stop/restart 脚本。code gate 执行 compile/package、lint、typecheck、
启动与 readiness，并保持预览运行；test 阶段由 Core 清理预览端口、执行 tester 产出后的预检，再按
suite 需求运行 unit 或 Playwright functional 测试。

v1.0 继续支持默认 `functional` selector：省略时按最终 T-id 生成
`tests/functional/T-xxxx.functional.ts`。v1.1 的 Verification 必须显式提供符合该 suite 路径模式的
POSIX 项目内 selector；tester 仍只能修改已发布 Spec 声明的精确文件。
`scaffold.json` 声明关键文件 fingerprint、protected paths、allowed paths 与 extension points。
Design 只能引用已声明 extension point；实际代码文件由 code 后的 Git diff 推导。

OpenCode 允许用户手动切换主代理或直接 `@` 调用 agent，这不是 permission 能彻底禁止的能力。活动
Run 中不要切 agent、不要手动 `@` 子代理；团队边界见
[docs/operational-boundaries.md](docs/operational-boundaries.md)。

## 本地验证

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
python -X utf8 -m unittest discover -s tests -v
node --check .opencode/plugins/sdlc-pipeline.js
git diff --check
```

设计细节见 [Storage Layout v3](docs/design/Storage-Layout-v3.md) 和
[ADR-0003](docs/adr/0003-storage-layout-v3.md)。

## License

见 [LICENSE](LICENSE)。
