import { spawn } from "node:child_process"
import { existsSync } from "node:fs"
import { fileURLToPath } from "node:url"
import path from "node:path"

const AGENTS = {
  "sdlc-coder": "coder",
  "sdlc-tester": "tester",
}
const taskWriteSessions = new Set()
const PLUGIN_PROJECT_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)), "..", ".."
)

function localCoreScript(root) {
  const installed = path.join(
    root, ".sdlc-pipeline", "runtime", "scripts", "sdlc.py"
  )
  if (existsSync(installed)) return installed
  const development = path.join(root, "scripts", "sdlc.py")
  if (existsSync(development)) return development
}

function coreScript(root) {
  for (const candidate of [root, PLUGIN_PROJECT_ROOT]) {
    const script = localCoreScript(candidate)
    if (script) return script
  }
  throw new Error("sdlc-pipeline Python core is missing")
}

export function pythonExecutable(environment = process.env, platformName = process.platform) {
  const configured = environment.SDLC_PYTHON || environment.PYTHON
  if (typeof configured === "string" && configured.trim()) return configured.trim()
  return platformName === "win32" ? "python" : "python3"
}

export function sourceReceipt(result) {
  const envelope = result?.envelope
  if (!envelope || typeof envelope !== "object") return result
  const sourceId = envelope.source_id
  const anchors = Array.isArray(envelope.segments)
    ? envelope.segments.map((segment) => ({
      anchor: segment.anchor,
      kind: segment.kind || (typeof segment.text === "string" ? "text" : "asset"),
      characters: typeof segment.text === "string" ? segment.text.length : 0,
      sha256: segment.sha256,
      preview: typeof segment.text === "string" ? segment.text.slice(0, 160) : "",
      asset_ref: segment.asset_ref,
      media_type: segment.media_type,
    }))
    : []
  return {
    ok: result.ok === true,
    source_id: sourceId,
    kind: envelope.kind,
    source: envelope.source,
    uri: envelope.uri,
    media_type: envelope.media_type,
    sha256: envelope.sha256,
    anchors,
    canonical_path: typeof sourceId === "string"
      ? `.sdlc-pipeline/work/sources/${sourceId}/index.json`
      : undefined,
    asset_ref: envelope.asset_ref,
    manifest_ref: envelope.manifest_ref,
    bundle: envelope.bundle,
    extractor: envelope.extractor,
    next_action: "Use only source_id/anchor above; do not read uncontrolled paths. Query text anchors with sdlc_query_source. Asset anchors return a controlled asset_ref that keeps the original format; never decode binary as text.",
  }
}

export function sourcePayload(args) {
  const kind = args.source_type
  const sourceIsPath = ["file", "directory"].includes(kind)
    && !args.uri
    && args.source
  return {
    kind,
    content: args.content,
    source: sourceIsPath ? undefined : args.source,
    uri: args.uri || (sourceIsPath ? args.source : undefined),
    media_type: args.media_type,
    allow_external_copy: args.allow_external_copy,
  }
}

export function approvalPayload(args) {
  const candidateId = typeof args?.candidate_id === "string"
    ? args.candidate_id.trim()
    : ""
  const contentHash = typeof args?.content_hash === "string"
    ? args.content_hash.trim()
    : ""
  const missing = [
    ...(candidateId ? [] : ["candidate_id"]),
    ...(contentHash ? [] : ["content_hash"]),
    ...(args?.confirmed === true ? [] : ["confirmed=true"]),
  ]
  if (missing.length > 0) {
    return {
      ok: false,
      code: "invalid_approval_arguments",
      error: `批准 Candidate 的参数不完整：缺少 ${missing.join(", ")}。不要调用 Core 或重建候选；使用 validate 返回的 candidate_id + content_hash + confirmed=true 原样重试。`,
      retryable: true,
    }
  }
  return {
    ok: true,
    candidate_id: candidateId,
    content_hash: contentHash,
    confirmed: true,
  }
}

async function logPluginEvent(client, message, extra = {}, level = "info") {
  try {
    await client?.app?.log?.({
      body: {
        service: "sdlc-pipeline",
        level,
        message,
        extra,
      },
    })
  } catch {
    // Logging must never block or fail a delivery hook.
  }
}

