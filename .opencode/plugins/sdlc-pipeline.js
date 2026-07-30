import { spawn } from "node:child_process"
import { existsSync } from "node:fs"
import { fileURLToPath } from "node:url"
import path from "node:path"

const AGENTS = { "sdlc-coder": "coder", "sdlc-tester": "tester" }
const taskWriteSessions = new Set()
const PLUGIN_PROJECT_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)), "..", ".."
)

function localCoreScript(root) {
  const installed = path.join(root, ".sdlc-pipeline", "runtime", "scripts", "sdlc.py")
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

export function approvalPayload(args) {
  const contentHash = typeof args?.content_hash === "string"
    ? args.content_hash.trim()
    : ""
  const missing = [
    ...(contentHash ? [] : ["content_hash"]),
    ...(args?.confirmed === true ? [] : ["confirmed=true"]),
  ]
  return missing.length
    ? {
        ok: false,
        code: "invalid_approval_arguments",
        error: `批准 Spec 的参数不完整：缺少 ${missing.join(", ")}。`,
      }
    : { ok: true, content_hash: contentHash, confirmed: true }
}

function invoke(root, operation, payload = {}, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      pythonExecutable(),
      [coreScript(root), operation, "--root", root],
      {
        cwd: root,
        env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" },
        windowsHide: true,
        shell: false,
        stdio: ["pipe", "pipe", "pipe"],
      },
    )
    let stdout = ""
    let stderr = ""
    const timer = setTimeout(() => {
      child.kill("SIGKILL")
      reject(new Error(`sdlc ${operation} deadline exceeded`))
    }, options.timeoutMs || 30 * 60 * 1000)
    const abort = () => child.kill("SIGKILL")
    options.signal?.addEventListener("abort", abort, { once: true })
    child.stdout.on("data", (chunk) => { stdout += chunk.toString("utf8") })
    child.stderr.on("data", (chunk) => { stderr += chunk.toString("utf8") })
    child.on("error", reject)
    child.on("close", (status) => {
      clearTimeout(timer)
      options.signal?.removeEventListener("abort", abort)
      let data
      try {
        data = JSON.parse(stdout.trim().split(/\r?\n/).at(-1) || "{}")
      } catch {
        reject(new Error(`sdlc core returned invalid JSON: ${stdout}`))
        return
      }
      if ((status ?? 1) !== 0 || data.ok === false) {
        reject(new Error(data.error || stderr || `sdlc ${operation} failed`))
        return
      }
      resolve(data)
    })
    child.stdin.end(JSON.stringify(payload))
  })
}

export function resolveProjectRoot(context = {}, fallback = PLUGIN_PROJECT_ROOT) {
  for (const candidate of [context.directory, context.worktree, fallback, PLUGIN_PROJECT_ROOT]) {
    if (typeof candidate !== "string" || !candidate.trim()) continue
    const resolved = path.resolve(candidate)
    if (localCoreScript(resolved)) return resolved
  }
  return PLUGIN_PROJECT_ROOT
}

function rootOf(context, fallback) {
  return resolveProjectRoot(context, fallback)
}

function requireAgent(context, allowed, toolName) {
  if (!allowed.includes(context?.agent)) {
    throw new Error(`${toolName} is not available to agent ${context?.agent || "unknown"}`)
  }
}

async function logPluginEvent(client, message, extra = {}) {
  try {
    await client?.app?.log?.({
      body: { service: "sdlc-pipeline", level: "info", message, extra },
    })
  } catch {
    // Observability must not break delivery.
  }
}

