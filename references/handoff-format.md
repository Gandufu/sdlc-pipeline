# 交接块格式 (Handoff Block)

> 机器可 parse。编码/测试 agent 在任务结束时输出,校验脚本据此判定与 merge。
> 必须放在 `<!-- HANDOFF:... -->` / `<!-- /HANDOFF -->` 之间,一行一个字段。
> 本文件为 /code 与 /test 共享资产,位于插件级 `references/`;派单 skill 把其路径塞进 Agent prompt,agent 显式 Read。

## 编码 agent 交接块

```markdown
<!-- HANDOFF:code agent=<scaffold-id>-coder status=done -->
compiled: pass
files:
  - src/auth/AuthController.java
  - src/auth/dto/LoginRequest.java
trace:
  D1: [C7 AuthController]
  D2: [C8 RbacService, C9 RbacController]
open-issues: []
<!-- /HANDOFF -->
```

字段:
- `compiled`:`pass` / `fail`(fail 时不可进入测试)。
- `files`:实际改动的文件相对路径列表(H3b 会与 worktree `git diff` 比对防谎报)。
- `trace`:D-id → C-id(代码模块/文件)映射。
- `open-issues`:未解决问题(可为空 `[]`)。

## 测试 agent 交接块(双轴 review-findings)

```markdown
<!-- HANDOFF:test agent=<scaffold-id>-tester status=done -->
review-findings:
  standards:
    - severity: medium
      target: C8 RbacService
      issue: 命名违反 spring.md 的 service 层约定
  spec:
    - severity: high
      target: C8 RbacService
      issue: 偏离 D2,未实现角色继承
      requirement: R2
<!-- /HANDOFF -->
```

字段:
- `standards`:代码是否符合 rules/conventions。severity ∈ high/medium/low;target 指向 C-id。
- `spec`:代码是否满足 requirement/design。必须带 `requirement`(R-id)定位。
- 两轴都非空(H4a 校验);若代码完全无问题,各列一条 `severity: low, issue: 无偏离` 占位。

## 校验脚本如何用
- `validate_code_handoff.py`(H3a/H3b):parse 交接块 → 校验 compiled、files 真实存在、与 git diff 比对、D→C 完整性 → merge `trace` 进矩阵。
- `validate_test_handoff.py`(H4a/H4b):parse → 校验两轴非空、MVP 全链 R→D→C 闭合 → merge。
