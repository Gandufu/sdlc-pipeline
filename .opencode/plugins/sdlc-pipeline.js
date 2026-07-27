import { spawn } from "node:child_process"
import { existsSync } from "node:fs"
import { fileURLToPath } from "node:url"
import path from "node:path"

const AGENTS = {
  "sdlc-coder": "coder",
}
const CODER_DEADLINE_SECONDS = 9 * 60
const coderDeadlines = new Map()
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
    const child = spawn("python", [coreScript(root), operation, "--root", root], {
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
      sdlc_save_checkpoint: tool({
        description: "保存 spec 恢复点；结构见 spec-checkpoint.schema.json。",
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
      sdlc_publish_contract: tool({
        description: "发布已确认的 Feature Contract；结构见 feature-contract.schema.json。",
        args: {
          payload: tool.schema.string().describe("Feature Contract JSON object encoded as a string."),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_publish_contract")
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "publish", {
            kind: "contract",
            payload: JSON.parse(args.payload),
          }, { signal: context.abort }))
        },
      }),
      sdlc_lifecycle: tool({
        description: "执行一个交付意图；内部生命周期由 Core 管理。",
        args: {
          action: tool.schema.enum([
            "init", "focused_check", "verify_delivery",
          ]),
          options: tool.schema.string().optional().describe(
            "Optional JSON. init: {template}; focused_check: {test_ids}.",
          ),
        },
        async execute(args, context) {
          const options = args.options ? JSON.parse(args.options) : {}
          const allowed = {
            "sdlc-main": [
              "init", "focused_check", "verify_delivery",
            ],
            "sdlc-coder": ["focused_check"],
          }
          if (!allowed[context?.agent]?.includes(args.action)) {
            throw new Error(`agent ${context?.agent || "unknown"} cannot run lifecycle ${args.action}`)
          }
          if (context?.agent === "sdlc-coder") {
            await invoke(rootOf(context, fallbackRoot), "task-heartbeat", {
              role: "coder",
              owner_pid: process.pid,
            })
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
        await invoke(fallbackRoot, "task-heartbeat", {
          role: "coder",
          owner_pid: process.pid,
        })
        const target = output.args?.filePath || output.args?.path
        if (target) await invoke(fallbackRoot, "path-check", { path: target })
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
      const deadline = setTimeout(async () => {
        try {
          await client.session.abort({
            path: { id: input.sessionID },
            query: { directory: fallbackRoot },
          })
        } finally {
          await invoke(fallbackRoot, "task-cancel", {
            reason: `coder deadline exceeded after ${CODER_DEADLINE_SECONDS}s`,
          }).catch(() => undefined)
        }
      }, CODER_DEADLINE_SECONDS * 1000)
      deadline.unref()
      coderDeadlines.set(input.callID, deadline)
      const paths = result.context_pack.paths.join(", ")
      output.args.prompt = `${output.args.prompt || ""}\n\n`
        + `[SDLC context pack] ${paths}\n${result.instruction}`
        + `\nCoder deadline: ${CODER_DEADLINE_SECONDS}s; 每完成一个可验证增量即运行 focused check，`
        + "无法在 deadline 内完成时返回已完成摘要与 open_issues，不要静默等待。"
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
    },
  }
}

export default SdlcPipelinePlugin
