# 参照版 SDLC 流水线插件设计方案

> 本文档为 **grill 式拷问产出**,所有决策均经逐轮追问、给候选、push back 后由用户拍板。
> 文档定位:参照版,用于和现有版本(`D:\workspace\sdlc-agent-pipeline`)对照找差距。

---

## 1. 目的与对照定位

### 1.1 定位
一个 **"需求分析 → 设计 → 编码 → 测试"四阶段闭环**研发流水线插件,用 plugin-dev 最佳实践从零实现。

- **对照目标**:与现有版本 `D:\workspace\sdlc-agent-pipeline` 并列,找出编排范式、资产组织、门禁实现上的差距。
- **本版测试阶段的实际范围**:测试 agent 的设计能力完整(工具画像已就位),但**测试执行(接口测试 / Playwright 功能测试)本版 defer**,MVP 只行使**需求符合性走查**部分。详见 §2.3 与 §5.4。

### 1.2 三条隔离边界(本版的核心取舍,详见第 8 章)
| 资产 | 处置 |
|---|---|
| `rules/` | **通用栈规约,从现有版本原样引入,放根目录,不重组** |
| `templates/` | 内容可借鉴,但**必须按 preset 化结构重组,非原样拷贝** |
| `skill` / `agent` / `hook` / 脚本 / manifest / marketplace | **从零设计,不得照抄现有实现** |

### 1.3 硬约束(实测教训 + 官方文档依据,不可违反)
1. **hooks 按官方范式,不用状态机门禁做编排**:hooks 是"生命周期里的确定性控制点",不是工作流编排器。阶段推进改用 skill 触发(用户显式命令)+ agent 工具限制;**质量门用 PostToolUse**(agent 返回后自动跑校验脚本,结果作为 additionalContext 注入);**硬性"谁不能做什么"走 agent 工具限制 + permission**;**只有"必要的事前拦截"才用 PreToolUse(deny)**;hook 注入文本写**事实陈述**,不写命令式(否则触发 prompt-injection 防御)。
2. **agent 不得依赖 skills frontmatter 预加载**(实测 plugin agent 的 `skills:` 字段不注入 SKILL.md 正文);需要协议时**显式 Read**。
3. **每个 agent 必须有"工具限制"或"上下文隔离"的刚需理由**,否则下沉为 skill。
4. **可机器校验的约束**(交接块格式、追溯矩阵、状态)写成校验脚本,evidence over claims。
5. **skill 的 description 写"做什么 + 何时用"**(官方原文:What the skill does AND when to use it),**关键用例前置**;细化触发短语放配套字段 `when_to_use`;`description + when_to_use` 合计上限 **1,536 字符**(官方 skill listing 预算,超则被截断)。注意:早期版本误记为"只写何时用"——以官方为准。

> ⚠️ **关于约束 #1 的一次有意义的扩权**:本方案把"阶段准入门禁"判定为属于"必要的事前拦截",因此 G2/G4 用 **PreToolUse deny** 强制(而非 skill 自觉前置检查)。这升级了门禁的强制性,文档显式记录此升级;其余 hooks 仍严格遵循官方范式。

---

## 2. 组件清单

### 2.1 总览
| 类型 | 数量 | 列表 |
|---|---|---|
| user-invoked skill(slash 命令) | **5** | `/init` · `/requirement` · `/design` · `/code` · `/test` |
| model-invoked SOP skill | **0** | 不设。SOP 内容内联进各 skill / agent system prompt + 显式 Read 协议文件 |
| agent | **2** | 编码 agent · 测试 agent |
| hook | **9** | 见 §4.5 |
| 校验脚本 | **5** | `gate-code` · `gate-test` · `validate-code-handoff` · `validate-test-handoff` · `derive-state` |

**没有** `/setup`(脚手架已自带预填能力文档,降级为无)、**没有** `/pipeline` 总指挥(全程用户显式敲命令推进,无自动串联)。

