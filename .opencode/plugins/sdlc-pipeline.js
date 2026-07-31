import { spawn } from "node:child_process"
import { existsSync } from "node:fs"
import { fileURLToPath } from "node:url"
import path from "node:path"

const AGENTS = { "sdlc-coder": "coder", "sdlc-tester": "tester" }
const TOKEN_PHASES = {
  "sdlc-main": "main",
  "sdlc-coder": "coder",
  "sdlc-tester": "tester",
}
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
  const completedTokenMessages = new Set()
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
    title: tool.schema.string(),
    modules: tool.schema.array(moduleSpec),
    interfaces: tool.schema.array(interfaceSpec),
    data_contracts: tool.schema.array(dataContract),
    extension_points: tool.schema.array(tool.schema.string()),
    decisions: tool.schema.array(tool.schema.string()),
  })
  const verification = tool.schema.object({
    level: tool.schema.enum(["unit", "functional"]),
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
    event: async ({ event }) => {
      if (event.type !== "message.updated") return
      const info = event.properties?.info
      const phase = TOKEN_PHASES[info?.agent]
      if (
        info?.role !== "assistant"
        || !phase
        || !info.id
        || !info.time?.completed
        || completedTokenMessages.has(info.id)
      ) return
      completedTokenMessages.add(info.id)
      const tokens = info.tokens || {}
      const cache = tokens.cache || {}
      const cost = typeof info.cost === "number"
        ? info.cost
        : (typeof info.cost?.total === "number" ? info.cost.total : 0)
      try {
        await invoke(fallbackRoot, "publish", {
          kind: "tokens",
          payload: {
            phase,
            input_tokens: tokens.input || 0,
            output_tokens: tokens.output || 0,
            reasoning_tokens: tokens.reasoning || 0,
            cache_read_tokens: cache.read || 0,
            cache_write_tokens: cache.write || 0,
            cost,
            source: "opencode-message",
          },
        })
      } catch (error) {
        await logPluginEvent(client, "tokens.record_failed", {
          session_id: info.sessionID,
          message_id: info.id,
          error: error instanceof Error ? error.message : String(error),
        })
      }
    },
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
        description: [
          "一次性校验完整 Spec，或在用户确认后直接发布正式 baseline；未发布正文不落盘。",
          "不要提交 R/D/T/AC 的 id、design_ids、acceptance_criteria_ids、test_key 或 selector；它们全部由 Core 分配。",
          "不要提交 requirement_ids；Core 将 Design/Verification 关联到本次 Spec 的正式 Requirement。",
          "extension_points 只使用 sdlc_status.spec_contract 中列出的值；无法匹配时 Core 使用脚手架受控范围。",
          "校验失败后立即向用户报告原始错误并停止，本轮不得猜测格式、搜索插件文件或自动重试。",
        ].join(" "),
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
        description: [
          "初始化项目，或对已有 Coder handoff 做一次确定性 Code 门禁复验。",
          "init 前必须先调用 sdlc_status；contracts 不存在时必须等待用户跨消息选择模板并传入 options.template。",
          "严禁用无参数 init 探测状态。",
          "任何 lifecycle 失败后原样报告并停止；禁止自行清理端口、结束进程或同轮重试。",
        ].join(" "),
        args: {
          action: tool.schema.enum(["init", "reverify_code"]),
          options: tool.schema.object({
            template: tool.schema.string().optional(),
          }).optional(),
        },
        async execute(args, context) {
          requireAgent(context, ["sdlc-main"], "sdlc_lifecycle")
          const options = args.options || {}
          const root = rootOf(context, fallbackRoot)
          const result = await invoke(root, "lifecycle", {
            action: args.action === "reverify_code"
              ? "compile_restart_verify"
              : args.action,
            ...options,
          }, { signal: context.abort })
          if (args.action === "reverify_code") {
            await invoke(root, "task-state", {
              action: "transition", event: "code_completed",
            })
          }
          return JSON.stringify(result)
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
      if (input.tool !== "task") return
      const role = AGENTS[output.args?.subagent_type]
      if (!role) throw new Error("sdlc-main 只能派发 sdlc-coder 或 sdlc-tester")
      const result = await invoke(fallbackRoot, "task-before", {
        role,
        owner_pid: process.pid,
      })
      const objective = String(output.args?.description || "").trim()
      const delegatedPrompt = String(
        output.args?.prompt || output.args?.command || "",
      ).trim()
      delete output.args.command
      output.args.prompt = `[SDLC context pack] ${result.context_pack.paths[0]}\n`
        + `${result.instruction}\n`
        + (
          delegatedPrompt
            ? `主会话委派内容（原文）：\n${delegatedPrompt}\n`
            : (objective ? `本次任务目标：${objective}。\n` : "")
        )
        + (
          role === "coder"
            ? "验证按既有测试、compile、lint/typecheck、必要时一次 package 的顺序闭环；"
              + "不要反复 start 或深挖发布包。完成或形成 open_issues 后立即返回约定 JSON handoff。"
            : "完成后立即返回约定 JSON handoff。"
        )
    },
    "tool.execute.after": async (input, output) => {
      if (input.tool !== "task") return
      const role = AGENTS[input.args?.subagent_type]
      if (!role) return
      let receipt
      try {
        receipt = await invoke(fallbackRoot, "task-after", {
          role,
          output: output.output || "",
        })
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error)
        output.output = `${output.output || ""}\n`
          + `[SDLC ${role} handoff rejected] ${detail}\n`
          + "未执行后续 gate，也未推进 Task；本次命令必须停止，由 main 或用户修正后重新执行。"
        await logPluginEvent(client, `${role}.handoff_rejected`, {
          session_id: input.sessionID,
          error: detail,
        })
        return
      }
      const openIssues = receipt?.handoff?.open_issues
      if (Array.isArray(openIssues) && openIssues.length) {
        output.output = `${output.output || ""}\n`
          + `[SDLC ${role} handoff] 存在 open_issues，`
          + "未执行后续 gate，也未推进 Task；由 sdlc-main 决定回退或重新派发。"
        await logPluginEvent(client, `${role}.open_issues`, {
          session_id: input.sessionID,
          count: openIssues.length,
        })
        return
      }
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
