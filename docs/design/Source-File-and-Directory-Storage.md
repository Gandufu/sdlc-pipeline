# Source 文件与目录存储

## 原则

Source 的受控副本保持原格式。Markdown 只用于原始 Markdown、inline 文本或真实 extractor 明确生成的文字
投影；PNG、PDF、压缩包等二进制不能被解码为 Markdown。

## 存储

每个 Source 使用一个自包含目录：

```text
SRC-XXXXXXXXXXXX/
  index.json
  manifest.json
  files/
    <原文件或原目录树>
  projection.md
```

`projection.md` 是可选产物。不存在 extractor 输出时不创建。

## 旧 Source 迁移

旧版已经生成的 `content.md` 不在升级时原地猜测或改写，因为二进制乱码无法可靠恢复原文件边界。
升级插件后必须从权威原路径重新执行 `sdlc_ingest_source`，取得新的 `source_id/anchor`，再更新尚未发布
的 Spec work 引用。旧目录保留为审计证据，只有使用者明确确认后才清理。

- `index.json` 是小型状态索引，保存 Source ID、tree hash、manifest hash 和 anchor 定位信息。
- `manifest.json` 是文件索引，保存稳定排序的相对路径、media type、字节数和 SHA-256。
- `files/` 保存原始字节；目录来源保留相对树结构。

## Anchor

- 文本文件：`text:N` 或 `file:<relative-path>:N`，绑定原格式文件的字符偏移。
- 二进制文件：`asset:<relative-path>`，查询返回 `asset_ref`、media type、大小和 hash，不返回 `text`。
- extractor 投影：`projection:N`，明确与原始资产分离。

## 安全和确定性

- 项目外路径必须显式 `allow_external_copy=true`。
- 单文件上限 10 MiB，目录总计上限 32 MiB，目录最多 64 个文件、128 个 anchor。
- 拒绝 symlink/junction 和超过限制的相对路径。
- Source ID 绑定稳定排序后的路径、文件 hash、大小以及可选 projection hash。
- 发布 baseline 时复制整个 Source 目录并复验 manifest 和每个原文件的 hash。