### 2.2 skill 清单
| 命令 | 触发方 | 职责 | 产物 | 预加载说明 |
|---|---|---|---|---|
| `/init` | 用户 | 读 manifest → AskUserQuestion 选脚手架 → 拷骨架到工程根(不覆盖)→ 追加 `@docs/existing-framework.md` 到 CLAUDE.md | 项目骨架 + `工程/docs/existing-framework.md` | description 写"做什么+何时用":"初始化项目:选脚手架、铺骨架、接入能力清单;项目尚未初始化时用" |
| `/requirement` | 用户 | **主会话**内 AskUserQuestion 来回拷问需求 | `docs/requirement-spec.md`(含 R-id) | 需求留在主会话(需与用户交互,subagent 黑盒不可) |
| `/design` | 用户 | **主会话**内 Read 需求 + rules → 写设计文档落盘,返回结构摘要 | `docs/design-doc.md`(含 D-id) | 设计不进 agent:skill 直接 Write 落盘,主会话只收摘要,不撑爆上下文 |
| `/code` | 用户 | **派单员**:Read manifest 取 stacks/conventions → 把 design-doc 路径 + rules 路径 + conventions 路径塞进 Agent prompt → 派发**编码 agent** → 收交接块 | 源码 + 交接块(含 C-id 映射) | 不写死栈名,全靠 manifest 派生 |
| `/test` | 用户 | **派单员**:派发**测试 agent**(fresh eye,带需求+设计+代码)→ 收交接块 | 走查结论(MVP)+ 交接块 | MVP 不跑测试执行 |

> **设计阶段不设 agent 的理由**:设计师 agent 跑时项目里尚无实现代码,"不该看到实现细节"的隔离理由不成立;skill 直接 Write 落盘即可达成"大体量产物不进主会话"。按约束 #3,设计降级为 skill。

### 2.3 agent 清单
| agent | 工具画像 | 隔离刚需(为何是 agent 不是 skill) | MVP 行为 |
|---|---|---|---|
| **编码 agent** | `Edit` / `Write` / `Bash` | **工具限制**:PreToolUse 硬拦 docs/ 的 Write/Edit,H3 用 git diff 复校全部改动;**上下文隔离**:plan/生成/编译的冗长过程不进主会话;**worktree 隔离**:在独立 git worktree 中工作 | plan → 代码生成 → 编译 → 自检,交接块返回 C-id 映射 |
| **测试 agent** | `Read` / `Grep` / `Write(测试文件)` / `Bash(跑测试)` | **上下文隔离 + fresh eye**:带需求+设计入场,**不看编码 agent 的内部 plan 思路**,独立判代码是否对题;**工具限制**:不给 Edit 源码 | **MVP 只做需求符合性走查**(Read/Grep 判断),交接块返回 `review-findings`;写测试/跑测试的能力**工具已就位、行为本版 defer** |

> **测试 agent 命名**:保留"测试 agent / 测试阶段"之名。文档显式标注:**测试执行能力(接口测试、Playwright)本版未实现,工具画像已就位、待后续补**。

> **编码 agent 的 worktree 模型**(抄 `obra/superpowers`):`/code` skill 派单前 `git worktree add` 开一个隔离工作树,编码 agent 在其中写码。收益:① 产物是**可 `git diff`、可审查、可整体回滚**的硬证据(贴 evidence over claims);② 天然不碰主工作树(贴"不覆盖已有");③ H3b 校验可直接比对 worktree diff 与交接块 `files:` 列表是否一致,堵住"交接块谎报改动"。用户 review 后再 merge 回主树。
> **测试 agent 的角色冲突**:MVP 阶段它同时是"独立第三方走查员"(挑刺)和未来的"测试执行者"。本版只行使前者,冲突未显现;后续测试执行落地时需复核。

---

## 3. 领域资产机制

### 3.1 目录结构(锁定的最终形态)
```
plugin-root/
  rules/                                 # ① 栈级规约(根目录,原样引入,与脚手架无关)
    java.md
    spring.md
    vue.md
  templates/
    manifest.json                        # ② 注册表(id/name/description/stacks/path/conventions)
    docs/                                # ③ 平台统一【填充模板】(不拷,skill 按需 Read)
      requirement-spec.md
      design-doc.md
      traceability-matrix.md
      test-plan.md                       # 占位保留,本版未使用(标注)
    conventions/                         # ④ 脚手架级【编码约定】(与脚手架平级,不拷)
      <scaffold-id>.md
    <scaffold-id>/                       # ⑤ 脚手架骨架(整目录拷到工程根)
      docs/
        existing-framework.md            #   该脚手架预填能力清单(随骨架拷到 工程/docs/)
      src/...                            #   代码分层样例(随骨架拷走)
      (项目骨架其余文件)
  skills/        agents/        hooks/   # 从零设计
  scripts/        # 校验脚本(gate-*/validate-*/derive-state)
```

