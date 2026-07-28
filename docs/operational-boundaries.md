# 团队运行边界

SDLC Pipeline 的权限配置约束的是 Pipeline 代表主会话发起的工具调用。OpenCode 仍允许用户在界面中
手动切换 agent，或通过 `@ 调用` 直接启动任何已安装 agent；这属于宿主产品的用户控制能力，不能由
`permission.task` 强制封堵。

因此，处于活动 Run 时团队成员必须：

- 只通过 `/sdlc-init`、`/sdlc-spec`、`/sdlc-code`、`/sdlc-test` 推进流程；
- 不要手动切换 agent；
- 不要通过 `@ 调用` 其他 agent，也不要直接启动内置 `build`、`plan`、`explore` 或 `general` 代理；
- 如确有人工干预需求，先停止或标记当前 Run，记录原因，再从受控阶段重新执行并保留新证据。

Core 可以验证 Git diff、受控路径、审批、journal 和交付证据，但不能证明一次绕过 UI 约束的对话也遵循
这些规则。审计或团队交付应把以上约束作为运行规范，并把所有偏离、失败和重新执行写入 release evidence。
