import { spawn } from "node:child_process"
import { existsSync } from "node:fs"
import { fileURLToPath } from "node:url"
import path from "node:path"

const AGENTS = {
  "sdlc-coder": "coder",
  "sdlc-tester": "tester",
}
const taskDeadlines = new Map()
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
      characters: typeof segment.text === "string" ? segment.text.length : 0,
      sha256: segment.sha256,
      preview: typeof segment.text === "string" ? segment.text.slice(0, 160) : "",
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
    asset: envelope.asset ? {
      uri: envelope.asset.uri,
      sha256: envelope.asset.sha256,
      size: envelope.asset.size,
    } : undefined,
    extractor: envelope.extractor,
    next_action: "Use only source_id/anchor above. Query sdlc_query_source for bounded text; do not read the original external path.",
  }
}

export function sourcePayload(args) {
  const kind = args.source_type
  const sourceIsFilePath = kind === "file" && !args.uri && args.source
  return {
    kind,
    content: args.content,
    source: sourceIsFilePath ? undefined : args.source,
    uri: args.uri || (sourceIsFilePath ? args.source : undefined),
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
        description: "摄取一份原始需求来源为 Source Markdown，并返回有界 receipt。file 必须提供 uri；source 中的 file 路径会安全规范化为 uri。图片等二进制文件默认保存受控元数据和原件，不伪造视觉语义。只使用返回的 source_id/anchor；需要正文时调用 sdlc_query_source，绝不再读取项目外原路径。",
        args: {
          source_type: tool.schema.enum(["inline", "file", "url", "document"]),
          content: tool.schema.string().optional(),
          source: tool.schema.string().optional().describe("来源标签；file 的路径兼容为 uri。"),
          uri: tool.schema.string().optional().describe("file 路径、URL 或受控来源 URI。"),
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
        description: "按 source_id 和 anchor 读取一段已摄取原文。只返回受限片段与 hash。",
        args: {
          source_id: tool.schema.string(),
          anchor: tool.schema.string(),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_query_source")
          return JSON.stringify(await invoke(
            rootOf(context, fallbackRoot),
            "source-query",
            args,
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
        description: "写入一个独立 Requirement artifact；R/Feature/AC ID 均由 Core 分配或规范化，feature_id 可传语义 hint，禁止为格式猜测而重试。",
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
        description: "写入一个 Verification artifact，并用 R/D/AC ID 建立验收关系。",
        args: {
          candidate_id: tool.schema.string(),
          verification: tool.schema.object({
            id: tool.schema.string().optional(),
            requirement_ids: tool.schema.array(tool.schema.string()),
            design_ids: tool.schema.array(tool.schema.string()),
            acceptance_criteria_ids: tool.schema.array(tool.schema.string()),
            level: tool.schema.enum(["unit", "integration", "functional"]),
            test_key: tool.schema.string(),
            selector: tool.schema.string(),
            preconditions: tool.schema.string(),
            expected: tool.schema.string(),
            mandatory: tool.schema.boolean(),
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
      const deadlineSeconds = Number(result.deadline_seconds)
      if (!Number.isInteger(deadlineSeconds) || deadlineSeconds <= 0) {
        throw new Error(`Core 未返回有效的 ${role} deadline`)
      }
      await logPluginEvent(client, `${role}.dispatched`, {
        session_id: input.sessionID,
        deadline_seconds: deadlineSeconds,
        requirement_count: result.requirement_count,
        context_characters: result.context_pack.characters,
        context_resources: result.context_pack.resource_count,
      })
      const deadline = setTimeout(async () => {
        try {
          await logPluginEvent(client, `${role}.deadline_exceeded`, {
            session_id: input.sessionID,
            deadline_seconds: deadlineSeconds,
          }, "warn")
          await invoke(fallbackRoot, "task-cancel", {
            reason: `${role} deadline exceeded after ${deadlineSeconds}s`,
          })
        } catch (error) {
          await logPluginEvent(client, `${role}.cancel_failed`, {
            session_id: input.sessionID,
            error: String(error),
          }, "error")
        } finally {
          await client.session.abort({
            path: { id: input.sessionID },
            query: { directory: fallbackRoot },
          })
        }
      }, deadlineSeconds * 1000)
      deadline.unref()
      taskDeadlines.set(input.callID, deadline)
      const manifest = result.context_pack.paths[0]
      const taskObjective = String(output.args?.description || "").trim()
      delete output.args.command
      output.args.prompt = `[SDLC context pack] ${manifest}\n`
        + `${result.instruction}\n`
        + (taskObjective ? `本次任务目标：${taskObjective}。\n` : "")
        + `${role} deadline: ${deadlineSeconds}s。`
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
      const deadline = taskDeadlines.get(input.callID)
      if (deadline) clearTimeout(deadline)
      taskDeadlines.delete(input.callID)
      await invoke(fallbackRoot, "task-after", {
        role,
        output: output.output || "",
      })
      await invoke(fallbackRoot, "lifecycle", {
        action: role === "coder"
          ? "compile_restart_verify"
          : "verify_delivery",
      })
      await logPluginEvent(client, `${role}.completed`, {
        session_id: input.sessionID,
      })
    },
  }
}

export default SdlcPipelinePlugin