### 3.2 三类文档的判据:**"该不该进项目"**
| 类型 | 该进项目? | 位置 | 加载方式 |
|---|---|---|---|
| existing-framework.md(预填能力清单) | ✅ 拷 | 在骨架 `docs/` 内 → 随 /init 拷到 `工程/docs/` | **`@import` 常驻**(追加 `@docs/existing-framework.md` 到 CLAUDE.md,会话启动自动加载) |
| templates/docs/*.md(填充模板) | ❌ 不拷 | `templates/docs/` | 各 skill 按需 Read |
| conventions/<id>.md(编码约定) | ❌ 不拷 | `templates/conventions/`(与脚手架平级,**避免被整目录拷贝误拷**) | `/code` 派单时从 `${CLAUDE_PLUGIN_ROOT}` Read |
| 骨架样例代码 | ✅ 拷 | `templates/<id>/` | /init 整目录拷到工程根 |
| rules/<stack>.md(栈规约) | ❌ 不拷 | `rules/`(根) | 按 manifest `stacks` 字段**按需 Read**,不 @import、不常驻 |

> **rules 为何不 @import 常驻**:rules 是"怎么写代码"的栈规约,仅设计/编码/测试阶段需要;需求阶段不需要 spring.md。@import 常驻会白占上下文且让 CLAUDE.md 膨胀。与 existing-framework 的不对称是有意的:能力清单是"项目事实"(全阶段都要知道别重造),栈规约是"编码方法"(按需)。
> **conventions 为何与脚手架平级(不在脚手架目录内)**:/init 是"整目录拷贝",任何放在 `templates/<id>/` 内的文件都会被一锅端拷走。编码约定是"不该进项目"的参考文档,放在脚手架目录内会被误拷,故挪到平级的 `conventions/`。

### 3.3 manifest 字段
```json
{
  "id": "spring-boot-full",
  "name": "Spring Boot 全栈脚手架",
  "description": "...",
  "stacks": ["java", "spring"],
  "path": "templates/spring-boot-full",
  "conventions": "templates/conventions/spring-boot-full.md"
}
```

### 3.4 /init 拷贝语义(钉死)
- `templates/<id>/*` → **整目录拷到用户工程根**(不覆盖已有)。`existing-framework.md` 因在 `docs/` 子目录,自然落到 `工程/docs/existing-framework.md`。
- `templates/conventions/<id>.md` → **不拷**,`/code` skill 派单时 Read。
- `templates/docs/*.md` → **不拷**,各 skill 按需 Read。
- 拷贝完成后,在工程根 `CLAUDE.md` 追加 `@docs/existing-framework.md`(Claude Code 支持 `@` 引用自动加载)。

### 3.5 agent 取资产的"派单员"模式(模式 p)
约束 #2 卡死:agent 拿不到自动加载的 skill。故由 **`/code`、`/test` skill 充当派单员**:
1. skill 先 Read manifest,取得 `stacks` / `conventions` / `path`。
2. 算出 `rules/<stack>.md` 路径、`conventions/<id>.md` 路径、design-doc/requirement-spec 路径。
3. 把这些路径**拼进 Agent 工具的 prompt**,agent 启动后**显式 Read**。
4. agent 正文零硬编码栈名,所有路径由 manifest 派生。

### 3.6 各阶段资产来源一览
| 阶段 | 用的资产 | 怎么拿到 |
|---|---|---|
| 全阶段(会话启动) | existing-framework.md | `@import` 自动加载 |
| `/requirement` | templates/docs/requirement-spec.md | skill 内 Read |
| `/design` | templates/docs/design-doc.md + traceability-matrix.md + rules/<stack>.md | skill 内 Read(stacks 来自 manifest) |
| `/code`(编码 agent) | 骨架(已拷,含分层样例)+ design-doc + existing-framework(已在上下文)+ rules + conventions | skill 派单塞路径,agent 显式 Read |
| `/test`(测试 agent) | templates/docs/test-plan.md(占位)+ design-doc + requirement-spec + rules | 同上 |

---

## 4. 状态机与门禁

### 4.1 状态模型:**派生**(无 state 文件)
- **真值永远是产物存在性 + 校验结果**。无 `state.json`。
- 每次"当前处于哪个阶段、哪些步骤未完成"由 `derive-state.ts` 脚本从产物**实时派生**,杜绝状态漂移。
- 派生视图通过 H5/H6/H7 注入主会话(见 §4.5)。

### 4.2 阶段与转移条件
```
[未初始化] --/init--> [需求中] --/requirement--> [设计中] --/design--> [可编码]
   --/code (G2 deny)--> [编码中] --H3 通过--> [可测试] --/test (G4 deny)--> [测试中] --H4 通过--> [闭环]
```
任一前置门禁未过 → 对应命令拒绝(deny 或 skill 自查拒绝)。

### 4.3 门禁点与实现方式(三类映射)
| 门禁 | 守什么 | 实现 |
|---|---|---|
| **G0**:`/init` 前置 | 未初始化不能用其他命令 | (a) 各 skill 启动查 CLAUDE.md 是否含 `@docs/existing-framework.md` |
| **G1**:进入设计前 | requirement-spec.md 存在 + R-id 齐 + 必填章节齐 | (a) `/design` 内部前置自查 |
| **G2**:进入编码前 | design-doc 存在 + 追溯 R→D 闭合 | **(c) PreToolUse deny**(H1,钩 Agent·编码 agent) |
| **G3**:编码 agent 返回后 | 交接块格式 + compiled + 追溯 D→C | **(d) SubagentStop**(H3a)自纠正 + **(b) PostToolUse**(H3b)merge+注入 |
| **G4**:进入测试前 | G3 已通过 | **(c) PreToolUse deny**(H2,钩 Agent·测试 agent) |
| **G5**:测试 agent 返回后 | review-findings + 全链闭合(MVP:R→D→C) | **(d) SubagentStop**(H4a)自纠正 + **(b) PostToolUse**(H4b)merge+注入 |
| **工具硬限制** | 编码 agent 禁碰 docs;测试 agent 禁 Edit 源码 | agent tools + permission(非 hook) |

> (a)=skill 内前置自查;(b)=PostToolUse 注入主会话;(c)=PreToolUse deny;(d)=SubagentStop 自纠正(注入子代理)。
> **G1/G0 用 skill 自查**(文档撰写是 skill 主体,无干净的工具调用可拦);**G2/G4 用 PreToolUse deny**(agent 派发是干净的 Agent 工具调用,适合 hook 硬拦);**G3/G5 用 SubagentStop + PostToolUse 双钩**(见 §4.5)。
>
> ⚠️ **关于 matcher 的精度**:`matcher` 字段**只按工具名过滤**(当前为 `"Agent"`)。"是编码 agent 还是测试 agent"这层细筛由脚本兼容解析 `tool_input.subagent_type` 与 SubagentStop 的 `agent_type` 完成。

---

## 4.5 hooks 事件选用清单(逐事件)

### SubagentStop vs PostToolUse(Agent):不重叠,职责不同(关键澄清)
| | 介入时机 | additionalContext 注入给 | 用途 |
|---|---|---|---|
| **SubagentStop** | 子代理**考虑退出、尚未退出**,上下文仍在 | **子代理** | 质量门 + **自纠正**:交接块不合规 → block + 反馈 → 子代理**当场自己修**(带完整思考上下文)→ 再尝试退出 |
| **PostToolUse(Agent)** | 子代理**已彻底退出**,上下文已销毁 | **主会话** | 副作用(merge 矩阵)+ 把处理过的摘要告知主会话 |

> 二者**不是二选一**,而是按能力分工配对:H3 = H3a(SubagentStop,自纠正)+ H3b(PostToolUse,merge+告知);H4 同理。让 agent 在退出前把交接块修对(便宜、不丢上下文),退出后再由主会话侧脚本做落盘与告知。

### 选用的 9 个 hooks
> matcher 字段只按**工具名**过滤;Agent 工具事件读 `tool_input.subagent_type`,SubagentStop 读 `agent_type`。

| # | 事件 | matcher(实写) | 阻断/注入 | 脚本 | 注入文本草稿(**事实陈述式**) |
|---|---|---|---|---|---|
| **H1** | PreToolUse | `Agent` | **阻断 deny**(脚本内判 subagent_type=编码) | `gate_code.py` | `design-doc.md 缺少"模块划分"章节;追溯矩阵需求→设计有 2 条未映射。当前派生阶段:设计中。` |
| **H2** | PreToolUse | `Agent` | **阻断 deny**(脚本内判 subagent_type=测试) | `gate_test.py` | `上一门禁未通过:编码 agent 交接块"设计→代码追溯"未闭合(模块 X 未映射)。当前派生阶段:编码中。` |
| **H3a** | **SubagentStop** | (脚本内判 agent_type=编码) | **阻断 + 注入子代理**(block 决策使 agent 继续) | `validate_code_handoff.py` | `交接块缺 compiled 字段;D2 未给出 C 映射。当前交接块不合规。` |
| **H3b** | PostToolUse | `Agent` | 注入主会话 | `validate_code_handoff.py`(merge 模式) | `编码 agent 已退出。交接块格式:合规。编译:通过。追溯 D→C:4/5,模块 X 未映射,已 merge 入矩阵。派生阶段:编码中。` |
| **H4a** | **SubagentStop** | (脚本内判 agent_type=测试) | **阻断 + 注入子代理**(block 决策使 agent 继续) | `validate_test_handoff.py` | `review-findings 为空;走查结论缺失。当前交接块不合规。` |
| **H4b** | PostToolUse | `Agent` | 注入主会话 | `validate_test_handoff.py`(merge 模式) | `测试 agent 已退出。走查结果已校验并 merge。` |
| **H5** | PostToolUse | `Write\|Edit` 命中 `docs/**/*.md` | 注入主会话 | `derive-state.ts` | `当前派生阶段:设计完成,可进入编码。未完成步骤:无前置阻塞。产物:requirement-spec ✓、design-doc ✓、追溯 R→D 5/5 ✓。` |
| **H6** | SessionStart | — | 注入主会话 | `derive-state.ts` | 同 H5(初始派生) |
| **H7** | PreCompact | — | 注入主会话 | `derive-state.ts` | 同 H5(压缩前重算,防 compaction 丢状态视图) |

**职责关系**:H3a/H4a(SubagentStop)= 退出前自纠正质量门,不落盘;H3b/H4b(PostToolUse)= 退出后 merge 矩阵 + 告知主会话;H5/H6/H7 = 通用派生状态注入主会话。三者脚本可复用同一份校验/派生逻辑的不同入口模式。
**H7 存在理由**:主会话跨四阶段累积上下文,compaction 可能摘掉派生状态视图;PreCompact 强制重算注入,确保长任务中"当前阶段/未完成步骤"始终可靠。

> ⚠️ **防死循环约束**:H3a/H4a 的自纠正 block 必须在脚本内设**最大重试次数**(如 3 次);超限则放行退出并在 H3b/H4b 摘要里标注"交接块经 N 次自纠正仍未合规,需人工介入",避免 agent 改不好时无限 block。

### 不选的 hooks(文档写明理由)
| 事件 | 不选理由 |
|---|---|
| `UserPromptSubmit` | 派生状态已由 H5+H6+H7 覆盖;每次用户发话重算太贵、收益低 |
| `Stop` | 主会话停止点无门禁需求 |
| `SessionEnd` | 无清理需求 |
| `Notification` | 非流水线职责 |

> 所有注入文本严守约束 #1:**只陈述事实(缺什么、通过什么、当前阶段),不写命令式**(不写"请先完成设计"/"请修正"),避免触发 prompt-injection 防御。

---

## 5. 追溯矩阵与交接块

### 5.1 矩阵写法:**方案 I**(agent 吐映射,脚本落盘)
- 编码/测试 agent **不直接 Edit 矩阵**(守工具限制);它们在**交接块里吐结构化映射**返回。
- **H3/H4 校验脚本** parse 交接块后,把映射 **merge 进 `docs/traceability-matrix.md`**。
- 矩阵是存盘文件(人可读、UI 友好),但**只由脚本写,零手改、零漂移**(贴约束 #4 evidence over claims)。

### 5.2 矩阵结构(`docs/traceability-matrix.md`)
| R-id(需求) | D-id(设计) | C-id(代码模块/文件) | T-id(测试用例) | 状态 |
|---|---|---|---|---|
| R1 用户登录 | D1 鉴权模块 | C7 AuthController | _(后续填充)_ | MVP 闭合 |
| R2 权限管理 | D2 RBAC | C8/​C9 | _(后续填充)_ | MVP 闭合 |

> **MVP 闭合判据**:H4 校验 **R→D→C 三段闭合** + 双轴 review-findings 合规且没有 high/medium finding。T 列**结构保留、内容空**。全链 R→D→C→T 的闭合校验 defer。

### 5.3 ID 归属
| ID | 谁命名 | 何时产生 |
|---|---|---|
| R-id | `/requirement` | 写 requirement-spec.md 时,锁定不可变 |
| D-id | `/design` | 写 design-doc.md 时,填 R→D 列 |
| C-id | 编码 agent(交接块) | H3 脚本 merge 进 D→C 列 |
| T-id | 测试 agent(交接块,本版 defer) | 后续测试执行落地时 merge |

### 5.4 交接块格式(机器可 parse)
```markdown
<!-- HANDOFF:code agent=spring-boot-coder status=done -->
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
测试 agent 交接块多一个字段,**双轴结构**(抄 mattpocock/code-review:Standards 轴 = 是否符合 rules/conventions;Spec 轴 = 是否满足需求/设计):
```markdown
review-findings:
  standards:   # 代码是否符合 rules/<stack>.md 与 conventions
    - severity: medium
      target: C8 RbacService
      issue: 命名违反 spring.md 的 service 层约定
  spec:        # 代码是否满足 requirement-spec / design-doc
    - severity: high
      target: C8 RbacService
      issue: 偏离 D2,未实现角色继承
      requirement: R2
```

