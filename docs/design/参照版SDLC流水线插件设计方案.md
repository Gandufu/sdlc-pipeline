# 参照版 SDLC 流水线插件设计方案

> 本文档为 **grill 式拷问产出**,所有决策均经逐轮追问、给候选、push back 后由用户拍板。
> 文档定位:参照版,用于和现有版本(`D:\workspace\sdlc-agent-pipeline`)对照找差距。
>
> 当前实现版本：`0.4.0`。文档已同步四轮实现修订：R3（崩溃恢复、证据根、原子发布、可观测快速验证）、R4（Codex 适配）、R5（参照 Superpowers 的共享核心 + Claude Code/Codex/OpenCode 项目原生 adapter）与 R6（非阶段 verify 技能）。

---

## 1. 目的与对照定位

### 1.1 定位
一个 **"需求分析 → 设计 → 编码 → 测试"四阶段闭环**研发流水线插件,用 plugin-dev 最佳实践从零实现。

- **对照目标**:与现有版本 `D:\workspace\sdlc-agent-pipeline` 并列,找出编排范式、资产组织、门禁实现上的差距。
- **本版测试阶段的实际范围**:**测试执行(接口测试 / Playwright 功能测试)本版 defer**,MVP 只行使**需求符合性走查**部分；tester 当前保持只读。详见 §2.3 与 §5.4。

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
6. **宿主差异留在适配层**：Claude Code、Codex 与 OpenCode 共用阶段资产、skills、角色正文和校验脚本；manifest、项目目录、调用语法、子代理派发与生命周期映射由薄 adapter 处理，不复制三套业务协议。
7. **项目级优先**：`install_project.py` 只向业务项目写 `.sdlc-pipeline/` 与宿主原生目录，不写用户全局目录。Codex 复用当前登录态，不通过隔离 `CODEX_HOME` 模拟项目安装。

> ⚠️ **关于约束 #1 的一次有意义的扩权**:本方案把"阶段准入门禁"判定为属于"必要的事前拦截",因此 G2/G4 用 **PreToolUse deny** 强制(而非 skill 自觉前置检查)。这升级了门禁的强制性,文档显式记录此升级;其余 hooks 仍严格遵循官方范式。

---

## 2. 组件清单

### 2.1 总览
| 类型 | 数量 | 列表 |
|---|---|---|
| user-invoked phase skill | **5** | `init` · `requirement` · `design` · `code` · `test` |
| diagnostic skill | **1** | `verify`：机制验证、宿主冒烟说明、可观测诊断；不推进阶段 |
| model-invoked SOP skill | **0** | 不设。SOP 内容内联进各 skill / agent system prompt + 显式 Read 协议文件 |
| agent role | **2** | 编码 agent · 测试 agent；Claude Agent、Codex `spawn_agent`、OpenCode `task` 复用角色正文 |
| hook event type | **6** | PreToolUse · SubagentStart · SubagentStop · PostToolUse · SessionStart · PreCompact |
| hook command handler | **11** | 门禁、角色绑定、写入保护、交接自纠正/merge、状态注入 |
| 确定性脚本 | **11** | 阶段门禁/交接/状态 + Codex 异步结果适配 + run journal/原子发布/诊断/身份登记 |

**没有** `/setup`(脚手架已自带预填能力文档,降级为无)、**没有** `/pipeline` 总指挥(全程用户显式敲命令推进,无自动串联)。

### 2.2 skill 清单
| 命令 | 触发方 | 职责 | 产物 | 预加载说明 |
|---|---|---|---|---|
| `/init` / `$init` | 用户 | 读 manifest → 选择脚手架 → 拷骨架到工程根(不覆盖)→ 同步接入 `CLAUDE.md` 与 `AGENTS.md` | 项目骨架 + `工程/docs/existing-framework.md` | description 写"做什么+何时用":"初始化项目:选脚手架、铺骨架、接入能力清单;项目尚未初始化时用" |
| `/requirement` | 用户 | **主会话**内 AskUserQuestion 来回拷问需求 | `docs/requirement-spec.md`(含 R-id) | 需求留在主会话(需与用户交互,subagent 黑盒不可) |
| `/design` | 用户 | **主会话**内 Read 需求 + rules → 写设计文档落盘,返回结构摘要 | `docs/design-doc.md`(含 D-id) | 设计不进 agent:skill 直接 Write 落盘,主会话只收摘要,不撑爆上下文 |
| `/code` / `$code` | 用户 | **派单员**:Read manifest 取 stacks/conventions → 派发编码角色 → 绑定 execution root/run-id → 收交接块 | 源码 + 交接块(含 C-id 映射) | Claude Agent；Codex `spawn_agent`；OpenCode `task` |
| `/test` / `$test` | 用户 | **派单员**:派发 fresh-eye 测试角色 → 收交接块 | 走查结论(MVP)+ 交接块 | MVP 不跑测试执行 |
| `/verify` / `$verify` | 用户 | **非阶段诊断**:运行 L1/L1b/L3，说明 Claude/OpenCode 跑法和 L4/L5 触发条件 | 测试与诊断报告 | 不写阶段产物，不参与状态机 |

