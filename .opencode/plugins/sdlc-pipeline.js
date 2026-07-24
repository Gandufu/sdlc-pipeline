// Project-local OpenCode adapter for the shared Python runtime.
// It intentionally has no npm dependencies and can be copied into any repo.
import { spawnSync } from "node:child_process"
import { existsSync } from "node:fs"
import path from "node:path"

const ROLE_BY_AGENT = {
  "sdlc-coder": "coder",
  "sdlc-tester": "tester",
}

function python(root, script, args = [], payload = {}) {
  const file = path.join(root, ".sdlc-pipeline", "scripts", script)
  if (!existsSync(file)) return { status: 0, data: {} }
  const result = spawnSync("python", [file, ...args], {
    cwd: root,
    env: { ...process.env, CLAUDE_PROJECT_DIR: root },
    input: JSON.stringify(payload),
    encoding: "utf8",
    windowsHide: true,
  })
  if (result.error) throw result.error
  let data = {}
  const stdout = (result.stdout || "").trim()
  if (stdout) {
    try {
      data = JSON.parse(stdout.split(/\r?\n/).at(-1))
    } catch {
      throw new Error(`sdlc-pipeline hook returned invalid JSON: ${stdout}`)
    }
  }
  return { status: result.status ?? 1, data, stderr: result.stderr || "" }
}

function hookPayload(root, input, args, event) {
  return {
    session_id: input.sessionID,
    cwd: root,
    hook_event_name: event,
    tool_name: "Agent",
    tool_input: {
      subagent_type: args.subagent_type,
      task_name: args.subagent_type,
      prompt: args.prompt,
      description: args.description,
    },
  }
}

function rejection(data) {
  return (
    data?.decision === "block" ||
    data?.hookSpecificOutput?.permissionDecision === "deny" ||
    data?.continue === false
  )
}

function contextOf(data) {
  return (
    data?.hookSpecificOutput?.additionalContext ||
    data?.additionalContext ||
    data?.systemMessage ||
    data?.reason ||
    ""
  )
}

export const SdlcPipelinePlugin = async ({ directory, worktree }) => {
  const root = worktree || directory
  return {
    config: async (config) => {
      config.skills = config.skills || {}
      config.skills.paths = Array.from(
        new Set([...(config.skills.paths || []), path.join(root, ".opencode", "skills")]),
      )
    },

    "experimental.chat.messages.transform": async (_input, output) => {
      const state = python(
        root,
        "derive_state.py",
        [],
        { cwd: root, hook_event_name: "SessionStart", session_id: "opencode" },
      )
      const context = contextOf(state.data)
      if (!context || !output.messages?.length) return
      const first = output.messages[0]
      first.parts = first.parts || []
      if (first.parts.some((part) => part.text?.includes("[sdlc-pipeline state]"))) return
      first.parts.unshift({ type: "text", text: `[sdlc-pipeline state]\n${context}` })
    },

    "tool.execute.before": async (input, output) => {
      if (input.tool !== "task") return
      const role = ROLE_BY_AGENT[output.args?.subagent_type]
      if (!role) return
      const payload = hookPayload(root, input, output.args, "PreToolUse")
      const gate = python(root, role === "coder" ? "gate_code.py" : "gate_test.py", [], payload)
      if (gate.status !== 0 || rejection(gate.data)) {
        throw new Error(contextOf(gate.data) || gate.stderr || `${role} gate rejected`)
      }
    },

    "tool.execute.after": async (input, output) => {
      if (input.tool !== "task") return
      const role = ROLE_BY_AGENT[input.args?.subagent_type]
      if (!role) return
      const payload = hookPayload(root, input, input.args, "PostToolUse")
      payload.tool_response = { result: output.output || "" }
      const check = python(
        root,
        role === "coder" ? "validate_code_handoff.py" : "validate_test_handoff.py",
        ["posttooluse"],
        payload,
      )
      const context = contextOf(check.data)
      if (context) output.output = `${output.output || ""}\n\n[SDLC validation]\n${context}`
      if (check.status !== 0 || rejection(check.data)) {
        throw new Error(context || check.stderr || `${role} handoff rejected`)
      }
    },
  }
}

export default SdlcPipelinePlugin