### 5.5 校验脚本判据(evidence over claims)
| 脚本 | 触发 | 判据(任一不过 → deny / 标记) |
|---|---|---|
| `gate-code.ts`(H1) | 进编码前 | requirement-spec 每个 R-id 都在矩阵有 D 映射;design-doc 必填章节齐 |
| `gate-test.ts`(H2) | 进测试前 | H3 已通过(D→C 全映射、compiled=pass) |
| `validate-code-handoff.ts`(H3a 校验 / H3b merge) | 编码 agent 退出前(H3a)/ 退出后(H3b) | H3a:交接块可 parse、compiled=pass、每个被 touch 的 D-id 都有 C 映射、files 真实存在,不过则 block 自纠正;H3b:**worktree `git diff` 文件集 = 交接块 `files:` 列表**(防谎报),复校通过后 merge 矩阵 |
| `validate-test-handoff.ts`(H4a 校验 / H4b merge) | 测试 agent 退出前(H4a)/ 退出后(H4b) | H4a:交接块可 parse、**review-findings 的 standards 与 spec 两轴都非空**(走查双轴均完成)、MVP 全链 R→D→C 闭合,不过则 block 自纠正;H4b:复校通过后 merge 矩阵 |
| `derive-state.ts`(H5/H6/H7) | docs 写入 / 会话启动 / 压缩前 | 从产物派生"当前阶段 + 未完成步骤",事实陈述注入 |

