from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .adapter import after_task, before_task, validate_write_path
from .artifacts import publish_spec
from .bootstrap import bootstrap
from .common import SdlcError, project_root
from .lifecycle import (
    compile_restart_verify,
    execute_tests,
    init_project,
    install_system_tool,
    probe_tools,
    run_phase,
    run_test_plan,
    start,
    stop_active,
    verify_health,
)
from .runs import record_tokens
from .status import status
from .versions import finalize


def _input() -> dict[str, Any]:
    text = sys.stdin.read()
    if not text.strip():
        return {}
    value = json.loads(text)
    if not isinstance(value, dict):
        raise SdlcError("stdin JSON 必须是对象")
    return value


def execute(root: Path, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    if operation == "status":
        return status(root)
    if operation == "publish":
        kind = payload.get("kind")
        if kind == "spec":
            return publish_spec(root, payload["payload"])
        if kind == "tokens":
            return record_tokens(root, **payload["payload"])
        raise SdlcError(f"不支持的 publish kind: {kind}")
    if operation == "lifecycle":
        action = payload.get("action")
        lifecycle_root = (
            Path(payload["target_root"]).expanduser().resolve()
            if payload.get("target_root")
            else root
        )
        if action == "probe":
            return probe_tools(lifecycle_root)
        if action == "init":
            if payload.get("repo"):
                return bootstrap(
                    root,
                    repo=payload["repo"],
                    ref=payload.get("ref") or "HEAD",
                    target=payload["target"],
                    template=payload["template"],
                )
            return init_project(lifecycle_root)
        if action == "compile_restart_verify":
            return compile_restart_verify(lifecycle_root)
        if action == "start":
            return start(lifecycle_root)
        if action == "stop":
            return stop_active(lifecycle_root)
        if action == "health":
            return verify_health(lifecycle_root)
        if action == "test":
            return execute_tests(lifecycle_root, payload.get("executor_result"))
        if action == "run_tests":
            return run_test_plan(lifecycle_root)
        if action == "system_install":
            return install_system_tool(
                lifecycle_root, payload["tool"], bool(payload.get("approved"))
            )
        if action in {"install", "compile", "restart"}:
            return run_phase(lifecycle_root, action)
        raise SdlcError(f"不支持的 lifecycle action: {action}")
    if operation == "task-before":
        return before_task(root, payload["role"])
    if operation == "task-after":
        return after_task(root, payload["role"], payload["output"])
    if operation == "path-check":
        return validate_write_path(root, payload["path"])
    if operation == "finalize":
        return finalize(
            root,
            payload["version"],
            payload["summary"],
            bool(payload.get("confirmed")),
        )
    raise SdlcError(f"未知 operation: {operation}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="SDLC Pipeline deterministic core")
    parser.add_argument(
        "operation",
        choices=(
            "status", "publish", "lifecycle", "task-before", "task-after",
            "path-check", "finalize",
        ),
    )
    parser.add_argument("--root", help="项目根目录")
    args = parser.parse_args()
    root = project_root(args.root)
    try:
        result = execute(root, args.operation, _input())
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (SdlcError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
