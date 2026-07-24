#!/usr/bin/env python3
"""Codex 异步子代理结果适配器。

Codex spawn_agent 立即返回 agent id，最终文本在 wait/follow-up 后到达，因而
PostToolUse:Agent 不一定能看到交接块。本脚本由 dispatcher 在拿到最终文本后调用，
先执行 SubagentStop 语义校验，再执行 PostToolUse merge。

交接块正文从 stdin 读取；输出单个 JSON，退出码 0 表示校验并 merge 成功。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

for _stream in (sys.stdout, sys.stdin):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def invoke(script: str, mode: str, payload: dict) -> tuple[int, dict, str]:
    result = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(__file__), script), mode],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
    )
    stdout = result.stdout.decode("utf-8", errors="replace").strip()
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(stdout.splitlines()[-1]) if stdout else {}
    except json.JSONDecodeError:
        data = {}
    return result.returncode, data, stderr


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 Codex 异步子代理最终交接块")
    parser.add_argument("role", choices=("code", "test"))
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--agent-id", default="")
    parser.add_argument("--session-id", default="codex-dispatch")
    args = parser.parse_args()

    handoff = sys.stdin.read()
    script = "validate_code_handoff.py" if args.role == "code" else "validate_test_handoff.py"
    agent_type = "sdlc_coder" if args.role == "code" else "sdlc_tester"
    common = {
        "cwd": os.path.realpath(args.project_root),
        "session_id": args.session_id,
        "agent_id": args.agent_id,
        "agent_type": agent_type,
        "tool_name": "Agent",
        "tool_input": {"task_name": agent_type, "subagent_type": agent_type},
    }
    stop_payload = {
        **common,
        "hook_event_name": "SubagentStop",
        "last_assistant_message": handoff,
    }
    stop_rc, stop, stop_err = invoke(script, "subagentstop", stop_payload)
    if stop_rc != 0 or stop.get("decision") != "approve":
        print(
            json.dumps(
                {
                    "ok": False,
                    "stage": "validate",
                    "decision": stop,
                    "stderr": stop_err,
                },
                ensure_ascii=False,
            )
        )
        return 1

    post_payload = {
        **common,
        "hook_event_name": "PostToolUse",
        "tool_response": {"result": handoff},
    }
    post_rc, post, post_err = invoke(script, "posttooluse", post_payload)
    context = (
        post.get("hookSpecificOutput", {}).get("additionalContext")
        or post.get("systemMessage")
        or ""
    )
    invalid = "不合规" in context or "人工介入" in context
    ok = post_rc == 0 and not invalid
    print(
        json.dumps(
            {
                "ok": ok,
                "stage": "merge",
                "validation": stop,
                "merge": post,
                "stderr": post_err,
            },
            ensure_ascii=False,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