### 5.6 测试 agent 工作流(层 B,本版 MVP)
- **设计能力**:三级流水线 — ① 需求符合性走查 → ② 接口测试 → ③ Playwright 功能测试。工具画像 `Read/Grep/Write(测试文件)/Bash(跑测试)` 已就位。
- **MVP 行为**:只行使 **① 走查**(Read/Grep 判断,交接块返回 review-findings)。②③ 本版 defer。
- **三级门禁语义(为后续预留)**:建议采用**混合门禁** — ① 走查不过则中止(代码连需求都没满足,白跑昂贵 E2E 是浪费);① 过则 ②③ 互补都跑。本版不实现,记录待续。
- **测试代码来源(为后续预留)**:建议脚手架预置测试框架样例(随 /init 拷进工程),agent 补用例。本版不实现。

---

## 6. 扩展规则(三种扩展的不变量)

| 扩展类型 | 要改的文件 | 不该动的 |
|---|---|---|
| **新增栈**(如 `react`) | `rules/react.md` | 不动任何 skill/agent/manifest 既有条目 |
| **新增脚手架**(如 `spring-boot-lite`) | ① `templates/spring-boot-lite/`(骨架)② `templates/conventions/spring-boot-lite.md`(编码约定)③ manifest 加一条(path+conventions+stacks) | 不动 rules/(除非引入全新栈)、不动 skill/agent 正文 |
| **新增文档模板**(如 `api-spec.md`) | `templates/docs/api-spec.md` + 在使用它的 skill 里加一行 Read | 不动 manifest、不动脚手架 |