function stopProcessTree(child) {
  return new Promise((resolve) => {
    if (!child?.pid) {
      resolve()
      return
    }
    if (process.platform === "win32") {
      const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
        windowsHide: true,
        shell: false,
        stdio: "ignore",
      })
      killer.on("error", () => resolve())
      killer.on("close", () => resolve())
      return
    }
    try {
      process.kill(-child.pid, "SIGKILL")
    } catch {
      child.kill("SIGKILL")
    }
    child.once("close", () => resolve())
    setTimeout(resolve, 5000).unref()
  })
}

function invoke(root, operation, payload = {}, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonExecutable(), [coreScript(root), operation, "--root", root], {
    cwd: root,
    env: {
      ...process.env,
      PYTHONUTF8: "1",
      PYTHONIOENCODING: "utf-8",
    },
    windowsHide: true,
    shell: false,
    detached: process.platform !== "win32",
    stdio: ["pipe", "pipe", "pipe"],
  })
    let stdout = ""
    let stderr = ""
    let settled = false
    let cancelling = false
    const finish = (error, data) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      options.signal?.removeEventListener("abort", abort)
      if (error) reject(error)
      else resolve(data)
    }
    const abort = async () => {
      if (cancelling || settled) return
      cancelling = true
      await stopProcessTree(child)
      finish(new Error(`sdlc ${operation} cancelled`))
    }
    const timer = setTimeout(async () => {
      if (cancelling || settled) return
      cancelling = true
      await stopProcessTree(child)
      finish(new Error(`sdlc ${operation} deadline exceeded`))
    }, options.timeoutMs || 30 * 60 * 1000)
    options.signal?.addEventListener("abort", abort, { once: true })
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8")
      if (stdout.length > 10 * 1024 * 1024) abort()
    })
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8")
    })
    child.on("error", (error) => {
      if (!cancelling) finish(error)
    })
    child.on("close", (status) => {
      if (cancelling) return
      const lines = stdout.trim().split(/\r?\n/)
      let data
      try {
        data = JSON.parse(lines.at(-1) || "{}")
      } catch {
        finish(new Error(`sdlc core returned invalid JSON: ${stdout}`))
        return
      }
      if ((status ?? 1) !== 0 || data.ok === false) {
        finish(new Error(data.error || stderr || `sdlc ${operation} failed`))
        return
      }
      finish(null, data)
    })
    child.stdin.end(JSON.stringify(payload))
  })
}

export function resolveProjectRoot(context = {}, fallback = PLUGIN_PROJECT_ROOT) {
  const candidates = [
    context?.directory,
    context?.worktree,
    fallback,
    PLUGIN_PROJECT_ROOT,
  ]
  const seen = new Set()
  for (const candidate of candidates) {
    if (typeof candidate !== "string" || !candidate.trim()) continue
    const resolved = path.resolve(candidate)
    const key = resolved.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    if (localCoreScript(resolved)) return resolved
  }
  return PLUGIN_PROJECT_ROOT
}

function rootOf(context, fallback) {
  return resolveProjectRoot(context, fallback)
}

function requireAgent(context, allowed, toolName) {
  const agent = context?.agent
  if (!allowed.includes(agent)) {
    throw new Error(`${toolName} is not available to agent ${agent || "unknown"}`)
  }
}