> **设计阶段不设 agent 的理由**:设计师 agent 跑时项目里尚无实现代码,"不该看到实现细节"的隔离理由不成立;skill 直接 Write 落盘即可达成"大体量产物不进主会话"。按约束 #3,设计降级为 skill。

### 2.3 agent 清单
| agent | 工具画像 | 隔离刚需(为何是 agent 不是 skill) | MVP 行为 |
|---|---|---|---|
| **编码 agent** | Claude:`Edit/Write/Bash`; Codex:本地读写/shell | **工具限制**:PreToolUse 硬拦 docs/ 的 Write/Edit/apply_patch,H3 用相对运行基线的 git diff 复校全部改动;**上下文隔离**:plan/生成/编译的冗长过程不进主会话 | plan → 代码生成 → 编译 → 自检,交接块返回 C-id 映射 |
| **测试 agent** | 只读；Claude 通过 frontmatter 限权；Codex 拒绝编辑/变更型 Bash，允许只读 Bash 并由 H4 指纹复核；OpenCode permission 禁 edit/bash | **上下文隔离 + fresh eye**:带需求+设计入场,不看编码 agent 的内部 plan 思路，独立判代码是否对题 | **MVP 只做需求符合性走查**，交接块返回 `review-findings` |

> **测试 agent 命名**:保留"测试 agent / 测试阶段"之名。文档显式标注:**测试执行能力(接口测试、Playwright)本版未实现；当前只读工具画像与 MVP 一致**。

> **编码 agent 的 worktree 模型**：Claude 模式可由 `/code` 建立手工 worktree；Codex 复用 App 当前 Local/Worktree checkout；OpenCode 复用当前 session checkout，后两者都禁止嵌套 worktree。H3 始终以运行登记绑定的 execution root 和编码前 baseline 为证据根，而不是信任易漂移的 hook `cwd`。
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
  .claude-plugin/ .codex-plugin/ .opencode/ # 三宿主发布 adapter
  scripts/        # 项目安装器 + 校验/状态/诊断脚本

业务项目安装后：
  .sdlc-pipeline/                    # 三宿主共享运行时（项目内）
  .claude/                           # Claude 项目 skills/agents/hooks
  .agents/skills/ + .codex/hooks.json # Codex 项目 adapter
  .opencode/                         # OpenCode plugin/skills/agents/commands
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
- 拷贝完成后，原子、幂等地接入项目指令：`CLAUDE.md` 追加 `@docs/existing-framework.md`；`AGENTS.md` 追加能力清单说明。Codex/OpenCode 不依赖 Claude 的 Markdown include，后续 skill 仍显式 Read。

### 3.5 agent 取资产的"派单员"模式(模式 p)
约束 #2 卡死:agent 拿不到自动加载的 skill。故由 **`/code`、`/test` skill 充当派单员**:
1. skill 先 Read manifest,取得 `stacks` / `conventions` / `path`。
2. 算出 `rules/<stack>.md` 路径、`conventions/<id>.md` 路径、design-doc/requirement-spec 路径。
3. 把这些路径**拼进 Agent 工具的 prompt**,agent 启动后**显式 Read**。
4. agent 正文零硬编码栈名,所有路径由 manifest 派生。

