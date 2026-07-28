from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .common import SdlcError, sha256_json, utc_now
from .failures import failure_fingerprint
from .layout import evidence_root, relative_to_project, state_root, work_root
from .records import (
    read_compact_index,
    read_markdown_record,
    write_compact_index,
    write_markdown_record,
)
from .schema_validation import validate_schema_instance
from .sources import load_source


TERMINAL_STATES = {"succeeded", "failed", "blocked", "aborted"}


def journal_root(root: Path) -> Path:
    return state_root(root) / "runs"


def active_run(root: Path) -> dict[str, Any] | None:
    pointer = read_compact_index(state_root(root) / "active.json", required=False)
    if not pointer:
        return None
    return read_compact_index(
        _run_dir(root, pointer["run_id"]) / "index.json", required=False
    )


def ensure_run(root: Path, phase: str) -> dict[str, Any]:
    run = active_run(root)
    if run and run.get("state") not in {"succeeded", "aborted"}:
        if run.get("phase") != phase:
            if run.get("state") in {"failed", "blocked"}:
                raise SdlcError(
                    f"Run {run['run_id']} 在 {run['phase']} 阶段失败；"
                    "禁止通过切换阶段清除失败状态"
                )
            previous = run.get("phase")
            run["phase"] = phase
            run["state"] = "running"
            run["updated_at"] = utc_now()
            write_compact_index(_run_dir(root, run["run_id"]) / "index.json", run)
            append_event(
                root,
                run["run_id"],
                "run.phase_changed",
                phase=phase,
                data={"previous_phase": previous, "phase": phase},
            )
        return run
    run_id = f"RUN-{utc_now().replace(':', '').replace('-', '')}-{uuid.uuid4().hex[:8]}"
    run = {
        "schema_version": "3.0",
        "run_id": run_id,
        "state": "running",
        "phase": phase,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "attempt_count": 0,
        "session_ref": relative_to_project(
            root, work_root(root) / "sessions" / f"{run_id}.md"
        ),
        "last_error_ref": None,
        "last_failure": None,
    }
    write_compact_index(_run_dir(root, run_id) / "index.json", run)
    write_compact_index(state_root(root) / "active.json", {"run_id": run_id})
    append_event(root, run_id, "run.started", phase=phase)
    return run


def begin_attempt(
    root: Path,
    *,
    phase: str,
    step: str,
    operation: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
    owner_pid: int | None = None,
    deadline_seconds: int | None = None,
) -> dict[str, Any]:
    run = ensure_run(root, phase)
    if run.get("state") == "blocked":
        raise SdlcError(
            "Run 已进入 BLOCKED；请处理最近失败后显式开始新 Run"
        )
    _reconcile_abandoned_attempts(root, run)
    run_id = run["run_id"]
    binding = sha256_json({
        "operation": operation,
        "phase": phase,
        "step": step,
        "payload": payload,
    })
    if idempotency_key:
        cached = _idempotency_record(root, run_id, idempotency_key)
        if cached:
            if cached.get("binding") != binding:
                raise SdlcError(
                    f"idempotency key 已绑定不同输入: {idempotency_key}"
                )
            if cached.get("state") == "succeeded":
                result = read_markdown_record(root / cached["result_ref"])
                return {
                    "cached": True,
                    "result": result,
                    "attempt_id": cached["attempt_id"],
                    "run_id": run_id,
                }
    attempt_number = int(run.get("attempt_count", 0)) + 1
    attempt_id = f"A{attempt_number:06d}"
    started_at = utc_now()
    deadline_at = None
    if deadline_seconds is not None:
        if deadline_seconds < 1:
            raise SdlcError("attempt deadline_seconds 必须大于 0")
        deadline_at = (
            datetime.now(timezone.utc) + timedelta(seconds=deadline_seconds)
        ).isoformat()
    attempt = {
        "schema_version": "3.0",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "phase": phase,
        "step": step,
        "operation": operation,
        "state": "running",
        "input_hash": binding,
        "idempotency_key": idempotency_key,
        "owner": _owner_identity(owner_pid),
        "started_at": started_at,
        "last_heartbeat_at": started_at,
        "deadline_at": deadline_at,
        "finished_at": None,
        "result_ref": None,
        "result_hash": None,
        "error_ref": None,
    }
    run.update({
        "state": "running",
        "phase": phase,
        "attempt_count": attempt_number,
        "updated_at": utc_now(),
    })
    write_compact_index(_run_dir(root, run_id) / "index.json", run)
    write_compact_index(
        _attempt_path(root, run_id, phase, attempt_id), attempt
    )
    append_event(
        root,
        run_id,
        "attempt.started",
        phase=phase,
        step=step,
        attempt_id=attempt_id,
        data={"operation": operation, "input_hash": binding},
    )
    return {"cached": False, **attempt}


