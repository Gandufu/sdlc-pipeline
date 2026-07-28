# Coder Handoff

Coder 只返回自己知道的信息：

```json
{
  "summary": "完成了功能实现与自动化测试",
  "open_issues": [],
  "full_scan": false,
  "full_scan_reason": null
}
```

`changed_files`、文件 SHA-256 和范围合规性不由模型声明，而由 Core 根据任务前 baseline 与
任务后 Git diff 自动生成和校验。Schema v2 的 R/D/代码/测试关系在 code/test 后生成
Delivery Trace，并显式标注 `direct`、`scoped` 或 `shared` 精度。