### 3.6 各阶段资产来源一览
| 阶段 | 用的资产 | 怎么拿到 |
|---|---|---|
| 全阶段 | existing-framework.md | Claude 由 `@import` 自动加载；Codex/各 skill 显式 Read |
| `/requirement` | templates/docs/requirement-spec.md | skill 内 Read |
| `/design` | templates/docs/design-doc.md + traceability-matrix.md + rules/<stack>.md | skill 内 Read(stacks 来自 manifest) |
| `/code`(编码 agent) | 骨架(已拷,含分层样例)+ design-doc + existing-framework(已在上下文)+ rules + conventions | skill 派单塞路径,agent 显式 Read |
| `/test`(测试 agent) | templates/docs/test-plan.md(占位)+ design-doc + requirement-spec + rules | 同上 |

---

## 4. 状态机与门禁

### 4.1 状态模型:**派生**(无 state 文件)
- **真值永远是产物存在性 + 校验结果**。无 `state.json`。
- `/code` 运行期间允许保存一份**非阶段真值**的原子运行登记（Git 项目位于 shared git common dir，非 Git 项目位于系统临时目录），记录 run-id、project/execution root、宿主模式、phase、编码前改动基线、agent_id 和文件指纹。它用于中断现场发现与证据绑定，删除后仍可从正式产物重新派生阶段。
- 每次"当前处于哪个阶段、哪些步骤未完成"由 `derive_state.py` 从产物**实时派生**,杜绝状态漂移。矩阵状态同时写机器 token（如 `[SDLC:COMPILED_PASS]`），不再以自然语言关键词作为唯一判据。
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
| **G0**:`init` 前置 | 未初始化不能用其他命令 | (a) 各 skill 启动查 CLAUDE.md 或 AGENTS.md 是否接入能力清单 |
| **G1**:进入设计前 | requirement-spec.md 存在 + R-id 齐 + 必填章节齐 | (a) `/design` 内部前置自查 |
| **G2**:进入编码前 | design-doc 存在 + 追溯 R→D 闭合 | **(c) PreToolUse deny**(H1,钩 Agent·编码 agent) |
| **G3**:编码 agent 返回后 | 交接块格式 + compiled + 追溯 D→C | **(d) SubagentStop**(H3a)自纠正 + **(b) PostToolUse**(H3b)merge+注入 |
| **G4**:进入测试前 | G3 已通过 | **(c) PreToolUse deny**(H2,钩 Agent·测试 agent) |
| **G5**:测试 agent 返回后 | review-findings + 全链闭合(MVP:R→D→C) | **(d) SubagentStop**(H4a)自纠正 + **(b) PostToolUse**(H4b)merge+注入 |
| **工具硬限制** | 编码 agent 禁碰 docs;测试 agent 禁 Edit 源码 | agent tools + permission(非 hook) |

> (a)=skill 内前置自查;(b)=PostToolUse 注入主会话;(c)=PreToolUse deny;(d)=SubagentStop 自纠正(注入子代理)。
> **G1/G0 用 skill 自查**(文档撰写是 skill 主体,无干净的工具调用可拦);**G2/G4 用 PreToolUse deny**(agent 派发是干净的 Agent 工具调用,适合 hook 硬拦);**G3/G5 用 SubagentStop + PostToolUse 双钩**(见 §4.5)。
>
> ⚠️ **关于 matcher、角色身份与异步结果**：Claude 由 `tool_input.subagent_type` / `agent_type` 识别；Codex 由 `task_name=sdlc_coder|sdlc_tester` 预判，并在 SubagentStart 后把实际 `agent_id` 写入运行登记。Codex `spawn_agent` 返回时最终文本尚未到达，dispatcher 必须在 wait 后调用 `validate_result.py`，不能把 `PostToolUse:Agent` 当作最终交接点。

---

## 4.5 hooks 事件选用清单(逐事件)

### SubagentStop vs PostToolUse(Agent):不重叠,职责不同(关键澄清)
| | 介入时机 | additionalContext 注入给 | 用途 |
|---|---|---|---|
| **SubagentStop** | 子代理**考虑退出、尚未退出**,上下文仍在 | **子代理** | 质量门 + **自纠正**:交接块不合规 → block + 反馈 → 子代理**当场自己修**(带完整思考上下文)→ 再尝试退出 |
| **PostToolUse(Agent)** | 子代理**已彻底退出**,上下文已销毁 | **主会话** | 副作用(merge 矩阵)+ 把处理过的摘要告知主会话 |

