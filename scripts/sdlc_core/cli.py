from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .adapter import (
    after_task,
    before_task,
    task_deadline_seconds,
    validate_write_path,
)
from .bootstrap import bootstrap
from .common import SdlcError, project_root
from .layout import contracts_root
from .stores import read_evidence_record
from .lifecycle import (
    compile_restart_verify,
    execute_tests,
    activate_template_rules,
    init_project,
    install_system_tool,
    probe_tools,
    run_phase,
    run_focused_checks,
    run_test_plan,
    start,
    stop_active,
    verify_health,
    verify_delivery,
)
from .runs import record_tokens
from .journal import (
    begin_attempt,
    cancel_running_attempt,
    close_run,
    finish_attempt,
    heartbeat_attempt,
    discard_spec_work,
    query_spec_work,
    record_spec_work,
    running_attempt,
)
from .status import status
from .versions import finalize
from .sources import ingest_source, query_source
from .spec_candidates import (
    begin_candidate,
    put_design,
    put_requirement,
    put_verification,
    validate_candidate,
)
from .spec_publisher import approve_and_promote


def _input() -> dict[str, Any]:
    text = sys.stdin.read()
    if not text.strip():
        return {}
    value = json.loads(text)
    if not isinstance(value, dict):
        raise SdlcError("stdin JSON 必须是对象")
    return value


def _validate_request(operation: str, payload: dict[str, Any]) -> None:
    """Reject structurally incomplete requests before they can affect a Run."""
    if operation != "spec-candidate" or payload.get("action") != "approve":
        return
    missing = [
        field
        for field in ("candidate_id", "content_hash")
        if not isinstance(payload.get(field), str) or not payload[field].strip()
    ]
    if payload.get("confirmed") is not True:
        missing.append("confirmed=true")
    if missing:
        raise SdlcError(
            "spec-candidate approve 缺少必填字段: " + ", ".join(missing)
        )


