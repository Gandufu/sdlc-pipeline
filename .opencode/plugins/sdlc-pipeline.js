import { spawnSync } from "node:child_process"
import { existsSync } from "node:fs"
import { fileURLToPath } from "node:url"
import path from "node:path"

const AGENTS = {
  "sdlc-coder": "coder",
}
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

function invoke(root, operation, payload = {}) {
  const result = spawnSync("python", [coreScript(root), operation, "--root", root], {
    cwd: root,
    input: JSON.stringify(payload),
    encoding: "utf8",
    env: {
      ...process.env,
      PYTHONUTF8: "1",
      PYTHONIOENCODING: "utf-8",
    },
    windowsHide: true,
    shell: false,
    timeout: 30 * 60 * 1000,
    maxBuffer: 10 * 1024 * 1024,
  })
  if (result.error) throw result.error
  const lines = (result.stdout || "").trim().split(/\r?\n/)
  let data
  try {
    data = JSON.parse(lines.at(-1) || "{}")
  } catch {
    throw new Error(`sdlc core returned invalid JSON: ${result.stdout}`)
  }
  if ((result.status ?? 1) !== 0 || data.ok === false) {
    throw new Error(data.error || result.stderr || `sdlc ${operation} failed`)
  }
  return data
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

export const SdlcPipelinePlugin = async ({ directory, worktree }) => {
  const { tool } = await import("@opencode-ai/plugin")
  const fallbackRoot = resolveProjectRoot({ directory, worktree })
  return {
    tool: {
      sdlc_status: tool({
        description: "读取当前阶段、恢复点、门禁、诊断和下一步。",
        args: {},
        async execute(_args, context) {
          return JSON.stringify(invoke(rootOf(context, fallbackRoot), "status"))
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
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_ingest_source")
          return JSON.stringify(invoke(rootOf(context, fallbackRoot), "publish", {
            kind: "source",
            payload: {
              kind: args.source_type,
              content: args.content,
              source: args.source,
              uri: args.uri,
              media_type: args.media_type,
            },
          }))
        },
      }),
      sdlc_save_checkpoint: tool({
        description: "保存 spec 恢复点；结构见 spec-checkpoint.schema.json。",
        args: {
          payload: tool.schema.string().describe("Checkpoint JSON object encoded as a string."),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_save_checkpoint")
          return JSON.stringify(invoke(rootOf(context, fallbackRoot), "publish", {
            kind: "checkpoint",
            payload: JSON.parse(args.payload),
          }))
        },
      }),
      sdlc_publish_contract: tool({
        description: "发布已确认的 Feature Contract；结构见 feature-contract.schema.json。",
        args: {
          payload: tool.schema.string().describe("Feature Contract JSON object encoded as a string."),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_publish_contract")
          return JSON.stringify(invoke(rootOf(context, fallbackRoot), "publish", {
            kind: "contract",
            payload: JSON.parse(args.payload),
          }))
        },
      }),
      sdlc_lifecycle: tool({
        description: "执行一个交付意图；内部生命周期由 Core 管理。",
        args: {
          action: tool.schema.enum([
            "init", "focused_check", "verify_delivery",
          ]),
          options: tool.schema.string().optional().describe(
            "Optional JSON. init: {template}; focused_check: {test_keys}.",
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
          return JSON.stringify(invoke(rootOf(context, fallbackRoot), "lifecycle", {
            action: args.action,
            ...options,
          }))
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
          return JSON.stringify(invoke(rootOf(context, fallbackRoot), "finalize", {
            ...args,
          }))
        },
      }),
    },

    "tool.execute.before": async (input, output) => {
      if (["edit", "write", "apply_patch"].includes(input.tool)) {
        const target = output.args?.filePath || output.args?.path
        if (target) invoke(fallbackRoot, "path-check", { path: target })
        return
      }
      if (input.tool !== "task") return
      const role = AGENTS[output.args?.subagent_type]
      if (!role) {
        throw new Error("sdlc-main 只能派发 sdlc-coder")
      }
      const result = invoke(fallbackRoot, "task-before", { role })
      const paths = result.context_pack.paths.join(", ")
      output.args.prompt = `${output.args.prompt || ""}\n\n`
        + `[SDLC context pack] ${paths}\n${result.instruction}`
    },

    "tool.execute.after": async (input, output) => {
      if (input.tool !== "task") return
      const role = AGENTS[input.args?.subagent_type]
      if (!role) return
      invoke(fallbackRoot, "task-after", {
        role,
        output: output.output || "",
      })
    },
  }
}

export default SdlcPipelinePlugin