> 二者**不是二选一**,而是按能力分工配对:H3 = H3a(SubagentStop,自纠正)+ H3b(PostToolUse,merge+告知);H4 同理。让 agent 在退出前把交接块修对(便宜、不丢上下文),退出后再由主会话侧脚本做落盘与告知。

### 选用的生命周期控制点
> Claude/Codex 配置共有 6 类事件、11 个 command handler。下表 H0–H7 表示逻辑控制点；OpenCode adapter 把可表达的同一逻辑映射到 `tool.execute.before/after` 与消息 transform。

| # | 事件 | matcher(实写) | 阻断/注入 | 脚本 | 注入文本草稿(**事实陈述式**) |
|---|---|---|---|---|---|
| **H0** | SubagentStart | `*` | 记录身份 | `register_subagent.py` | 无文本；把 Codex/Claude 宿主生成的 agent_id 绑定到当前 coder/tester run |
| **H1** | PreToolUse | `Agent` | **阻断 deny**(脚本内判 subagent_type=编码) | `gate_code.py` | `design-doc.md 缺少"模块划分"章节;追溯矩阵需求→设计有 2 条未映射。当前派生阶段:设计中。` |
| **H2** | PreToolUse | `Agent` | **阻断 deny**(脚本内判 subagent_type=测试) | `gate_test.py` | `上一门禁未通过:编码 agent 交接块"设计→代码追溯"未闭合(模块 X 未映射)。当前派生阶段:编码中。` |
| **H3a** | **SubagentStop** | (脚本内判 agent_type=编码) | **阻断 + 注入子代理**(block 决策使 agent 继续) | `validate_code_handoff.py` | `交接块缺 compiled 字段;D2 未给出 C 映射。当前交接块不合规。` |
| **H3b** | PostToolUse | `Agent` | 注入主会话 | `validate_code_handoff.py`(merge 模式) | `编码 agent 已退出。交接块格式:合规。编译:通过。追溯 D→C:4/5,模块 X 未映射,已 merge 入矩阵。派生阶段:编码中。` |
| **H4a** | **SubagentStop** | (脚本内判 agent_type=测试) | **阻断 + 注入子代理**(block 决策使 agent 继续) | `validate_test_handoff.py` | `review-findings 为空;走查结论缺失。当前交接块不合规。` |
| **H4b** | PostToolUse | `Agent` | 注入主会话 | `validate_test_handoff.py`(merge 模式) | `测试 agent 已退出。走查结果已校验并 merge。` |
| **H5** | PostToolUse | `Write\|Edit`（Codex `apply_patch` 按 Edit/Write 匹配） | 注入主会话 | `derive_state.py` | `当前派生阶段:设计完成,可进入编码。未完成步骤:无前置阻塞。` |
| **H6** | SessionStart | — | 注入主会话 | `derive_state.py` | 同 H5，并显示活动运行现场 |
| **H7** | PreCompact | — | 注入主会话 | `derive_state.py` | 同 H5(压缩前重算,防 compaction 丢状态视图) |

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

### 4.6 崩溃恢复与证据根

恢复能力按粒度区分：

| 中断位置 | 恢复语义 |
|---|---|
| 阶段之间 | 完全从文档和矩阵重算；SessionStart 自动注入当前阶段 |
| init | 不覆盖 + 追加标记幂等，可安全重跑 |
| requirement/design 发布中 | 先写同目录临时文件，再 `os.replace` 原子发布；目标文件不会留下半截 |
| code/test 子代理中 | 不恢复模型内部 token/思考；保留活动 run、execution root、agent_id、baseline 和 worktree，使半成品可发现、可检查、可接管或明确 abandon |
| worktree 合并后 | 按 H3/H4 已核验文件的 SHA-256 指纹检查目标树；未合并、漏文件或冲突误改均不能标 complete |

关键不变量：

1. `_lib.project_dir()` 优先采用活动 run 的 execution root，不把 hook `cwd` 或环境变量当作唯一证据。
2. H3 的改动集合是“当前 Git snapshot 相对编码启动 baseline 的差异”，因此阶段前已有未提交 docs 不污染编码证据；编码开始后的 docs 变化仍会被拒绝。
3. `guard_agent_actions.py` 是事前边界，H3 git diff 是事后兜底。Codex `apply_patch` 会解析 Add/Update/Delete/Move 目标，无法解析时拒绝。
4. 当前实现以 Git common dir 保存一个活动 run，因此同一 Git 仓库同一时刻只支持一条受管 SDLC code/test 运行；并发多 worktree 流程需要后续引入多 run registry。

