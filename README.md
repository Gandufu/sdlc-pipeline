# SDLC Pipeline

OpenCode-first、Windows 友好的确定性交付编排器。当前版本：`0.15.4`。

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
   install → compile → start → health → artifact → stop。init 只写 evidence，不创建 `docs/sdlc`。
2. `/sdlc-spec`
   摄取原型、协议和需求为 Source Markdown；一次只处理阻塞决策；按 R/D/T 分片构建 Candidate。
   “采用推荐”只保存临时 spec work；validate 后展示 revision/hash；只有“确认发布”才按
   `candidate_id + content_hash` 发布不可变 baseline。
3. `/sdlc-code`
   原生 task 只派发 `sdlc-coder`。coder 最多 16 个 agent steps，读取一个渐进式 context manifest，
   在 allowed paths 内实现业务代码和 functional 文件。task-after 校验真实 Git diff 和 handoff，
   Core 再执行 compile/package/lint/typecheck code gate。
4. `/sdlc-test`
   start/readiness 后执行 mandatory 与 headless functional 验证，最后 cleanup。Core 记录每次测试、
   中间错误和 Delivery Trace；最终成功不能覆盖此前失败 attempt。
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
  agents/                     # sdlc-main / sdlc-coder / sdlc-tester
  commands/                   # 四个用户命令
  skills/                     # 项目技能

.sdlc-pipeline/
  installation.json           # 安装版本与 layout_version
  runtime/
    scripts/                  # Python Core 与验证脚本
    schemas/                  # 当前 Schema；无 v2 兼容目录
    rules/                    # 可选规则和 policy
    references/               # spec 访谈等运行参考
    templates/                # 模板 registry 元数据
  contracts/
    lifecycle.json            # 脚手架生命周期合同
    scaffold.json             # protected/allowed/extension points
    active-rules.json         # 本项目启用规则的 hash 索引
  state/                      # 仅 compact JSON 索引、ID、hash、引用和流转状态
  work/                       # Source/Candidate/temporary spec work/context/handoff Markdown
  evidence/                   # init/code/test/error/log 等 Markdown 证据

docs/sdlc/
  current.json                # 只指向当前 baseline
  baselines/<baseline-id>/
    manifest.json             # compact 索引
    spec.md
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

- JSON 索引不得保存 prompt、answer、content、text、summary、result、error 等正文；单个索引上限
  32 KiB，单字符串上限 512 字符。
- 会话只保存宿主 session/run/task 引用和状态；对话、决策、结果与错误正文写 Markdown。
- 同一内容只存一次；Candidate revision 引用 artifact Markdown，不复制完整目录。
- `.sdlc-pipeline/state`、`work`、`evidence` 是本地现场并默认忽略；正式批准的 baseline 和版本文档进入
  `docs/sdlc`。
- 不存在 `.sdlc-pipeline/opencode`、`.sdlc-pipeline/runs` 或 `docs/sdlc/current/` 镜像。

## 合同与门禁

`lifecycle.json` 用 argv 数组声明工具、install/compile/start/stop/health/artifact 和逻辑测试键。
`scaffold.json` 声明关键文件 fingerprint、protected paths、allowed paths 与 extension points。
Design 只能引用已声明 extension point；实际代码文件由 code 后的 Git diff 推导。

OpenCode 允许用户手动切换主代理或直接 `@` 调用 agent，这不是 permission 能彻底禁止的能力。活动
Run 中不要切 agent、不要手动 `@` 子代理；团队边界见
[docs/operational-boundaries.md](docs/operational-boundaries.md)。

## 本地验证

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
python -m unittest discover -s tests -v
node --check .opencode/plugins/sdlc-pipeline.js
git diff --check
```

设计细节见 [Storage Layout v3](docs/design/Storage-Layout-v3.md) 和
[ADR-0003](docs/adr/0003-storage-layout-v3.md)。

## License

见 [LICENSE](LICENSE)。
