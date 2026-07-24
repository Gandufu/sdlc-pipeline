# Handoff JSON

这是唯一的 subagent handoff 格式。JSON Schema 位于
`.sdlc-pipeline/schemas/handoff.schema.json`。

Coder：

```json
{
  "design_to_code": {"D-0001": ["src/example.ts"]},
  "test_to_files": {"T-0001": ["tests/example.test.ts"]},
  "changed_files": ["src/example.ts", "tests/example.test.ts"],
  "open_issues": [],
  "full_scan": false,
  "full_scan_reason": null
}
```

Executor：

```json
{
  "results": [
    {"id": "T-0001", "status": "pass", "evidence": ".sdlc-pipeline/runs/logs/..."}
  ],
  "open_issues": []
}
```

Coder 的 changed_files 必须与任务期间实际 Git diff 完全一致；D/T 映射必须覆盖当前 spec。
Executor 必须恰好返回全部 T-id，且状态必须与 runner 保存的结果一致。