def _execute(root: Path, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    if operation == "status":
        return status(root)
    if operation == "source-query":
        return query_source(root, payload["source_id"], payload["anchor"])
    if operation == "spec-work-query":
        return query_spec_work(root)
    if operation == "spec-candidate":
        action = payload.get("action")
        if action == "begin":
            return begin_candidate(
                root,
                title=payload["title"],
                source_refs=payload["source_refs"],
            )
        if action == "put-requirement":
            return put_requirement(
                root, payload["candidate_id"], payload["requirement"]
            )
        if action == "put-design":
            return put_design(root, payload["candidate_id"], payload["design"])
        if action == "put-verification":
            return put_verification(
                root, payload["candidate_id"], payload["verification"]
            )
        if action == "validate":
            return validate_candidate(root, payload["candidate_id"])
        if action == "approve":
            return approve_and_promote(
                root,
                candidate_id=payload["candidate_id"],
                content_hash=payload["content_hash"],
                confirmed=bool(payload.get("confirmed")),
            )
        raise SdlcError(f"不支持的 spec-candidate action: {action}")
    if operation == "publish":
        kind = payload.get("kind")
        if kind == "tokens":
            return record_tokens(root, **payload["payload"])
        if kind == "spec-work":
            return record_spec_work(root, payload["payload"])
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
            contract_root = contracts_root(lifecycle_root)
            contracts_present = all(
                (contract_root / name).is_file()
                for name in ("lifecycle.json", "scaffold.json")
            )
            existing_report = read_evidence_record(
                lifecycle_root, "init", required=False
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
        if action == "verify_delivery":
            return verify_delivery(lifecycle_root)
        if action == "focused_check":
            return run_focused_checks(
                lifecycle_root,
                payload.get("test_ids"),
            )
        if action == "start":
            return start(lifecycle_root)
        if action == "stop":
            return stop_active(lifecycle_root)
        if action == "health":
            return verify_health(lifecycle_root)
        if action in {"record_test_results", "test"}:
            return execute_tests(lifecycle_root)
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
    if operation == "task-heartbeat":
        return heartbeat_attempt(
            root,
            operation="task-before",
            owner_pid=payload.get("owner_pid"),
        )
    if operation == "write-check":
        attempt = running_attempt(root, operation="task-before")
        role = (
            str(attempt.get("step", "")).removeprefix("task-before:")
            if attempt else None
        )
        checked = validate_write_path(
            root,
            payload["path"],
            role=role,
        )
        heartbeat = heartbeat_attempt(
            root,
            operation="task-before",
            owner_pid=payload.get("owner_pid"),
        )
        return {
            "ok": True,
            "path": checked["path"],
            "role": role,
            "heartbeat": heartbeat,
        }
    if operation == "task-cancel":
        stop = stop_active(root)
        return {
            **cancel_running_attempt(
                root,
                operation="task-before",
                reason=str(payload.get("reason", "coder deadline cancelled")),
            ),
            "process_cleanup": stop,
        }
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
    if operation == "spec-candidate":
        return "spec", str(payload.get("action", "candidate"))
    if operation == "publish":
        return "spec", str(payload.get("kind", "publish"))
    if operation == "lifecycle":
        action = str(payload.get("action", "unknown"))
        if action == "init" or action == "probe" or action == "system_install":
            return "init", action
        if action in {
            "execute_test_plan", "run_tests", "record_test_results", "test",
            "verify_delivery",
        }:
            return "test", action
        if action == "focused_check":
            return "code", action
        return "code", action
    if operation in {"task-before", "task-after"}:
        role = str(payload.get("role", "unknown"))
        return ("test" if role == "tester" else "code"), f"{operation}:{role}"
    if operation == "finalize":
        return "version", "finalize"
    if operation == "path-check":
        return "code", "write-guard"
    return "unknown", operation


def execute(root: Path, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    _validate_request(operation, payload)
    if operation in {"task-heartbeat", "task-cancel"}:
        return _execute(root, operation, payload)
    if operation == "task-before":
        payload = dict(payload)
        if payload.get("role") in {"coder", "tester"}:
            payload["deadline_seconds"] = task_deadline_seconds(
                root,
                str(payload["role"]),
            )
        phase, step = _phase_step(operation, payload)
        attempt = begin_attempt(
            root,
            phase=phase,
            step=step,
            operation=operation,
            payload=payload,
            owner_pid=payload.get("owner_pid"),
            deadline_seconds=payload.get("deadline_seconds"),
        )
        try:
            result = _execute(root, operation, payload)
        except Exception as exc:
            finish_attempt(root, attempt, state="failed", error=str(exc))
            raise
        return {
            **result,
            "attempt_id": attempt["attempt_id"],
            "deadline_seconds": payload.get("deadline_seconds"),
            "deadline_at": attempt.get("deadline_at"),
        }
    if operation == "task-after":
        attempt = running_attempt(root, operation="task-before")
        if not attempt:
            raise SdlcError("subagent dispatch 不存在、已超时或已回收")
        expected_step = f"task-before:{payload.get('role')}"
        if attempt.get("step") != expected_step:
            raise SdlcError(
                f"subagent handoff role 不匹配: "
                f"{attempt.get('step')} != {expected_step}"
            )
        try:
            result = _execute(root, operation, payload)
        except Exception as exc:
            finish_attempt(root, attempt, state="failed", error=str(exc))
            raise
        finish_attempt(root, attempt, state="succeeded", result=result)
        return result
    if operation in {
        "status", "source-query", "spec-work-query", "path-check", "write-check",
    } or (
        operation == "publish" and payload.get("kind") in {"tokens", "spec-work"}
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
    if isinstance(result, dict) and result.get("ok") is False:
        error = str(result.get("error") or f"{phase}:{step} returned ok=false")
        finish_attempt(root, attempt, state="failed", result=result, error=error)
        return result
    finish_attempt(root, attempt, state="succeeded", result=result)
    if (
        operation == "spec-candidate"
        and effective_payload.get("action") == "approve"
    ):
        result = {**result, "spec_work_cleanup": discard_spec_work(root)}
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
            "task-heartbeat", "task-cancel", "write-check", "path-check", "finalize",
            "spec-candidate", "source-query", "spec-work-query",
        ),
    )
    parser.add_argument("--root", help="项目根目录")
    args = parser.parse_args()
    root = project_root(args.root)
    try:
        result = execute(root, args.operation, _input())
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
