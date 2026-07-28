# Storage Layout v3 设计

## 目标

Layout v3 将“状态”和“内容”分离。JSON 只承担可快速解析的控制面；会话、需求、决策、结果、错误与
证据正文统一使用 Markdown。该版本不读取、不迁移旧 `runs`、Schema v2 bundle 或 current mirror。

## 模块边界

Store Module 是 Core 的持久化 seam：

- `layout.py`：唯一目录定位器；
- `records.py`：Markdown structured record 与 compact index 不变量；
- `stores.py`：work/evidence 深接口；
- `journal.py`：Run/Attempt 状态索引和错误/结果引用；
- `sources.py`：来源 Markdown、anchor offset 与 hash；
- `spec_candidates.py`：Candidate revision 引用图；
- `artifact_store.py`：原子发布正式 baseline。

调用方不拼接正文文件路径，也不直接把业务 payload 写进 state JSON。

## 控制面与内容面

`state/**/*.json` 的允许信息是 ID、时间、流转状态、引用、hash、计数和短枚举。禁止字段包括
`prompt/answer/content/text/description/summary/result/error/rationale/tail`。写入时递归校验，
超过 32 KiB 或出现超过 512 字符字符串立即失败。

完整 payload 写入 Markdown 的 structured record 区块，同时保留可读标题和摘要。索引保存
`content_ref + content_hash`；读取时重新计算 payload hash，任何漂移都会阻断流程。

## Source 与 Candidate

来源正文只在 `work/sources/<SRC>/content.md` 保存一次。`index.json` 保存 anchor 的
`start/end/sha256`，查询时按 offset 提取并复核 hash。外部文本不会再额外复制一份 blob；二进制原件
只有在受控 extractor 提供文本时才进入 evidence blob。

Candidate artifact 各自追加 Markdown revision。Candidate revision JSON 只引用 artifact revision，
不执行 `copytree`，因此一次局部修改不会复制完整候选。validate 生成 validation/preview Markdown
并冻结 content hash。

## 正式 baseline

批准按精确 `candidate_id + revision + content_hash + confirmed` 执行。发布使用同目录临时目录和
`os.replace`，生成 `docs/sdlc/baselines/<sha256>`。Baseline 同时冻结被引用的 Source Markdown，
因此清理全部 `work/` 后仍可独立加载。`docs/sdlc/current.json` 只是指针，不生成 current 镜像。

## Journal 与错误可观测性

Run、Attempt 和 checkpoint 索引位于 `state/runs`。Attempt 的成功结果写
`work/runs/.../<attempt>-result.md`，失败写 `evidence/errors/.../<attempt>.md`。状态索引只保存
`result_ref/error_ref`。真实目标项目的阶段审计必须同时检查宿主 JSONL tool error 和全部 Core
attempt，不允许最终 gate 掩盖中间失败。

## 清理与保留

- 可清理：`state/`、`work/`、`evidence/`，但活动 Run 不应清理；
- 长期保留：`docs/sdlc/baselines`、`test-results`、`versions`；
- 外部 raw OpenCode 日志：保存在项目同级 evidence 目录；
- 禁止重新引入：内层 `.opencode`、`runs`、current mirror、正文型 JSON。

## 验证

测试必须覆盖 compact index 不变量、Candidate 引用而非复制、删除 `work/` 后 baseline 可加载、
installer fresh tree allowlist、强制升级删除旧布局和完整 Core lifecycle。真实目标项目另按阶段
审查执行过程和交付结果。
