# SDLC Pipeline Schema v2 实现说明

- 状态：已实施
- 首次实现版本：`0.14.0`
- 适用范围：OpenCode plugin、Python Core、安装产物
- 调研依据：[社区中的 Spec、中间状态与知识索引模式](../research/community-intermediate-state-patterns.md)

## 1. 决策

SDLC Pipeline 只支持 Schema v2 Spec，不保留 Feature Contract v1 写入或聚合读取协议。

正式数据分成四层：

1. Source：原始输入及可验证 anchor；
2. Spec Candidate：Feature Map、Requirement、Design、Verification 分片候选；
3. Published Baseline：经精确 hash 审批后发布的不可变 bundle；
4. Execution Evidence：code/test 后从 Git、文件和测试事实生成的 Delivery Trace。

```text
ingest source
  → begin candidate
  → put small artifacts
  → validate
  → ready(revision + content_hash + preview)
  → user confirms exact revision
  → approve(candidate_id + content_hash)
  → atomic v2 publish
  → code / verify
  → derive Delivery Trace
```

## 2. 文件模型

### Candidate

```text
.sdlc-pipeline/runs/spec-candidates/SC-000001/
  candidate.json
  approval.json
  revisions/
    0001/
      manifest.json
      feature-map.json
      requirements/R-0001.json
      designs/D-0001.json
      verification/T-0001.json
      validation.json
      preview.md
```

`candidate.json` 是唯一可变指针。每次 put 创建新 revision，旧 revision 不覆盖。ready 后的
revision/hash 冻结；任何业务 artifact 修改都会产生新的 draft revision。

### Published bundle

```text
docs/sdlc/bundles/<bundle-id>/
  bundle.json
  feature-map.json
  requirements/R-0001.json
  designs/D-0001.json
  verification/T-0001.json
  spec.md
  index.md
```

`docs/sdlc/spec-current.json` 只指向完整 bundle；`docs/sdlc/current/` 是可重建镜像，不保存
聚合 requirements/design/test-plan JSON。

## 3. Schema

```text
schemas/v2/
  source-ref.schema.json
  feature-map.schema.json
  requirement.schema.json
  design.schema.json
  verification.schema.json
  candidate-manifest.schema.json
  candidate-pointer.schema.json
  approval.schema.json
  delivery-trace.schema.json
```

Schema resolver 只允许 schema root 内的相对 `$ref` 和当前文档 JSON Pointer。网络引用、
绝对路径、目录越界和循环引用全部拒绝。安装器在写 installation marker 前递归解析全部 Schema。

## 4. Artifact 责任

### Feature Map

只保存 Initiative、Feature、依赖和 Requirement ID。依赖必须无环；Requirement 只能属于一个
Feature；Map 不复制 Requirement 正文。

### Requirement

一个 Requirement 是可独立验收的垂直切片，包含目标、参与者、范围、非范围、主流程、异常流程、
带独立 source refs 的 AC，以及可选 `supersedes`。

### Design

只描述 module、responsibility、seam、interface、data contract、decision 和 scaffold
extension point。不得声明 `allowed_paths` 或实际 changed files；Core 从 scaffold 推导允许范围。

### Verification

建立 R/D/AC 到 lifecycle `test_key` 和 selector 的关系。每个 AC、Requirement 和 Design 必须被
mandatory Verification 覆盖。lint、static analysis、package 等工程控制不伪装成业务验证。

## 5. Candidate 状态机

```text
absent
  → draft
      ├─ put → new draft revision
      ├─ validate(fail) → draft + diagnostics
      └─ validate(pass) → ready + preview + frozen hash
          ├─ put(change) → new draft revision
          └─ approve(exact id/hash/confirmed)
              → published
```

审批不携带正文。Core 在发布前重新验证 pointer、manifest、artifact hash、validation、preview 和
source anchor。重复批准同一 published ID/hash 幂等返回同一 bundle。

## 6. OpenCode 工具

```text
sdlc_begin_candidate
sdlc_put_requirement
sdlc_put_design
sdlc_put_verification
sdlc_validate_candidate
sdlc_approve_candidate
```

参数使用宿主结构化 schema，不使用 JSON-in-string。`sdlc_status.spec_candidate` 返回当前
candidate 的 state、revision、hash、preview path、validation 结果和 artifact 计数。

## 7. Delivery Trace

Spec 只约束 R→D→T 和 extension point。实际代码映射在 code/test 后生成：

```json
{
  "schema_version": "2.0",
  "spec_bundle_id": "<sha256>",
  "rows": [
    {
      "requirement_id": "R-0001",
      "design_ids": ["D-0001"],
      "changed_files": [
        {"path": "src/device/system-info.py", "sha256": "..."}
      ],
      "verification": [
        {
          "test_id": "T-0001",
          "selector": "tests/functional/system-info.functional.ts",
          "result_ref": "docs/sdlc/test-results/V0001.json#T-0001",
          "precision": "direct"
        }
      ],
      "precision": "scoped"
    }
  ]
}
```

精度只有：

- `direct`：selector 或测试结果直接绑定；
- `scoped`：唯一 extension point 范围推导；
- `shared`：多个 Design 共享路径，保守建立多对多关系。

finalize 只有在全部 R/D/T 形成有效证据闭环且无非法路径时才允许固化版本。

## 8. 大需求与索引

大需求通过 Feature Map 和独立 R/D/T artifact 渐进导航。发布时生成 `index.md`，索引只包含
metadata、ID、摘要和链接，不复制正文。长期知识条目不参与 spec approval，也不会自动从来源
复制到仓库。

## 9. 安装与清理

- 安装器复制 `schemas/v2/**` 和 v2 Core；
- force upgrade 删除旧 Feature Contract schema/module；
- Candidate 和 source 工作文件留在 ignored `.sdlc-pipeline/runs/`；
- revision/bundle 使用同目录临时目录和 `os.replace` 原子提交；
- 临时目录在成功或异常后清理；
- published bundle、version manifest 和被引用 source evidence 不自动删除。

## 10. 验证

实现由以下检查覆盖：

- Candidate begin/put/revision/idempotency；
- 跨 artifact 和 source anchor 校验；
- ready hash 与修改后失效；
- exact-hash approval 和重复批准；
- v2-only bundle 内容；
- post-code Delivery Trace；
- OpenCode 工具和权限；
- 安装递归 Schema self-check；
- 完整 init → spec → code → test → finalize 回归。