---

## 5. 追溯矩阵与交接块

### 5.1 矩阵写法:**方案 I**(agent 吐映射,脚本落盘)
- 编码/测试 agent **不直接 Edit 矩阵**(守工具限制);它们在**交接块里吐结构化映射**返回。
- **H3/H4 校验脚本** parse 交接块后,把映射 **merge 进 `docs/traceability-matrix.md`**。
- 矩阵是存盘文件(人可读、UI 友好)。R→D 由 `/design` 主会话生成并接受结构门禁；D→C 与走查状态只由 H3/H4 脚本校验后写入。这里的“零手改”特指 agent 交接后的强证据列，不把 R→D 误称为机器证明。

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
| `gate_code.py`(H1) | 进编码前 | requirement-spec 每个 R-id 都在矩阵有 D 映射;design-doc 必填章节齐 |
| `gate_test.py`(H2) | 进测试前 | H3 已通过(D→C 全映射、compiled=pass) |
| `validate_code_handoff.py`(H3a 校验 / H3b merge) | 编码 agent 退出前(H3a)/ 退出后(H3b) | 交接可 parse、compiled=pass、D→C 完整；相对 run baseline 的 Git 改动集必须与 files 一致，docs 越界为硬错误 |
| `validate_test_handoff.py`(H4a 校验 / H4b merge) | 测试 agent 退出前(H4a)/ 退出后(H4b) | 双轴非空、目标 ID 合法、MVP 全链闭合；通过后写入结构化状态 token 和证据指纹 |
| `derive_state.py`(H5/H6/H7) | docs 写入 / 会话启动 / 压缩前 | 从产物派生阶段并附活动 run 现场 |

### 5.6 测试 agent 工作流(层 B,本版 MVP)
- **目标设计**:三级流水线 — ① 需求符合性走查 → ② 接口测试 → ③ Playwright 功能测试。当前只开放 ① 所需的只读能力；②③ 落地时再评审 Write/Bash 权限和测试隔离。
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
| hooks/adapter 接线 | ✅ 确定性部分可测 | 配置静态校验 + 模拟 Claude/Codex hook payload + OpenCode JS 语法/目录契约 |
| 崩溃恢复/合并证据 | ✅ 可测 | 临时 Git repo/worktree → 重复 start、execution root、baseline、指纹核验 |
| 三宿主项目安装 | ✅ 确定性部分可测 | 临时项目运行安装器，断言 `.claude/.codex/.agents/.opencode/.sdlc-pipeline` 与安装后诊断 |
| **skill 的 LLM 行为**(/requirement 拷问质量、/design 设计质量) | ❌ 不单测 | 靠 SKILL.md 指令 + 人工评审 |
| **agent 的 LLM 行为**(编码质量、走查质量) | ❌ 不单测 | 同上 |

> **测试策略只覆盖确定性机器**(脚本 + 拷贝 + 解析);LLM 驱动的 skill/agent 行为**不纳入自动化测试**。

### 7.2 必测行为清单
1. `gate_code.py`:齐全→放行;缺章节→deny,理由事实陈述
2. `gate_test.py`:H3 未过→deny
3. `validate_code_handoff.py`:交接块 parse、compiled 校验、D→C 完整性、merge 正确
4. `validate_test_handoff.py`:MVP 全链闭合、review-findings 校验、merge 正确
5. `derive_state.py`:给定产物→派生阶段 + 未完成步骤正确
6. `/init` 拷贝:目录树、不覆盖、`@docs/existing-framework.md` 追加、conventions 不被拷
7. manifest 解析:路径派生、缺 `conventions` 字段报错
8. 运行现场：start 幂等、execution root 绑定、残留 worktree 可见、合并指纹一致
9. 原子发布：需求/设计临时文件成功 replace，失败不破坏旧目标
10. Codex：manifest、AGENTS.md、SubagentStart agent_id、apply_patch 写入边界、通用 agent_type 的交接识别
11. 项目安装：不创建 `CODEX_HOME`/插件缓存；三宿主 skills/hooks/agents/commands 与 `verify` 入口可发现；OpenCode adapter 通过 JS syntax check