def heartbeat_attempt(
    root: Path,
    *,
    operation: str,
    owner_pid: int | None = None,
) -> dict[str, Any]:
    run = active_run(root)
    if not run:
        return {"ok": True, "active": False}
    attempts = [
        item for item in _running_attempts(root, run["run_id"])
        if item.get("operation") == operation
    ]
    if not attempts:
        return {"ok": True, "active": False}
    attempt = attempts[-1]
    if owner_pid is not None and attempt.get("owner") != _owner_identity(owner_pid):
        raise SdlcError("heartbeat owner 与 coder dispatch owner 不匹配")
    attempt["last_heartbeat_at"] = utc_now()
    write_compact_index(
        _attempt_path(
            root, run["run_id"], attempt["phase"], attempt["attempt_id"]
        ),
        attempt,
    )
    append_event(
        root,
        run["run_id"],
        "attempt.heartbeat",
        phase=attempt["phase"],
        step=attempt["step"],
        attempt_id=attempt["attempt_id"],
        data={"deadline_at": attempt.get("deadline_at")},
    )
    return {
        "ok": True,
        "active": True,
        "attempt_id": attempt["attempt_id"],
        "deadline_at": attempt.get("deadline_at"),
    }


def running_attempt(
    root: Path,
    *,
    operation: str,
) -> dict[str, Any] | None:
    run = active_run(root)
    if not run:
        return None
    matches = [
        item for item in _running_attempts(root, run["run_id"])
        if item.get("operation") == operation
    ]
    return matches[-1] if matches else None


def cancel_running_attempt(
    root: Path,
    *,
    operation: str,
    reason: str,
) -> dict[str, Any]:
    attempt = running_attempt(root, operation=operation)
    if not attempt:
        return {"ok": True, "cancelled": False, "reason": "no_running_attempt"}
    finish_attempt(root, attempt, state="aborted", error=reason)
    return {
        "ok": True,
        "cancelled": True,
        "attempt_id": attempt["attempt_id"],
        "reason": reason,
    }


