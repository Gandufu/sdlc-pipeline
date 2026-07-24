# SDLC Pipeline

一个窄而强的 OpenCode 项目交付状态机。它用脚手架契约、确定性 Python runner、真实
编译/运行/测试和 Git 版本证据，把需求到版本固化闭环起来。

当前版本：`0.5.0`。

当前版本只正式支持 OpenCode（包括桌面版）。Claude Code 与 Codex adapter 已从活动代码
中移除。

## 安装

在本仓库执行：

```powershell
python scripts/install_project.py --target D:\path\to\project
```

升级受管文件时显式增加 `--force`。installer 只写：

- `.opencode/agents`、`.opencode/commands`、`.opencode/plugins`、`.opencode/skills`
- `.sdlc-pipeline` 的 Python core、schema、模板和运行目录

它不会覆盖不属于本插件的 OpenCode 文件。OpenCode 桌面版已安装时不需要再次安装；用桌面版
打开目标项目即可发现项目级配置。

## 四个阶段命令

```text
/sdlc-init <repo> <ref> <target> [template]
/sdlc-spec
/sdlc-code
/sdlc-test
```

流程固定为：

```text
init → spec → coder → compile/restart/verify → executor/test
     → 用户确认 → manifest + commit + annotated tag
```

- `init`：clone 到空目录，复制模板且不覆盖已有文件，探测工具链，然后执行
  install → compile → start → health/artifact → stop。
- `spec`：在同一主会话澄清并原子发布独立 requirements、design、test-plan。
- `code`：只派发 `sdlc-coder`，校验实际 Git diff 后由 runner 重新编译、重启和验证。
- `test`：只派发 `sdlc-executor`，按 T-id 执行测试；全部 mandatory 通过后询问是否固化。

`sdlc_status` 和 `sdlc_finalize` 是内部工具，不是用户阶段命令。

## 角色与权限

固定只有一个 primary agent 和两个 subagent：

- `sdlc-main`：不能直接 edit 或 bash，只能发布结构化产物、调用生命周期工具并派发下述两者。
- `sdlc-coder`：可改生产代码和测试，但写入前、任务结束后都会校验 protected/allowed path；
  禁止 bash、系统安装和 Git 发布操作。
- `sdlc-executor`：只读，通过 lifecycle runner 执行测试，不改代码。

`sdlc_finalize` 默认需要 OpenCode 人工 approval，同时 Python core 还要求
`confirmed: true`、mandatory test pass 和 ready candidate。系统级 Java/Node/Maven 安装也必须
单独获得用户批准；拒绝时 init 输出缺失项并失败，不伪造成功。

## 生命周期与脚手架

每个模板必须提供：

- `.sdlc-pipeline/lifecycle.json`：受控 argv、工具探测、install/compile/start/stop/restart、
  health、artifact 和 unit/integration/e2e/lint/static-analysis。
- `.sdlc-pipeline/scaffold.json`：模板版本、关键文件 hash、protected path、extension point、
  allowed path 和 lifecycle hash。

命令不接受任意 shell 字符串，只执行 argv 数组和 `${PROJECT_ROOT}`、`${PYTHON}`、`${PORT}`
三个受控变量。模板修改后必须同步更新 SHA-256，否则 init/code 门禁拒绝。

新增模板时：

1. 在 `templates/<id>` 中放入可独立编译、启动、验证的基线项目。
2. 添加两个契约文件并按 `schemas/` 校验。
3. 把模板登记到 `templates/manifest.json`。
4. 增加 hash、health、artifact 和至少一个完整闭环测试。

## 产物与追溯

JSON 是机器真值，Markdown 由 runner 固定渲染：

```text
docs/sdlc/init-report.{json,md}
docs/sdlc/current/requirements.{json,md}
docs/sdlc/current/design.{json,md}
docs/sdlc/current/test-plan.{json,md}
docs/sdlc/test-results/Vxxxx.{json,md}
docs/sdlc/versions/Vxxxx/manifest.json
```

manifest 保存 parent、模板/lifecycle/spec hash、R/D/C/T、影响范围、编译/重启/健康/测试证据、
artifact hash、Token、open issues、commit 与 tag。修改需求产生新 R-id，并以 `supersedes`
指向旧 ID；旧 ID 不复用。

完整日志与 context pack 留在 `.sdlc-pipeline/runs` 且默认不提交，模型只看到 ID、路径、hash、
失败尾部和最多约 30k 字符的分包。

## 故障排查

- `init` 缺工具：查看 `docs/sdlc/init-report.json` 的 `missing` 与 approval_required。
- 启动失败：查看 `.sdlc-pipeline/runs/logs/*-start.log`。
- code 被拒绝：检查 design.allowed_paths、scaffold.extension_points 和 protected_paths。
- test 被拒绝：确认每个 mandatory T-id 都有测试实现映射，且 runner 与 executor 结果一致。
- 无法使用增量流程：`sdlc_status` 会列出漂移、缺父 manifest 或高风险 change flag。
- 桌面版未发现配置：确认从目标项目根打开，并存在 `.opencode/plugins/sdlc-pipeline.js`。

开发回归：

```powershell
python -m unittest discover -s tests -v
node --check .opencode/plugins/sdlc-pipeline.js
```
