# SDLC Pipeline

OpenCode-first、Windows 友好的轻量软件交付编排器。当前版本：`0.12.1`。

它面向固定脚手架和给定需求完成一个可交付功能：需求澄清、设计、编码、确定性验证和版本固化。
Python Core 保存机器真值与运行证据，OpenCode plugin 只负责薄适配和最小上下文编排。

## 快速安装

在目标项目目录运行：

```powershell
curl.exe -fsSL https://raw.githubusercontent.com/Gandufu/sdlc-pipeline/main/scripts/install_project.py | python - --target .
```

升级受管文件：

```powershell
curl.exe -fsSL https://raw.githubusercontent.com/Gandufu/sdlc-pipeline/main/scripts/install_project.py | python - --target . --force
```

安装器自动准备 `@opencode-ai/plugin` 依赖。重启 OpenCode 后只执行 `/sdlc-init`，再依次使用
`/sdlc-spec`、`/sdlc-code`、`/sdlc-test`。

安装会对发行包内模板 registry 与 rule policy 做 contract self-check，并把 `.opencode/**`、
`.sdlc-pipeline/**` 合并进常见 Vitest/ESLint 配置的 ignore 数组。若配置存在但结构无法安全
合并，安装结果的 `tooling_ignore.unresolved` 会显式列出，不能把它当成已处理。

## 轻量流程

```text
init
  → 选择登记脚手架
  → import/install/compile/start/health/artifact/stop

spec
  → 摄取 SourceEnvelope
  → 最多三个阻塞问题
  → “采用推荐”只保存 checkpoint
  → 用户明确“确认发布”单功能 Feature Contract
  → Core 原子生成 requirement/design/test-plan 三个视图

code
  → 派发唯一 sdlc-coder
  → 先读 Feature brief，再按需读取资源索引
  → coder 自主选择受控 focused check
  → Core 校验 Git diff 与允许路径
  → Core 自动生成 design-to-code/test-to-files evidence

test
  → 主会话只调用一次 verify_delivery
  → 校验 code 阶段 compile/package/lint/typecheck evidence
  → start/readiness/headless functional/cleanup
  → 用户确认后 finalize
```

不设置测试 subagent、默认 reviewer 或隐式完整生命周期 hook。相同输入指纹的成功交付证据可以复用；
相同失败连续出现两次时 Run Journal 将流程置为 blocked，避免 agent 无界反思和重试。
coder dispatch 单独绑定 OpenCode PID、9 分钟 deadline 和工具活动 heartbeat；owner 退出或
deadline 到期后，下一次 status 会把 attempt/run 标为 aborted，不遗留伪 running 状态。

Context manifest 不嵌入源码、长需求或完整规则，只提供 brief、资源路径、hash、tier 和读取理由。
Delivery Memory 自动派生稳定项目事实、已确认决策以及“失败后成功”的指纹经验；它不保存聊天，
并在 lifecycle、scaffold 或 spec hash 改变时失效。

## Feature Contract

模型只生成 `schemas/feature-contract.schema.json` 约束的单功能对象，内容包括：

- `F-xxxx` 功能目标、角色、范围和非范围；
- 来源 `source_id + anchor`；
- 领域数据模型和字段；
- 简洁主流程及必要异常流程；
- `AC-xxxx` 验收条件；
- 模块、接口、data contract、真实 scaffold extension point；
- 每个 AC 对应一个 functional T-id、受控测试逻辑键和功能文件 selector。

`lint` 和 `static_analysis` 属于 code policy，不伪装成功能需求测试。Core 将 Feature Contract
投影为兼容的 requirements、design、test-plan JSON/Markdown；这些文件不是模型重复编写的三份输入。

## 状态、恢复与追溯

`.sdlc-pipeline/runs/journal/` 记录 run/phase/step/attempt/event，包含进程身份、失败分类和输入指纹。
Spec 问答检查点保存 source refs、已确认事实、假设和风险；中断后从最后检查点继续。
项目外文本来源只有显式 `allow_external_copy=true` 才会复制到
`.sdlc-pipeline/runs/source-assets/`；副本与 SourceEnvelope 同时绑定 SHA-256。默认单文件上限
10 MiB，目录和未经 extractor 处理的二进制来源仍拒绝。

Headless 运行建议实时消费 OpenCode 的原始事件流，不要等进程结束后才读取 stdout：

```powershell
opencode run --format json "/sdlc-code"
```

`--format json` 是宿主 CLI 的调用参数，插件无法替调用者强制开启；journal heartbeat 是独立的
项目内持久证据。

正式机器产物包括：

```text
docs/sdlc/bundles/<bundle>/feature-contract.json
docs/sdlc/current/requirements.json
docs/sdlc/current/design.json
docs/sdlc/current/test-plan.json
docs/sdlc/test-results/Vxxxx.json
docs/sdlc/versions/Vxxxx/manifest.json
```

完整命令日志保存在 `.sdlc-pipeline/runs/logs/`。bundle 使用同目录暂存后原子提交；Schema 使用正式
JSON Schema validator；Git 工作树、lifecycle、scaffold、artifact 与 PID identity 都进入证据绑定。

## 工具边界

OpenCode 暴露六个窄工具：

- `sdlc_status`
- `sdlc_ingest_source`
- `sdlc_query_source`
- `sdlc_save_checkpoint`
- `sdlc_publish_contract`
- `sdlc_lifecycle`（仅 `init`、`focused_check`、`verify_delivery`）
- `sdlc_finalize`

模型不能提供 idempotency key，也不能直接编辑正式 SDLC 文档。`focused_check` 只运行当前
Feature Contract 已登记的 T-id 与对应文件，不构成交付证据。内部仍保留可恢复的确定性操作，
但幂等性由 Core 根据规范化输入计算和管理。

## 生命周期契约

项目提供：

```text
.sdlc-pipeline/lifecycle.json
.sdlc-pipeline/scaffold.json
```

`lifecycle.json` 使用 argv 数组声明 install/compile/start/stop/health/artifact，以及
functional、unit、integration、lint、static_analysis 逻辑键。功能测试命令只有显式
`allow_selector=true` 才能追加 `tests/` 内的测试文件。`scaffold.json` 声明关键文件 fingerprint、
protected paths、allowed paths 与 extension points。
常见 `vitest.config.*`、`eslint.config.*` 作为预登记 tooling paths，可记录为非业务变更，
但不会被错误计入 design-to-code 功能证据。

Electron profile 是当前参考实现；状态机和证据契约稳定后再增加 Spring、Node Web、Python API
profile，避免模板数量先于 Core 稳定性扩张。

## 开发验证

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
python -m unittest discover -s tests -v
node --check .opencode/plugins/sdlc-pipeline.js
git diff --check
```

测试覆盖 Schema、Feature Contract 投影、原子 bundle、Git 路径映射、PID identity、Run Journal
恢复和熔断、权限矩阵、安装升级清理以及完整 init → spec → code → verify → finalize Core 闭环。

## License

见 [LICENSE](LICENSE)。