当前 `tests/test_pipeline.py` 为无第三方依赖的快速回归；`tests/test_project_install.py` 覆盖三宿主项目安装、adapter 结构和 `verify` 入口。它们验证机制和安装契约，不宣称验证 LLM 生成质量。

### 7.3 可观测与分层验证

| 层级 | 工具 | 目的 |
|---|---|---|
| L1 | `python tests/test_pipeline.py` | 每次修改快速验证确定性机制 |
| L1b | `python tests/test_project_install.py` | 三宿主项目安装、verify 入口与 adapter 契约，不调用 LLM |
| L2 | Codex plugin validator、skill quick validator、`claude plugin validate` | 验证 manifest/skill/hook 结构 |
| L3 | `python scripts/inspect_pipeline.py --project-root <path>` | 一次输出派生阶段、活动 run、execution root、worktree、未登记残留 |
| L4 | 隔离项目单阶段冒烟 | 只有宿主 hook/agent 接线变化时运行 |
| L5 | 完整 init→test E2E | 只在发布候选或宿主大版本升级时运行 |

选择这一分层是为了让插件保持可调试、可观测，而不是把正确性押在昂贵且有模型波动的全流程重跑上。如果未来没有新增可确定性断言，保持现有测试层级，不为了“有测试”而堆脆弱的 prompt 快照。

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

### 三宿主适配边界

| 适配点 | Claude Code | Codex | OpenCode | 共用真值 |
|---|---|---|---|---|
| 发布入口 | `.claude-plugin` | `.codex-plugin` | `package.json` + `.opencode/plugins` | 名称/版本/协议 |
| 项目入口 | `.claude/` | `.agents/skills` + `.codex/hooks.json` | `.opencode/` | `.sdlc-pipeline/` |
| skill 调用 | `/sdlc-pipeline-*` | `$sdlc-pipeline-*` | `/sdlc-*` command | `skills/<name>/SKILL.md` |
| coder/tester | Agent | `spawn_agent` | `task` + custom agent | `agents/coder.md`、`agents/tester.md` |
| 生命周期 | Claude hooks | 派发前 hooks + wait 后 `validate_result.py` | `tool.execute.before/after` | Python gate/validate/derive |
| 编辑 | Write/Edit | apply_patch | edit/bash permission | guard + H3 diff |
| worktree | 手工/当前树 | App Local/Worktree | 当前 session checkout | execution root |

正式插件仍可用宿主根变量；项目安装器则把路径渲染为业务项目内
`.sdlc-pipeline/`。Codex 项目 hooks 首次运行或内容变化后必须经 `/hooks` 信任
审核，这不涉及重新登录。Codex 最终交接由 wait 后的 `validate_result.py` 固化，
不依赖异步派发时过早发生的 PostToolUse。OpenCode 当前没有 SubagentStop 等价续回语义，因此
adapter 在 task 返回后拒绝无效交接并保留现场。

