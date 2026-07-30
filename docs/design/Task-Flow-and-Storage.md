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
`.sdlc-pipeline/evidence/task-events.jsonl`。用户原始输入逐字追加到
`.sdlc-pipeline/work/input.md`。

Spec prepare 只保存 hash；approve 使用相同正文和 hash，原子生成
`docs/sdlc/baselines/<content-hash>`。失败或未发布的正文不落盘。