**三个"不变"根基**(skill/agent 正文零硬编码栈名,全靠 manifest 派生):
- 栈名 ← manifest `stacks` → 拼 `rules/<stack>.md`
- 脚手架编码约定 ← manifest `conventions`
- 骨架位置 ← manifest `path`

> **边界说明**:本章只覆盖"领域资产"扩展(栈/脚手架/文档模板)。新增门禁点、新增 agent 属"流水线结构"变更,不在领域资产扩展范围,需另评审对状态机与 hooks 的影响。

---

## 7. 测试策略(层 A:插件自测)

### 7.1 测试边界(核心决策)
| 对象 | 可测性 | 策略 |
|---|---|---|
| 校验脚本(gate/test/validate/derive) | ✅ 纯函数 | fixture 产物 → 断言 deny/通过/merge 结果 |
| `/init` 拷贝逻辑 | ✅ 可测 | fixture 脚手架 → 断言目录树 + 不覆盖 + `@import` 追加正确 |
| manifest 解析 | ✅ 可测 | 各种 JSON → 断言路径派生、缺字段报错 |
| hooks 接线 | 🟡 半可测 | 配置静态校验;行为靠脚本单测覆盖 |
| **skill 的 LLM 行为**(/requirement 拷问质量、/design 设计质量) | ❌ 不单测 | 靠 SKILL.md 指令 + 人工评审 |
| **agent 的 LLM 行为**(编码质量、走查质量) | ❌ 不单测 | 同上 |