### skill 膨胀免疫力(对照 superpowers / ECC 的结构优势)
官方明说 skill 数量增长是真实问题:skill listing 占 context 预算 1%,描述超 1,536 字符会被截断,需靠 progressive disclosure + `skillOverrides` + `/doctor` 治理(见 [Skills 文档](https://code.claude.com/docs/en/skills.md))。`obra/superpowers`(~86 skill)、ECC(上百)、社区 `claude-skills`(345)都走"skill 堆积"路线,正是膨胀重灾区。

**本方案的结构优势:阶段 skill 数量与脚手架数解耦**——加脚手架只改 `templates/<id>/` + `conventions/<id>.md` + manifest 一条(数据),**不加阶段 skill**;加栈只加 `rules/<stack>.md`;加文档模板只加 `templates/docs/*.md`。阶段 skill 恒定 **5 个**(四阶段 + init),无论承载多少脚手架/栈。这是相对 superpowers/ECC 的核心对照点,也是对"skill 会膨胀"这一官方关切的最强应对:**把变异放进数据,不放进阶段 skill。**

`verify` 是刻意独立出来的非阶段诊断 skill：它不承载脚手架/栈差异，也不参与流水线状态机，只把 L1/L1b/L3 与宿主冒烟路径显式化。换句话说，阶段复杂度仍固定为 5，新增的是可调试入口，不是第六个研发阶段。

> 概念澄清:"skill 当协调员"是 superpowers 的**社区模式,非官方**。官方推荐的组合单元是 skill+subagent 或 plugin,从不推荐"主 skill 编排子 skill"。本方案的 `/code`、`/test` 派单员 = skill(任务定义)+ agent(隔离执行),正合官方范式。

---

## 附录:决策溯源(grill 轮次索引)

| 轮次 | 决策点 | 结论 |
|---|---|---|
| 1–4 | agent 数量与职责 | 2 agent(编码/测试);需求+设计为主会话 skill;砍 Review agent |
| 5 | skill 清单 | 5 个阶段 user-invoked,0 model-invoked;无 /setup、无 /pipeline；R6 增加非阶段 verify |
| 6 | 状态模型 | 派生(无 state 文件) |
| 7 | 门禁实现 | G2/G4=PreToolUse deny;G1/G0=skill 自查;派生视图=PostToolUse+SessionStart(+PreCompact)注入 |
| 8 | hooks 初版清单 | 初版 7 个控制点;不选 5 类;注入文本事实陈述；后续由 R1/R4 扩展 |
| 修订 R1 | **H3/H4 改用 SubagentStop + PostToolUse 双钩** | 原方案把 SubagentStop 与 PostToolUse(Task)误判为"重叠"。实为不同时机/不同注入目标:SubagentStop 退出前注入子代理、可自纠正;PostToolUse 退出后注入主会话、做 merge。改为 H3a/H4a(SubagentStop 自纠正)+ H3b/H4b(PostToolUse merge+告知),总 hooks 7→9;并加最大重试防死循环。matcher 仅按工具名,agent 区分在脚本内读 `tool_input.subagent_type`。 |
| 修订 R2 | **参照 superpowers / mattpocock / 官方文档的四项改进** | ① 约束 #5 修正:description = 做什么+何时用(非"只写何时用"),关键用例前置,1536 字符上限(官方纠正)。② 编码 agent 加 git worktree 隔离(抄 superpowers),H3b 增 git diff 校验防谎报。③ 走查双轴化 standards/spec(抄 mattpocock/code-review),H4a 校验两轴非空。④ §8 写入"skill 膨胀免疫力"——skill 数与脚手架数解耦,是对官方 skill 膨胀关切的核心应对;并澄清"skill 协调员"是社区模式非官方。 |
| 修订 R3 | **崩溃恢复、证据根与可观测** | 增加非阶段真值 run journal；execution root 优先；编码前 baseline diff；阶段文档原子发布；worktree 残留诊断；合并文件指纹；docs 双层防护；矩阵结构化 token；快速回归与分层验证。阶段间可自动恢复，agent 内部不做 token 级续跑，但现场可发现、可接管、可明确放弃。 |
| 修订 R4 | **Codex 初版适配（已由 R5 收敛）** | 初版验证了 AGENTS.md 同步、角色复用、agent_id 绑定、apply_patch 边界防护及快速测试；其中 marketplace/隔离插件目录思路已在 R5 改为项目根 `.codex` + `.agents` 原生配置。 |
| 修订 R5 | **Superpowers 式三宿主架构** | 共享 core + Claude/Codex/OpenCode 薄 adapter；新增项目安装器与 `.sdlc-pipeline` runtime；Codex 改为 `.agents/skills` + `.codex/hooks.json` 真项目级方案，并以 `validate_result.py` 处理 wait 后的异步最终交接；OpenCode 增加本地 plugin/custom agents/commands；新增无需 LLM 的安装契约测试。 |
| 修订 R6 | **验证技能** | 增加非阶段 `verify` skill，让 Claude Code、Codex、OpenCode 可直接执行快速机制测试、安装契约测试和 `inspect_pipeline.py` 诊断；L4/L5 仍按需在隔离业务项目运行，避免日常修改被完整 E2E 拖慢。 |
| 9 | 领域资产 | rules 按需 Read;agent 派单模式;conventions 与脚手架平级(防误拷) |
| 10 | 追溯与交接 | 方案 I(agent 吐映射,脚本落盘);R→D 由 design 生成，强证据列由脚本写 |
| 11 | 扩展 + 测试 | 三种扩展不变量;测试只覆盖确定性机器 |
| 12–13 | 测试 agent 工作流 | 工具画像完整但 MVP 只走查;接口/Playwright defer;命名保留"测试 agent";test-plan 占位保留 |