export const SdlcPipelinePlugin = async ({ client, directory, worktree }) => {
  const { tool } = await import("@opencode-ai/plugin")
  const fallbackRoot = resolveProjectRoot({ directory, worktree })
  const sourceRef = tool.schema.object({
    source_id: tool.schema.string(),
    anchor: tool.schema.string(),
  })
  const specQuestion = tool.schema.object({
    id: tool.schema.string(),
    prompt: tool.schema.string(),
    answer: tool.schema.string(),
    status: tool.schema.enum(["resolved"]),
    rationale: tool.schema.string(),
  })
  const moduleSpec = tool.schema.object({
    name: tool.schema.string(),
    responsibility: tool.schema.string(),
    seam: tool.schema.string(),
  })
  const interfaceSpec = tool.schema.object({
    name: tool.schema.string(),
    input: tool.schema.string(),
    output: tool.schema.string(),
    errors: tool.schema.array(tool.schema.string()),
  })
  const dataField = tool.schema.object({
    name: tool.schema.string(),
    type: tool.schema.string(),
    required: tool.schema.boolean(),
    source_ref: tool.schema.string().optional(),
  })
  const dataContract = tool.schema.object({
    name: tool.schema.string(),
    fields: tool.schema.array(dataField),
  })
  return {
    tool: {
      sdlc_status: tool({
        description: "读取当前阶段、恢复点、门禁、诊断和下一步。",
        args: {},
        async execute(_args, context) {
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "status", {}, {
            signal: context.abort,
          }))
        },
      }),
      sdlc_ingest_source: tool({
        description: "受控摄取 inline/file/directory 来源并保持原格式。file 指向目录时 Core 自动按 directory 处理；文件和目录树原字节复制到 Source files/，manifest.json 只保存路径/hash/media 索引。文本生成可查询 anchor；PNG 等二进制生成 asset anchor，查询后返回受控 asset_ref，绝不把二进制解码成 content.md 或伪造视觉语义。项目外路径必须 allow_external_copy=true。",
        args: {
          source_type: tool.schema.enum(["inline", "file", "directory", "url", "document"]),
          content: tool.schema.string().optional(),
          source: tool.schema.string().optional().describe("来源标签；file/directory 的路径兼容为 uri。"),
          uri: tool.schema.string().optional().describe("文件、目录、URL 或受控来源 URI。"),
          media_type: tool.schema.string().optional(),
          allow_external_copy: tool.schema.boolean().optional(),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_ingest_source")
          const result = await invoke(rootOf(context, fallbackRoot), "publish", {
            kind: "source",
            payload: sourcePayload(args),
          }, { signal: context.abort })
          return JSON.stringify(sourceReceipt(result))
        },
      }),
      sdlc_query_source: tool({
        description: "按 source_id 和 anchor 查询受控来源。文本 anchor 返回有界原文；asset anchor 返回保持原格式的 asset_ref、媒体类型与 hash，不把二进制转换为文本。",
        args: {
          source_id: tool.schema.string(),
          anchor: tool.schema.string(),
        },
        async execute(args, context) {
          requireAgent(
            context,
            ["sdlc-main", "sdlc-coder"],
            "sdlc_query_source",
          )
          return JSON.stringify(await invoke(
            rootOf(context, fallbackRoot),
            "source-query",
            {
              ...args,
              requester: context.agent,
            },
            { signal: context.abort },
          ))
        },
      }),
      sdlc_begin_candidate: tool({
        description: "开始一个 Layout v3 Spec Candidate；正文后续按 Markdown artifact 分片写入。",
        args: {
          title: tool.schema.string(),
          source_refs: tool.schema.array(sourceRef),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_begin_candidate")
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "spec-candidate", {
            action: "begin",
            ...args,
          }, { signal: context.abort }))
        },
      }),
      sdlc_put_requirement: tool({
        description: "写入一个独立 Requirement artifact。acceptance_criteria 必须是非空数组，每项必须含 given/when/then/source_refs；只省略 AC id（Core 分配），不可省略整个数组。R/Feature/AC ID 均由 Core 分配或规范化，feature_id 可传语义 hint，禁止为格式猜测而重试。",
        args: {
          candidate_id: tool.schema.string(),
          requirement: tool.schema.object({
            id: tool.schema.string().optional(),
            feature_id: tool.schema.string(),
            title: tool.schema.string(),
            goal: tool.schema.string(),
            actor: tool.schema.string(),
            scope: tool.schema.array(tool.schema.string()),
            non_goals: tool.schema.array(tool.schema.string()),
            source_refs: tool.schema.array(sourceRef),
            decision_ids: tool.schema.array(tool.schema.string()).optional(),
            main_flow: tool.schema.array(tool.schema.string()),
            alternate_flows: tool.schema.array(tool.schema.object({
              name: tool.schema.string(),
              steps: tool.schema.array(tool.schema.string()),
            })),
            acceptance_criteria: tool.schema.array(tool.schema.object({
              id: tool.schema.string().optional(),
              given: tool.schema.string(),
              when: tool.schema.string(),
              then: tool.schema.string(),
              source_refs: tool.schema.array(sourceRef),
            })),
            supersedes: tool.schema.string().optional(),
          }),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_put_requirement")
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "spec-candidate", {
            action: "put-requirement",
            ...args,
          }, { signal: context.abort }))
        },
      }),
      sdlc_put_design: tool({
        description: "写入一个 Design artifact；只声明 module seam 和 extension point，不预测代码文件。extension_points 必须逐字来自 .sdlc-pipeline/contracts/scaffold.json 的已声明 ID，禁止编造泛称。",
        args: {
          candidate_id: tool.schema.string(),
          design: tool.schema.object({
            id: tool.schema.string().optional(),
            title: tool.schema.string(),
            requirement_ids: tool.schema.array(tool.schema.string()),
            decision_ids: tool.schema.array(tool.schema.string()).optional(),
            modules: tool.schema.array(moduleSpec),
            interfaces: tool.schema.array(interfaceSpec),
            data_contracts: tool.schema.array(dataContract),
            extension_points: tool.schema.array(tool.schema.string()),
            decisions: tool.schema.array(tool.schema.string()),
          }),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_put_design")
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "spec-candidate", {
            action: "put-design",
            ...args,
          }, { signal: context.abort }))
        },
      }),
      sdlc_put_verification: tool({
        description: "写入一个 Verification artifact，并用 R/D/AC ID 建立验收关系。selector 是否可省略及其路径模式由 lifecycle test_key 合约决定；v1.1 测试套件必须显式声明 selector。",
        args: {
          candidate_id: tool.schema.string(),
          verification: tool.schema.object({
            id: tool.schema.string().optional(),
            requirement_ids: tool.schema.array(tool.schema.string()),
            design_ids: tool.schema.array(tool.schema.string()),
            acceptance_criteria_ids: tool.schema.array(tool.schema.string()),
            level: tool.schema.enum(["unit", "functional"]),
            test_key: tool.schema.string(),
            selector: tool.schema.string().optional(),
            preconditions: tool.schema.string(),
            expected: tool.schema.string(),
            mandatory: tool.schema.boolean(),
            test_basis: tool.schema.enum([
              "acceptance", "risk", "regression", "contract",
            ]).optional(),
            intent: tool.schema.string().optional(),
            coverage: tool.schema.string().optional(),
          }),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_put_verification")
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "spec-candidate", {
            action: "put-verification",
            ...args,
          }, { signal: context.abort }))
        },
      }),
      sdlc_validate_candidate: tool({
        description: "确定性校验当前 Candidate，生成 preview；通过后返回冻结 revision/hash。",
        args: {
          candidate_id: tool.schema.string(),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_validate_candidate")
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "spec-candidate", {
            action: "validate",
            ...args,
          }, { signal: context.abort }))
        },
      }),
      sdlc_approve_candidate: tool({
        description: "批准用户看到的精确 Candidate；只传 ID/hash/confirmed，不重传契约正文。三个字段必须在同一次调用中完整传入；字段不完整时只返回可重试错误，不会调用 Core 或写入 journal。",
        args: {
          candidate_id: tool.schema.string(),
          content_hash: tool.schema.string(),
          confirmed: tool.schema.boolean(),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_approve_candidate")
          const approval = approvalPayload(args)
          if (!approval.ok) return JSON.stringify(approval)
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "spec-candidate", {
            action: "approve",
            candidate_id: approval.candidate_id,
            content_hash: approval.content_hash,
            confirmed: approval.confirmed,
          }, { signal: context.abort }))
        },
      }),
      sdlc_save_spec_work: tool({
        description: "保存可恢复的临时 spec 工作内容。内容只写入临时 Markdown，JSON 仅保存索引和 hash；不要传 state、decisions 或 notes。字段是结构化参数，不要嵌套为 JSON 字符串。Candidate 发布成功后 Core 自动清理该临时内容。",
        args: {
          question: specQuestion.optional(),
          source_refs: tool.schema.array(sourceRef).optional(),
          confirmed_facts: tool.schema.array(tool.schema.string()).optional(),
          assumptions: tool.schema.array(tool.schema.string()).optional(),
          risks: tool.schema.array(tool.schema.string()).optional(),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_save_spec_work")
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "publish", {
            kind: "spec-work",
            payload: args,
          }, { signal: context.abort }))
        },
      }),
      sdlc_query_spec_work: tool({
        description: "读取受控的临时 spec 工作内容，用于中断恢复。status 只返回索引摘要，不返回这些内容。",
        args: {},
        async execute(_args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_query_spec_work")
          return JSON.stringify(await invoke(
            rootOf(context, fallbackRoot),
            "spec-work-query",
            {},
            { signal: context.abort },
          ))
        },
      }),
      sdlc_begin_rework: tool({
        description: "登记结构化 Feedback 并开始受控返工。人工预览/验收缺陷或自动测试失败都必须先走此入口；Core 根据分类路由到 code 或 spec，并使既有通过门禁失效，直到重新验证。",
        args: {
          origin: tool.schema.enum([
            "manual_preview", "manual_acceptance", "automated_test",
          ]),
          classification: tool.schema.enum([
            "implementation", "spec", "test_contract",
          ]),
          summary: tool.schema.string(),
          expected: tool.schema.string(),
          actual: tool.schema.string(),
          reproduction_steps: tool.schema.array(tool.schema.string()),
          affected_ids: tool.schema.array(tool.schema.string()),
          source_refs: tool.schema.array(sourceRef),
          evidence_refs: tool.schema.array(tool.schema.string()),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_begin_rework")
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "rework", {
            ...args,
            source_refs: args.source_refs.map(
              (reference) => `${reference.source_id}#${reference.anchor}`,
            ),
          }, { signal: context.abort }))
        },
      }),
      sdlc_lifecycle: tool({
        description: "执行一个交付意图；内部生命周期由 Core 管理。",
        args: {
          action: tool.schema.enum([
            "init", "verify_delivery",
          ]),
          options: tool.schema.string().optional().describe(
            "Optional JSON. init: {template}.",
          ),
        },
        async execute(args, context) {
          const options = args.options ? JSON.parse(args.options) : {}
          const allowed = {
            "sdlc-main": ["init"],
          }
          if (!allowed[context?.agent]?.includes(args.action)) {
            throw new Error(`agent ${context?.agent || "unknown"} cannot run lifecycle ${args.action}`)
          }
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "lifecycle", {
            action: args.action,
            ...options,
          }, { signal: context.abort }))
        },
      }),
      sdlc_finalize: tool({
        description: "高风险内部工具：仅在 mandatory 测试通过且用户明确确认后创建 manifest、commit 和 annotated tag。",
        args: {
          version: tool.schema.string(),
          summary: tool.schema.string(),
          confirmed: tool.schema.boolean(),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_finalize")
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "finalize", {
            ...args,
          }, { signal: context.abort }))
        },
      }),
    },

    "tool.execute.before": async (input, output) => {
      if (["edit", "write", "apply_patch"].includes(input.tool)) {
        const target = output.args?.filePath || output.args?.path
        let checked
        if (target) {
          checked = await invoke(fallbackRoot, "write-check", {
            path: target,
            owner_pid: process.pid,
          })
        }
        if (checked?.heartbeat?.active && input.sessionID && !taskWriteSessions.has(input.sessionID)) {
          taskWriteSessions.add(input.sessionID)
          await logPluginEvent(client, `${checked.role}.first_write`, {
            session_id: input.sessionID,
            tool: input.tool,
          })
        }
        return
      }
      if (input.tool !== "task") return
      const role = AGENTS[output.args?.subagent_type]
      if (!role) {
        throw new Error("sdlc-main 只能派发 sdlc-coder 或 sdlc-tester")
      }
      const result = await invoke(fallbackRoot, "task-before", {
        role,
        owner_pid: process.pid,
      })
      await logPluginEvent(client, `${role}.dispatched`, {
        session_id: input.sessionID,
        requirement_count: result.requirement_count,
        context_characters: result.context_pack.characters,
        context_resources: result.context_pack.resource_count,
      })
      const manifest = result.context_pack.paths[0]
      const taskObjective = String(output.args?.description || "").trim()
      delete output.args.command
      output.args.prompt = `[SDLC context pack] ${manifest}\n`
        + `${result.instruction}\n`
        + (taskObjective ? `本次任务目标：${taskObjective}。\n` : "")
        + (role === "coder"
          ? "只实现业务代码；禁止读取、创建或修改任何测试脚本；"
          : "只编写声明的测试脚本；禁止修改业务源码或直接运行 lifecycle；")
        + "不要展开读取 Core 源码；"
        + "完成实现后立即返回约定 JSON handoff。"
    },

    "tool.execute.after": async (input, output) => {
      if (input.tool !== "task") return
      const role = AGENTS[input.args?.subagent_type]
      if (!role) return
      await invoke(fallbackRoot, "task-after", {
        role,
        output: output.output || "",
      })
      const lifecycleResult = await invoke(fallbackRoot, "lifecycle", {
        action: role === "coder"
          ? "compile_restart_verify"
          : "verify_delivery",
      })
      if (role === "coder") {
        const accessUrl = lifecycleResult?.preview?.access_url
        const preview = accessUrl
          ? `预览已启动：${accessUrl}`
          : "预览进程已启动；当前模板未声明 HTTP 访问地址。"
        output.output = `${output.output || ""}\n[SDLC code gate] compile/package/readiness 通过；${preview}`
      }
      await logPluginEvent(client, `${role}.completed`, {
        session_id: input.sessionID,
      })
    },
  }
}

export default SdlcPipelinePlugin
