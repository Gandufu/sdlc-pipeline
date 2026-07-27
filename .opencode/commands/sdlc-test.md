---
description: 执行一次权威交付验证
agent: sdlc-main
subtask: false
---

执行 skill 的 test 阶段。调用一次 `verify_delivery`；失败时报告分类、指纹和日志路径，
成功时展示版本候选并等待用户确认。
