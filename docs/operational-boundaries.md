# 运行边界

- OpenCode 管理会话上下文；插件不保存或恢复会话。
- 主会话只记录用户原始输入并驱动 Task 状态。
- coder 只修改业务代码，tester 只修改正式 Verification 声明的测试。
- Core 管理状态流转、写入范围、compile/package/start/readiness、测试与固化门禁。
- 外部文件由 OpenCode 按用户授权读取，插件不复制或归档。
- 返工是 Task 状态流转，不执行自动 Git 回滚。
