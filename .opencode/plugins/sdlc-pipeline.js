import { spawn } from "node:child_process"
import { existsSync } from "node:fs"
import { fileURLToPath } from "node:url"
import path from "node:path"

const AGENTS = {
  "sdlc-coder": "coder",
}
const CODER_DEADLINE_SECONDS = 5 * 60
const coderDeadlines = new Map()
const coderWriteSessions = new Set()
const PLUGIN_PROJECT_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)), "..", ".."
)

function localCoreScript(root) {
  const installed = path.join(root, ".sdlc-pipeline", "scripts", "sdlc.py")
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
        description: "摄取一份原始需求来源并返回可引用的 SourceEnvelope。",
        args: {
          source_type: tool.schema.enum(["inline", "file", "url", "document"]),
          content: tool.schema.string().optional(),
          source: tool.schema.string().optional(),
          uri: tool.schema.string().optional(),
          media_type: tool.schema.string().optional(),
          allow_external_copy: tool.schema.boolean().optional(),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_ingest_source")
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "publish", {
            kind: "source",
            payload: {
              kind: args.source_type,
              content: args.content,
              source: args.source,
              uri: args.uri,
              media_type: args.media_type,
              allow_external_copy: args.allow_external_copy,
            },
          }, { signal: context.abort }))
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
        description: "开始一个 Schema v2 Spec Candidate；正文后续按小 artifact 分片写入。",
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
        description: "写入一个独立 Requirement artifact；ID 缺省时由 Core 分配。",
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
        description: "写入一个 Design artifact；只声明 module seam 和 extension point，不预测代码文件。extension_points 必须逐字来自 .sdlc-pipeline/scaffold.json 的已声明 ID，禁止编造泛称。",
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
        description: "批准用户看到的精确 Candidate；只传 ID/hash/confirmed，不重传契约正文。",
        args: {
          candidate_id: tool.schema.string(),
          content_hash: tool.schema.string(),
          confirmed: tool.schema.boolean(),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_approve_candidate")
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "spec-candidate", {
            action: "approve",
            ...args,
          }, { signal: context.abort }))
        },
      }),
      sdlc_save_checkpoint: tool({
        description: "保存 spec 恢复点。payload 仅可使用 state/question/source_refs/confirmed_facts/assumptions/risks；单个决策必须是 {\"state\":\"interviewing\",\"question\":{\"id\":\"Q-0001\",\"prompt\":\"...\",\"answer\":\"...\",\"status\":\"resolved\",\"rationale\":\"...\"}}，禁止 stage/decisions/notes。source_refs 可用 [\"SRC-XXXXXXXXXXXX#anchor\"] 或 {source_id,anchor} 对象。",
        args: {
          payload: tool.schema.string().describe("Checkpoint JSON object encoded as a string."),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_save_checkpoint")
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "publish", {
            kind: "checkpoint",
            payload: JSON.parse(args.payload),
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
            "sdlc-tester": ["verify_delivery"],
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
        if (target) {
          await invoke(fallbackRoot, "write-check", {
            path: target,
            owner_pid: process.pid,
          })
        }
        if (input.sessionID && !coderWriteSessions.has(input.sessionID)) {
          coderWriteSessions.add(input.sessionID)
          await logPluginEvent(client, "coder.first_write", {
            session_id: input.sessionID,
            tool: input.tool,
          })
        }
        return
      }
      if (input.tool !== "task") return
      const role = AGENTS[output.args?.subagent_type]
      if (!role) {
        throw new Error("sdlc-main 只能派发 sdlc-coder")
      }
      const result = await invoke(fallbackRoot, "task-before", {
        role,
        owner_pid: process.pid,
        deadline_seconds: CODER_DEADLINE_SECONDS,
      })
      await logPluginEvent(client, "coder.dispatched", {
        session_id: input.sessionID,
        deadline_seconds: CODER_DEADLINE_SECONDS,
        context_characters: result.context_pack.characters,
        context_resources: result.context_pack.resource_count,
      })
      const deadline = setTimeout(async () => {
        try {
          await logPluginEvent(client, "coder.deadline_exceeded", {
            session_id: input.sessionID,
            deadline_seconds: CODER_DEADLINE_SECONDS,
          }, "warn")
          await invoke(fallbackRoot, "task-cancel", {
            reason: `coder deadline exceeded after ${CODER_DEADLINE_SECONDS}s`,
          })
        } catch (error) {
          await logPluginEvent(client, "coder.cancel_failed", {
            session_id: input.sessionID,
            error: String(error),
          }, "error")
        } finally {
          await client.session.abort({
            path: { id: input.sessionID },
            query: { directory: fallbackRoot },
          })
        }
      }, CODER_DEADLINE_SECONDS * 1000)
      deadline.unref()
      coderDeadlines.set(input.callID, deadline)
      const manifest = result.context_pack.paths[0]
      const taskObjective = String(output.args?.description || "").trim()
      delete output.args.command
      output.args.prompt = `[SDLC context pack] ${manifest}\n`
        + `${result.instruction}\n`
        + (taskObjective ? `本次任务目标：${taskObjective}。\n` : "")
        + `Coder deadline: ${CODER_DEADLINE_SECONDS}s。`
        + "不要展开读取 Core 源码，不要在 code 阶段运行 functional；"
        + "完成实现后立即返回约定 JSON handoff。"
    },

    "tool.execute.after": async (input, output) => {
      if (input.tool !== "task") return
      const role = AGENTS[input.args?.subagent_type]
      if (!role) return
      const deadline = coderDeadlines.get(input.callID)
      if (deadline) clearTimeout(deadline)
      coderDeadlines.delete(input.callID)
      await invoke(fallbackRoot, "task-after", {
        role,
        output: output.output || "",
      })
      await invoke(fallbackRoot, "lifecycle", {
        action: "compile_restart_verify",
      })
      await logPluginEvent(client, "coder.completed", {
        session_id: input.sessionID,
      })
    },
  }
}

export default SdlcPipelinePlugin