export const SdlcPipelinePlugin = async ({ client, directory, worktree }) => {
  const { tool } = await import("@opencode-ai/plugin")
  const fallbackRoot = resolveProjectRoot({ directory, worktree })
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
  const dataContract = tool.schema.object({
    name: tool.schema.string(),
    fields: tool.schema.array(tool.schema.object({
      name: tool.schema.string(),
      type: tool.schema.string(),
      required: tool.schema.boolean(),
    })),
  })
  const requirement = tool.schema.object({
    id: tool.schema.string().optional(),
    feature_id: tool.schema.string(),
    title: tool.schema.string(),
    goal: tool.schema.string(),
    actor: tool.schema.string(),
    scope: tool.schema.array(tool.schema.string()),
    non_goals: tool.schema.array(tool.schema.string()),
    main_flow: tool.schema.array(tool.schema.string()),
    alternate_flows: tool.schema.array(tool.schema.object({
      name: tool.schema.string(),
      steps: tool.schema.array(tool.schema.string()),
    })),
    acceptance_criteria: tool.schema.array(tool.schema.object({
      given: tool.schema.string(),
      when: tool.schema.string(),
      then: tool.schema.string(),
    })),
  })
  const design = tool.schema.object({
    id: tool.schema.string().optional(),
    title: tool.schema.string(),
    requirement_ids: tool.schema.array(tool.schema.string()),
    modules: tool.schema.array(moduleSpec),
    interfaces: tool.schema.array(interfaceSpec),
    data_contracts: tool.schema.array(dataContract),
    extension_points: tool.schema.array(tool.schema.string()),
    decisions: tool.schema.array(tool.schema.string()),
  })
  const verification = tool.schema.object({
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
  })
  const spec = tool.schema.object({
    title: tool.schema.string(),
    requirements: tool.schema.array(requirement),
    designs: tool.schema.array(design),
    verification: tool.schema.array(verification),
  })
  return {
    tool: {
      sdlc_status: tool({
        description: "读取当前 Task、门禁、预览进程和下一步。",
        args: {},
        async execute(_args, context) {
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "status", {}, {
            signal: context.abort,
          }))
        },
      }),
      sdlc_task: tool({
        description: "记录用户原始输入或执行明确的 Task 状态流转。",
        args: {
          action: tool.schema.enum(["record_input", "transition"]),
          text: tool.schema.string().optional(),
          event: tool.schema.enum([
            "implementation_issue", "requirements_issue", "review_passed",
            "test_issue",
          ]).optional(),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_task")
          const payload = args.action === "record_input"
            ? { action: "record-input", text: args.text }
            : { action: "transition", event: args.event }
          return JSON.stringify(await invoke(
            rootOf(context, fallbackRoot), "task-state", payload,
            { signal: context.abort },
          ))
        },
      }),
      sdlc_spec: tool({
        description: "一次性校验完整 Spec，或在用户确认后直接发布正式 baseline；未发布正文不落盘。",
        args: {
          action: tool.schema.enum(["prepare", "approve"]),
          spec,
          content_hash: tool.schema.string().optional(),
          confirmed: tool.schema.boolean().optional(),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_spec")
          if (args.action === "approve") {
            const approval = approvalPayload(args)
            if (!approval.ok) return JSON.stringify(approval)
          }
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "spec", {
            action: args.action,
            spec: args.spec,
            content_hash: args.content_hash,
            confirmed: args.confirmed,
          }, { signal: context.abort }))
        },
      }),
      sdlc_lifecycle: tool({
        description: "初始化项目；Code/Test 执行由 subagent hook 驱动。",
        args: {
          action: tool.schema.enum(["init"]),
          options: tool.schema.string().optional(),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_lifecycle")
          const options = args.options ? JSON.parse(args.options) : {}
          return JSON.stringify(await invoke(rootOf(context, fallbackRoot), "lifecycle", {
            action: args.action,
            ...options,
          }, { signal: context.abort }))
        },
      }),
      sdlc_finalize: tool({
        description: "测试通过且用户明确确认后固化版本。",
        args: {
          version: tool.schema.string(),
          summary: tool.schema.string(),
          confirmed: tool.schema.boolean(),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_finalize")
          const result = await invoke(rootOf(context, fallbackRoot), "finalize", args, {
            signal: context.abort,
          })
          await invoke(rootOf(context, fallbackRoot), "task-state", {
            action: "transition", event: "finalized",
          })
          return JSON.stringify(result)
        },
      }),
    },
    "tool.execute.before": async (input, output) => {
      if (["edit", "write", "apply_patch"].includes(input.tool)) {
        const target = output.args?.filePath || output.args?.path
        if (target) {
          const checked = await invoke(fallbackRoot, "write-check", {
            path: target,
            owner_pid: process.pid,
          })
          if (checked?.heartbeat?.active && input.sessionID && !taskWriteSessions.has(input.sessionID)) {
            taskWriteSessions.add(input.sessionID)
            await logPluginEvent(client, `${checked.role}.first_write`, {
              session_id: input.sessionID,
            })
          }
        }
        return
      }
      if (input.tool !== "task") return
      const role = AGENTS[output.args?.subagent_type]
      if (!role) throw new Error("sdlc-main 只能派发 sdlc-coder 或 sdlc-tester")
      const result = await invoke(fallbackRoot, "task-before", {
        role,
        owner_pid: process.pid,
      })
      const objective = String(output.args?.description || "").trim()
      delete output.args.command
      output.args.prompt = `[SDLC context pack] ${result.context_pack.paths[0]}\n`
        + `${result.instruction}\n`
        + (objective ? `本次任务目标：${objective}。\n` : "")
        + "完成后立即返回约定 JSON handoff。"
    },
    "tool.execute.after": async (input, output) => {
      if (input.tool !== "task") return
      const role = AGENTS[input.args?.subagent_type]
      if (!role) return
      await invoke(fallbackRoot, "task-after", {
        role,
        output: output.output || "",
      })
      const result = await invoke(fallbackRoot, "lifecycle", {
        action: role === "coder" ? "compile_restart_verify" : "verify_delivery",
      })
      await invoke(fallbackRoot, "task-state", {
        action: "transition",
        event: role === "coder" ? "code_completed" : "test_completed",
      })
      if (role === "coder") {
        const accessUrl = result?.preview?.access_url
        output.output = `${output.output || ""}\n[SDLC code gate] 通过；`
          + (accessUrl ? `预览：${accessUrl}` : "预览进程已启动。")
      }
      await logPluginEvent(client, `${role}.completed`, { session_id: input.sessionID })
    },
  }
}

export default SdlcPipelinePlugin