> **测试策略只覆盖确定性机器**(脚本 + 拷贝 + 解析);LLM 驱动的 skill/agent 行为**不纳入自动化测试**。

### 7.2 必测行为清单(7 条)
1. `gate-code.ts`:齐全→放行;缺章节→deny,理由事实陈述
2. `gate-test.ts`:H3 未过→deny
3. `validate-code-handoff.ts`:交接块 parse、compiled 校验、D→C 完整性、merge 正确
4. `validate-test-handoff.ts`:MVP 全链闭合、review-findings 校验、merge 正确
5. `derive-state.ts`:给定产物→派生阶段 + 未完成步骤正确
6. `/init` 拷贝:目录树、不覆盖、`@docs/existing-framework.md` 追加、conventions 不被拷
7. manifest 解析:路径派生、缺 `conventions` 字段报错

---

## 8. 隔离边界

| 边界 | 处置 | 理由 |
|---|---|---|
| `rules/` | **原样引入,放根目录,不重组** | 通用栈规约,与脚手架无关,按 stacks 加载 |
| `templates/` | **内容借鉴但按 preset 化结构重组** | manifest 注册 + 统一 docs + 脚手架(含骨架+existing-framework)+ 平级 conventions |
| 编排(skill/agent/hook/脚本/manifest/marketplace) | **从零设计,不照抄** | 用官方范式重做,与现有版本对照找差距 |

