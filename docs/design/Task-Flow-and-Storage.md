# Task Flow 与存储

插件只管理一个活动 Task 的交付状态。Session 不是领域对象，外部文件也不是插件产物。

状态固定为：

`spec → awaiting_spec_approval → code → human_review → test →
awaiting_release_approval → finalized`

返工通过显式事件完成：

- `implementation_issue`：Human Review/Test → Code；
- `requirements_issue`：Human Review/Test → Spec；
- `review_passed`：Human Review → Test；
- `test_issue`：Test → Test。

Task 状态保存在 `.sdlc-pipeline/state/task.json`，流转事件保存在
`.sdlc-pipeline/evidence/task-events.jsonl`。用户原始需求与需求补充逐字追加到
`.sdlc-pipeline/work/input.md`；监督结果和阶段缺陷只通过 `<sdlc-feedback>` 透传。

Spec prepare 将规范化正文暂存到 `.sdlc-pipeline/work/pending-spec.md`，同时只在
`task.json` 记录 hash。approve 只接收 `content_hash + confirmed=true`，Core 读取并校验
pending 后原子生成 `docs/sdlc/baselines/<content-hash>`，成功流转后删除 pending。
修订 preview 会原子覆盖同一路径，不保留 revision 历史。