def finish_attempt(
    root: Path,
    attempt: dict[str, Any],
    *,
    state: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    if state not in TERMINAL_STATES:
        raise SdlcError(f"非法 attempt terminal state: {state}")
    run_id = attempt["run_id"]
    attempt_id = attempt["attempt_id"]
    attempt_path = _attempt_path(
        root, run_id, attempt["phase"], attempt_id
    )
    stored = read_compact_index(attempt_path)
    result_ref = None
    result_hash = None
    if result is not None:
        result_path = (
            work_root(root) / "runs" / run_id / "attempts" / f"{attempt_id}-result.md"
        )
        write_markdown_record(
            result_path,
            result,
            title=f"Attempt {attempt_id} result",
            summary_lines=[
                f"- Phase: `{attempt['phase']}`",
                f"- Step: `{attempt['step']}`",
                f"- State: `{state}`",
            ],
        )
        result_ref = relative_to_project(root, result_path)
        result_hash = sha256_json(result)
    error_ref = None
    if error:
        error_path = evidence_root(root) / "errors" / run_id / f"{attempt_id}.md"
        write_markdown_record(
            error_path,
            {"message": error},
            title=f"Attempt {attempt_id} error",
            summary_lines=[
                f"- Phase: `{attempt['phase']}`",
                f"- Step: `{attempt['step']}`",
                f"- State: `{state}`",
            ],
        )
        error_ref = relative_to_project(root, error_path)
    stored.update({
        "state": state,
        "finished_at": utc_now(),
        "result_ref": result_ref,
        "result_hash": result_hash,
        "error_ref": error_ref,
    })
    write_compact_index(attempt_path, stored)
    run = read_compact_index(_run_dir(root, run_id) / "index.json")
    final_state = "running" if state == "succeeded" else state
    last_failure = run.get("last_failure")
    if state == "failed" and error:
        failure = failure_fingerprint(error)
        repeat_count = (
            int(last_failure.get("repeat_count", 0)) + 1
            if isinstance(last_failure, dict)
            and last_failure.get("fingerprint") == failure["fingerprint"]
            else 1
        )
        last_failure = {**failure, "repeat_count": repeat_count}
        if repeat_count >= 2:
            final_state = "blocked"
    run.update({
        "state": final_state,
        "phase": attempt["phase"],
        "updated_at": utc_now(),
        "last_error_ref": error_ref,
        "last_failure": last_failure,
    })
    write_compact_index(_run_dir(root, run_id) / "index.json", run)
    if attempt.get("idempotency_key"):
        if state == "succeeded" and result_ref is None:
            raise SdlcError("幂等成功 attempt 必须持久化 result_ref")
        write_compact_index(
            _idempotency_path(root, run_id, attempt["idempotency_key"]),
            {
                "key": attempt["idempotency_key"],
                "binding": attempt["input_hash"],
                "attempt_id": attempt_id,
                "state": state,
                "result_ref": result_ref,
                "result_hash": result_hash,
                "updated_at": utc_now(),
            },
        )
    append_event(
        root,
        run_id,
        f"attempt.{state}",
        phase=attempt["phase"],
        step=attempt["step"],
        attempt_id=attempt_id,
        data={
            "error_ref": error_ref,
            "result_ref": result_ref,
            "result_hash": result_hash,
        },
    )


def close_run(root: Path, state: str = "succeeded") -> None:
    run = active_run(root)
    if not run:
        return
    run["state"] = state
    run["updated_at"] = utc_now()
    write_compact_index(_run_dir(root, run["run_id"]) / "index.json", run)
    append_event(root, run["run_id"], f"run.{state}", phase=run.get("phase"))


def record_spec_checkpoint(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_checkpoint_source_refs(payload)
    validate_schema_instance(
        root, "interactions/spec-checkpoint.schema.json", payload
    )
    for reference in payload.get("source_refs", []):
        source_id, anchor = reference.split("#", 1)
        source = load_source(root, source_id)
        if anchor not in {item["anchor"] for item in source["segments"]}:
            raise SdlcError(f"未知来源 anchor: {reference}")
    run = ensure_run(root, "spec")
    current = spec_checkpoint(root) or {
        "schema_version": "3.0",
        "run_id": run["run_id"],
        "state": "interviewing",
        "source_refs": [],
        "decisions": [],
        "confirmed_facts": [],
        "assumptions": [],
        "risks": [],
        "updated_at": utc_now(),
    }
    question = payload.get("question")
    if question:
        if not isinstance(question, dict) or not question.get("id"):
            raise SdlcError("spec checkpoint question 必须包含 id")
        decisions = [
            item for item in current["decisions"]
            if item.get("id") != question["id"]
        ]
        decisions.append({**question, "recorded_at": utc_now()})
        current["decisions"] = sorted(decisions, key=lambda item: item["id"])
    for name in ("source_refs", "confirmed_facts", "assumptions", "risks"):
        if name in payload:
            if not isinstance(payload[name], list):
                raise SdlcError(f"spec checkpoint {name} 必须是数组")
            current[name] = payload[name]
    if "state" in payload:
        if payload["state"] not in {"interviewing", "ready", "confirmed", "published"}:
            raise SdlcError("非法 spec checkpoint state")
        current["state"] = payload["state"]
    current["updated_at"] = utc_now()
    content_path = (
        work_root(root) / "runs" / run["run_id"] / "checkpoints" / "spec.md"
    )
    write_markdown_record(
        content_path,
        current,
        title=f"Spec checkpoint {run['run_id']}",
        summary_lines=[
            f"- State: `{current['state']}`",
            f"- Decisions: `{len(current['decisions'])}`",
        ],
    )
    index = {
        "schema_version": "3.0",
        "run_id": run["run_id"],
        "checkpoint_id": "spec",
        "state": current["state"],
        "source_refs": current["source_refs"],
        "decision_ids": [item["id"] for item in current["decisions"]],
        "content_ref": relative_to_project(root, content_path),
        "content_hash": sha256_json(current),
        "updated_at": current["updated_at"],
    }
    write_compact_index(
        _run_dir(root, run["run_id"]) / "checkpoints" / "spec.json", index
    )
    append_event(
        root,
        run["run_id"],
        "spec.checkpoint",
        phase="spec",
        step="grilling",
        data={
            "question_id": (question or {}).get("id"),
            "state": current["state"],
            "decision_count": len(current["decisions"]),
        },
    )
    return {"ok": True, "checkpoint": current}


def _normalize_checkpoint_source_refs(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    references = normalized.get("source_refs")
    if not isinstance(references, list):
        return normalized
    normalized["source_refs"] = [
        f"{reference['source_id']}#{reference['anchor']}"
        if (
            isinstance(reference, dict)
            and isinstance(reference.get("source_id"), str)
            and isinstance(reference.get("anchor"), str)
        )
        else reference
        for reference in references
    ]
    return normalized


def spec_checkpoint(root: Path) -> dict[str, Any] | None:
    run = active_run(root)
    if not run:
        return None
    index = read_compact_index(
        _run_dir(root, run["run_id"]) / "checkpoints" / "spec.json",
        required=False,
    )
    if not index:
        return None
    value = read_markdown_record(root / index["content_ref"])
    if sha256_json(value) != index["content_hash"]:
        raise SdlcError("spec checkpoint Markdown 与索引 hash 不匹配")
    return value


def journal_status(root: Path) -> dict[str, Any]:
    run = active_run(root)
    if not run:
        return {"active": False}
    _reconcile_abandoned_attempts(root, run)
    run = active_run(root) or run
    running = _running_attempts(root, run["run_id"])
    return {
        "active": True,
        "run_id": run["run_id"],
        "state": run["state"],
        "phase": run["phase"],
        "attempt_count": run["attempt_count"],
        "last_error": _error_message(root, run.get("last_error_ref")),
        "last_error_ref": run.get("last_error_ref"),
        "last_failure": run.get("last_failure"),
        "updated_at": run["updated_at"],
        "session_ref": run["session_ref"],
        "running_attempts": [
            {
                "attempt_id": item["attempt_id"],
                "phase": item["phase"],
                "step": item["step"],
                "owner_alive": _owner_alive(item.get("owner")),
                "last_heartbeat_at": item.get("last_heartbeat_at"),
                "deadline_at": item.get("deadline_at"),
            }
            for item in running
        ],
        "recoverable": any(
            not _owner_alive(item.get("owner")) for item in running
        ),
    }


def append_event(
    root: Path,
    run_id: str,
    event: str,
    *,
    phase: str | None = None,
    step: str | None = None,
    attempt_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    path = work_root(root) / "sessions" / f"{run_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    first = not path.exists()
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        if first:
            stream.write(f"# Session {run_id}\n\n")
        stream.write(
            f"## {utc_now()} · {event}\n\n"
            f"- Phase: `{phase or ''}`\n"
            f"- Step: `{step or ''}`\n"
            f"- Attempt: `{attempt_id or ''}`\n"
        )
        for key, value in sorted((data or {}).items()):
            stream.write(f"- {key}: `{value}`\n")
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _run_dir(root: Path, run_id: str) -> Path:
    return journal_root(root) / run_id


def _attempt_path(root: Path, run_id: str, phase: str, attempt_id: str) -> Path:
    return _run_dir(root, run_id) / "attempts" / phase / f"{attempt_id}.json"


def _idempotency_path(root: Path, run_id: str, key: str) -> Path:
    safe = sha256_json({"key": key})
    return _run_dir(root, run_id) / "idempotency" / f"{safe}.json"


def _idempotency_record(
    root: Path, run_id: str, key: str
) -> dict[str, Any] | None:
    return read_compact_index(
        _idempotency_path(root, run_id, key), required=False
    )


def _owner_identity(pid: int | None = None) -> dict[str, Any]:
    from .runs import process_identity

    pid = os.getpid() if pid is None else int(pid)
    return {"pid": pid, "process_identity": process_identity(pid)}


def _owner_alive(owner: Any) -> bool:
    if not isinstance(owner, dict):
        return False
    from .runs import pid_alive, process_identity

    pid = int(owner.get("pid", 0))
    return (
        pid_alive(pid)
        and isinstance(owner.get("process_identity"), dict)
        and owner["process_identity"] == process_identity(pid)
    )


def _running_attempts(root: Path, run_id: str) -> list[dict[str, Any]]:
    directory = _run_dir(root, run_id) / "attempts"
    if not directory.is_dir():
        return []
    attempts = []
    for path in directory.glob("*/*.json"):
        value = read_compact_index(path, required=False)
        if value and value.get("state") == "running":
            attempts.append(value)
    return sorted(attempts, key=lambda item: item["attempt_id"])


def _reconcile_abandoned_attempts(root: Path, run: dict[str, Any]) -> None:
    for attempt in list(_running_attempts(root, run["run_id"])):
        deadline_at = attempt.get("deadline_at")
        expired = bool(
            deadline_at
            and datetime.fromisoformat(deadline_at) <= datetime.now(timezone.utc)
        )
        if _owner_alive(attempt.get("owner")) and not expired:
            continue
        reason = (
            "attempt deadline expired before completion"
            if expired
            else "owner process exited before attempt completion"
        )
        finish_attempt(root, attempt, state="aborted", error=reason)


def _error_message(root: Path, reference: Any) -> str | None:
    if not isinstance(reference, str) or not reference:
        return None
    value = read_markdown_record(root / reference, required=False)
    if not value:
        return None
    message = value.get("message")
    return message if isinstance(message, str) else None