### 三条贯穿全篇的不变量
1. **evidence over claims**:可机器校验的全写成脚本(矩阵、交接块、状态派生),不靠 LLM 自觉。
2. **路径全派生**:skill/agent 正文零硬编码栈名,一切从 manifest + 所选脚手架派生。
3. **hooks 守纪律**:只做生命周期确定性控制点(deny 事前拦截 / PostToolUse 注入事实),不做工作流编排;阶段推进靠用户显式命令 + agent 工具限制。

### skill 膨胀免疫力(对照 superpowers / ECC 的结构优势)
官方明说 skill 数量增长是真实问题:skill listing 占 context 预算 1%,描述超 1,536 字符会被截断,需靠 progressive disclosure + `skillOverrides` + `/doctor` 治理(见 [Skills 文档](https://code.claude.com/docs/en/skills.md))。`obra/superpowers`(~86 skill)、ECC(上百)、社区 `claude-skills`(345)都走"skill 堆积"路线,正是膨胀重灾区。

**本方案的结构优势:skill 数量与脚手架数解耦**——加脚手架只改 `templates/<id>/` + `conventions/<id>.md` + manifest 一条(数据),**不加 skill**;加栈只加 `rules/<stack>.md`;加文档模板只加 `templates/docs/*.md`。skill 恒定 **5 个**(四阶段 + init),无论承载多少脚手架/栈。这是相对 superpowers/ECC 的核心对照点,也是对"skill 会膨胀"这一官方关切的最强应对:**把变异放进数据,不放进 skill。**

> 概念澄清:"skill 当协调员"是 superpowers 的**社区模式,非官方**。官方推荐的组合单元是 skill+subagent 或 plugin,从不推荐"主 skill 编排子 skill"。本方案的 `/code`、`/test` 派单员 = skill(任务定义)+ agent(隔离执行),正合官方范式。

---

## 附录:决策溯源(grill 轮次索引)

| 轮次 | 决策点 | 结论 |
|---|---|---|
| 1–4 | agent 数量与职责 | 2 agent(编码/测试);需求+设计为主会话 skill;砍 Review agent |
| 5 | skill 清单 | 5 user-invoked,0 model-invoked;无 /setup、无 /pipeline |
| 6 | 状态模型 | 派生(无 state 文件) |
| 7 | 门禁实现 | G2/G4=PreToolUse deny;G1/G0=skill 自查;派生视图=PostToolUse+SessionStart(+PreCompact)注入 |
| 8 | hooks 清单 | 7 个选用;不选 5 类;注入文本事实陈述 |
| 修订 R1 | **H3/H4 改用 SubagentStop + PostToolUse 双钩** | 原方案把 SubagentStop 与 PostToolUse(Task)误判为"重叠"。实为不同时机/不同注入目标:SubagentStop 退出前注入子代理、可自纠正;PostToolUse 退出后注入主会话、做 merge。改为 H3a/H4a(SubagentStop 自纠正)+ H3b/H4b(PostToolUse merge+告知),总 hooks 7→9;并加最大重试防死循环。matcher 仅按工具名,agent 区分在脚本内读 `tool_input.subagent_type`。 |
| 修订 R2 | **参照 superpowers / mattpocock / 官方文档的四项改进** | ① 约束 #5 修正:description = 做什么+何时用(非"只写何时用"),关键用例前置,1536 字符上限(官方纠正)。② 编码 agent 加 git worktree 隔离(抄 superpowers),H3b 增 git diff 校验防谎报。③ 走查双轴化 standards/spec(抄 mattpocock/code-review),H4a 校验两轴非空。④ §8 写入"skill 膨胀免疫力"——skill 数与脚手架数解耦,是对官方 skill 膨胀关切的核心应对;并澄清"skill 协调员"是社区模式非官方。 |
| 9 | 领域资产 | rules 按需 Read;agent 派单模式;conventions 与脚手架平级(防误拷) |
| 10 | 追溯与交接 | 方案 I(agent 吐映射,脚本落盘);矩阵零手改 |
| 11 | 扩展 + 测试 | 三种扩展不变量;测试只覆盖确定性机器 |
| 12–13 | 测试 agent 工作流 | 工具画像完整但 MVP 只走查;接口/Playwright defer;命名保留"测试 agent";test-plan 占位保留 |
