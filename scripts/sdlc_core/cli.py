from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .adapter import after_task, before_task, validate_write_path
from .artifacts import publish_spec
from .bootstrap import bootstrap
from .common import SdlcError, project_root, read_json
from .lifecycle import (
    compile_restart_verify,
    execute_tests,
    activate_template_rules,
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
from .journal import (
    begin_attempt,
    close_run,
    finish_attempt,
    record_spec_checkpoint,
)
from .status import status
from .versions import finalize
from .sources import ingest_source


def _input() -> dict[str, Any]:
    text = sys.stdin.read()
    if not text.strip():
        return {}
    value = json.loads(text)
    if not isinstance(value, dict):
        raise SdlcError("stdin JSON 必须是对象")
    return value


def _execute(root: Path, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    if operation == "status":
        return status(root)
    if operation == "publish":
        kind = payload.get("kind")
        if kind == "spec":
            return publish_spec(root, payload["payload"])
        if kind == "tokens":
            return record_tokens(root, **payload["payload"])
        if kind == "checkpoint":
            return record_spec_checkpoint(root, payload["payload"])
        if kind == "source":
            return ingest_source(root, payload["payload"])
        raise SdlcError(f"不支持的 publish kind: {kind}")
    if operation == "lifecycle":
        action = payload.get("action")
        lifecycle_root = root
        if action == "probe":
            return probe_tools(lifecycle_root)
        if action == "init":
            if any(
                payload.get(name)
                for name in ("target", "target_root", "repo", "github", "ref")
            ):
                raise SdlcError(
                    "sdlc-init 不接受路径、GitHub 地址或 ref；"
                    "模板只能从 sdlc_status.templates 中选择"
                )
            contract_root = lifecycle_root / ".sdlc-pipeline"
            contracts_present = all(
                (contract_root / name).is_file()
                for name in ("lifecycle.json", "scaffold.json")
            )
            existing_report = read_json(
                lifecycle_root / "docs" / "sdlc" / "init-report.json",
                required=False,
            )
            if (
                contracts_present
                and existing_report
                and existing_report.get("status") == "pass"
            ):
                active_rules = activate_template_rules(lifecycle_root)
                return {
                    "ok": True,
                    "idempotent": True,
                    "already_initialized": True,
                    "project_root": str(lifecycle_root.resolve()),
                    "report": existing_report,
                    "active_rules": active_rules,
                }
            if payload.get("template"):
                return bootstrap(
                    root,
                    template=payload.get("template"),
                )
            missing_contracts = [
                name
                for name in ("lifecycle.json", "scaffold.json")
                if not (contract_root / name).is_file()
            ]
            if missing_contracts:
                raise SdlcError(
                    "当前目录仅安装了 SDLC adapter，不是已初始化项目；"
                    "请先从 sdlc_status.templates 让用户选择模板数据源 ID。"
                    f"缺少项目合约: {', '.join(missing_contracts)}"
                )
            return init_project(lifecycle_root, auto_install_missing=True)
        if action == "compile_restart_verify":
            return compile_restart_verify(lifecycle_root)
        if action == "start":
            return start(lifecycle_root)
        if action == "stop":
            return stop_active(lifecycle_root)
        if action == "health":
            return verify_health(lifecycle_root)
        if action in {"record_test_results", "test"}:
            return execute_tests(lifecycle_root, payload.get("executor_result"))
        if action in {"execute_test_plan", "run_tests"}:
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


def _phase_step(operation: str, payload: dict[str, Any]) -> tuple[str, str]:
    if operation == "publish":
        return "spec", str(payload.get("kind", "publish"))
    if operation == "lifecycle":
        action = str(payload.get("action", "unknown"))
        if action == "init" or action == "probe" or action == "system_install":
            return "init", action
        if action in {"execute_test_plan", "run_tests", "record_test_results", "test"}:
            return "test", action
        return "code", action
    if operation in {"task-before", "task-after"}:
        role = str(payload.get("role", "unknown"))
        return ("test" if role == "executor" else "code"), f"{operation}:{role}"
    if operation == "finalize":
        return "version", "finalize"
    if operation == "path-check":
        return "code", "write-guard"
    return "unknown", operation


def execute(root: Path, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    if operation == "status" or (
        operation == "publish" and payload.get("kind") in {"tokens", "checkpoint"}
    ):
        return _execute(root, operation, payload)
    effective_payload = dict(payload)
    idempotency_key = effective_payload.pop("idempotency_key", None)
    if idempotency_key is not None and (
        not isinstance(idempotency_key, str) or not idempotency_key.strip()
    ):
        raise SdlcError("idempotency_key 必须是非空字符串")
    phase, step = _phase_step(operation, effective_payload)
    attempt = begin_attempt(
        root,
        phase=phase,
        step=step,
        operation=operation,
        payload=effective_payload,
        idempotency_key=idempotency_key,
    )
    if attempt.get("cached"):
        return attempt["result"]
    try:
        result = _execute(root, operation, effective_payload)
    except Exception as exc:
        finish_attempt(root, attempt, state="failed", error=str(exc))
        raise
    finish_attempt(root, attempt, state="succeeded", result=result)
    if operation == "publish" and effective_payload.get("kind") == "spec":
        record_spec_checkpoint(root, {"state": "published"})
    if operation == "finalize":
        close_run(root, "succeeded")
    return result


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
