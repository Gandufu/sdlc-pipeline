import { spawnSync } from "node:child_process"
import { existsSync } from "node:fs"
import path from "node:path"
import { tool } from "@opencode-ai/plugin"

const AGENTS = {
  "sdlc-coder": "coder",
  "sdlc-executor": "executor",
}

function coreScript(root) {
  const installed = path.join(root, ".sdlc-pipeline", "scripts", "sdlc.py")
  if (existsSync(installed)) return installed
  const development = path.join(root, "scripts", "sdlc.py")
  if (existsSync(development)) return development
  throw new Error("sdlc-pipeline Python core is missing")
}

function invoke(root, operation, payload = {}) {
  const result = spawnSync("python", [coreScript(root), operation, "--root", root], {
    cwd: root,
    input: JSON.stringify(payload),
    encoding: "utf8",
    windowsHide: true,
    shell: false,
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

function rootOf(context, fallback) {
  return context?.worktree || context?.directory || fallback
}

function requireAgent(context, allowed, toolName) {
  const agent = context?.agent
  if (!allowed.includes(agent)) {
    throw new Error(`${toolName} is not available to agent ${agent || "unknown"}`)
  }
}

export const SdlcPipelinePlugin = async ({ directory, worktree }) => {
  const fallbackRoot = worktree || directory
  return {
    tool: {
      sdlc_status: tool({
        description: "只读返回当前 SDLC 版本、阶段、门禁、PID、缺失产物和下一步资格。",
        args: {},
        async execute(_args, context) {
          return JSON.stringify(invoke(rootOf(context, fallbackRoot), "status"))
        },
      }),
      sdlc_publish: tool({
        description: "校验并原子发布固定格式 SDLC 产物；AI 不能直接编辑正式文档。",
        args: {
          kind: tool.schema.enum(["spec", "tokens"]),
          payload: tool.schema.string().describe("JSON object encoded as a string"),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_publish")
          return JSON.stringify(invoke(rootOf(context, fallbackRoot), "publish", {
            kind: args.kind,
            payload: JSON.parse(args.payload),
          }))
        },
      }),
      sdlc_lifecycle: tool({
        description: "执行确定性的探测、init、编译、启停、健康检查、产物验证和测试。",
        args: {
          action: tool.schema.enum([
            "probe", "init", "install", "compile", "start", "stop", "restart",
            "health", "system_install", "compile_restart_verify", "run_tests", "test",
          ]),
          options: tool.schema.string().optional().describe(
            "Optional JSON: init accepts repo/ref/target/template; later bootstrap actions accept target_root; test accepts executor_result",
          ),
        },
        async execute(args, context) {
          const options = args.options ? JSON.parse(args.options) : {}
          const allowed = {
            "sdlc-main": [
              "probe", "init", "install", "compile", "start", "stop", "restart",
              "health", "system_install", "compile_restart_verify", "test",
            ],
            "sdlc-coder": ["compile", "health"],
            "sdlc-executor": ["run_tests", "health"],
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
          return JSON.stringify(invoke(rootOf(context, fallbackRoot), "finalize", args))
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
