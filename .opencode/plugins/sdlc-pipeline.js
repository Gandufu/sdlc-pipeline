import { spawnSync } from "node:child_process"
import { existsSync } from "node:fs"
import { fileURLToPath } from "node:url"
import path from "node:path"

const AGENTS = {
  "sdlc-coder": "coder",
  "sdlc-executor": "executor",
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
        description: "只读返回 init 幂等状态、登记模板及 active rules 元数据、当前版本、阶段、门禁、PID 和下一步资格。",
        args: {},
        async execute(_args, context) {
          return JSON.stringify(invoke(rootOf(context, fallbackRoot), "status"))
        },
      }),
      sdlc_publish: tool({
        description: "校验并原子发布固定格式 SDLC 产物；AI 不能直接编辑正式文档。",
        args: {
          kind: tool.schema.enum(["source", "spec", "checkpoint", "tokens"]),
          payload: tool.schema.string().describe(
            "JSON object encoded as a string. source requires {content, source?, kind?, uri?, media_type?}. checkpoint must follow spec-checkpoint.schema.json. For spec, read spec.schema.json and submit the full object with R-0001/D-0001/T-0001 IDs."
          ),
          idempotency_key: tool.schema.string().optional(),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_publish")
          return JSON.stringify(invoke(rootOf(context, fallbackRoot), "publish", {
            kind: args.kind,
            payload: JSON.parse(args.payload),
            idempotency_key: args.idempotency_key || context?.callID,
          }))
        },
      }),
      sdlc_lifecycle: tool({
        description: "执行确定性的生命周期动作。角色范围：coder：仅 `compile`、`health`；executor：仅 `execute_test_plan`、`health`；主会话在 executor handoff 后仅用 `record_test_results` 记录结果。",
        args: {
          action: tool.schema.enum([
            "probe", "init", "install", "compile", "start", "stop", "restart",
            "health", "system_install", "compile_restart_verify",
            "execute_test_plan", "record_test_results",
          ]),
          options: tool.schema.string().optional().describe(
            "Optional JSON: init accepts only the template ID selected by the user from sdlc_status.templates; record_test_results accepts executor_result",
          ),
          idempotency_key: tool.schema.string().optional(),
        },
        async execute(args, context) {
          const options = args.options ? JSON.parse(args.options) : {}
          const allowed = {
            "sdlc-main": [
              "probe", "init", "install", "compile", "start", "stop", "restart",
              "health", "system_install", "compile_restart_verify",
              "record_test_results",
            ],
            "sdlc-coder": ["compile", "health"],
            "sdlc-executor": ["execute_test_plan", "health"],
          }
          if (!allowed[context?.agent]?.includes(args.action)) {
            throw new Error(`agent ${context?.agent || "unknown"} cannot run lifecycle ${args.action}`)
          }
          return JSON.stringify(invoke(rootOf(context, fallbackRoot), "lifecycle", {
            action: args.action,
            ...options,
            idempotency_key: args.idempotency_key || context?.callID,
          }))
        },
      }),
      sdlc_finalize: tool({
        description: "高风险内部工具：仅在 mandatory 测试通过且用户明确确认后创建 manifest、commit 和 annotated tag。",
        args: {
          version: tool.schema.string(),
          summary: tool.schema.string(),
          confirmed: tool.schema.boolean(),
          idempotency_key: tool.schema.string().optional(),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_finalize")
          return JSON.stringify(invoke(rootOf(context, fallbackRoot), "finalize", {
            ...args,
            idempotency_key: args.idempotency_key || context?.callID,
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
        throw new Error("sdlc-main 只能派发 sdlc-coder 或 sdlc-executor")
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
      if (role === "coder") {
        invoke(fallbackRoot, "lifecycle", {
          action: "compile_restart_verify",
        })
      }
    },

    event: async ({ event }) => {
      const info = event?.properties?.info
      const tokens = info?.tokens
      if (!tokens) return
      try {
        invoke(fallbackRoot, "publish", {
          kind: "tokens",
          payload: {
            phase: info.agent || "main",
            input_tokens: tokens.input || 0,
            output_tokens: tokens.output || 0,
            cache_read_tokens: tokens.cache?.read || 0,
            cache_write_tokens: tokens.cache?.write || 0,
            source: "opencode-event",
          },
        })
      } catch {
        // Token telemetry must never block delivery gates.
      }
    },
  }
}

export default SdlcPipelinePlugin
