from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .common import SdlcError, read_json, sha256_json, utc_now, write_json
from .failures import failure_fingerprint
from .schema_validation import validate_schema_instance
from .sources import load_source


TERMINAL_STATES = {"succeeded", "failed", "blocked", "aborted"}


def journal_root(root: Path) -> Path:
    return root / ".sdlc-pipeline" / "runs" / "journal"


def active_run(root: Path) -> dict[str, Any] | None:
    pointer = read_json(journal_root(root) / "active.json", required=False)
    if not pointer:
        return None
    run = read_json(journal_root(root) / pointer["run_id"] / "run.json", required=False)
    return run


def ensure_run(root: Path, phase: str) -> dict[str, Any]:
    run = active_run(root)
    if run and run.get("state") not in {"succeeded", "aborted"}:
        if run.get("phase") != phase:
            previous = run.get("phase")
            run["phase"] = phase
            run["state"] = "running"
            run["updated_at"] = utc_now()
            write_json(_run_dir(root, run["run_id"]) / "run.json", run)
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
        "schema_version": "1.0",
        "run_id": run_id,
        "state": "running",
        "phase": phase,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "attempt_count": 0,
        "last_error": None,
    }
    directory = journal_root(root) / run_id
    write_json(directory / "run.json", run)
    write_json(journal_root(root) / "active.json", {"run_id": run_id})
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
            "Run 已进入 BLOCKED；请先处理最近失败或显式开始新 Run"
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
                return {
                    "cached": True,
                    "result": cached["result"],
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
        "schema_version": "1.0",
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
        "result": None,
        "error": None,
    }
    run.update({
        "state": "running",
        "phase": phase,
        "attempt_count": attempt_number,
        "updated_at": utc_now(),
        "last_error": None,
    })
    write_json(_run_dir(root, run_id) / "run.json", run)
    write_json(_attempt_path(root, run_id, phase, attempt_id), attempt)
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
    write_json(
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
    attempt_path = _attempt_path(
        root, run_id, attempt["phase"], attempt["attempt_id"]
    )
    stored = read_json(attempt_path)
    stored.update({
        "state": state,
        "finished_at": utc_now(),
        "result": result,
        "result_hash": sha256_json(result) if result is not None else None,
        "error": error,
    })
    write_json(attempt_path, stored)
    run = read_json(_run_dir(root, run_id) / "run.json")
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
    elif state == "succeeded":
        last_failure = None
    run.update({
        "state": final_state,
        "phase": attempt["phase"],
        "updated_at": utc_now(),
        "last_error": error,
        "last_failure": last_failure,
    })
    write_json(_run_dir(root, run_id) / "run.json", run)
    if attempt.get("idempotency_key"):
        write_json(
            _idempotency_path(root, run_id, attempt["idempotency_key"]),
            {
                "key": attempt["idempotency_key"],
                "binding": attempt["input_hash"],
                "attempt_id": attempt["attempt_id"],
                "state": state,
                "result": result,
                "updated_at": utc_now(),
            },
        )
    append_event(
        root,
        run_id,
        f"attempt.{state}",
        phase=attempt["phase"],
        step=attempt["step"],
        attempt_id=attempt["attempt_id"],
        data={"error": error, "result_hash": stored.get("result_hash")},
    )


def close_run(root: Path, state: str = "succeeded") -> None:
    run = active_run(root)
    if not run:
        return
    run["state"] = state
    run["updated_at"] = utc_now()
    write_json(_run_dir(root, run["run_id"]) / "run.json", run)
    append_event(root, run["run_id"], f"run.{state}", phase=run.get("phase"))


def record_spec_checkpoint(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    validate_schema_instance(root, "spec-checkpoint.schema.json", payload)
    for reference in payload.get("source_refs", []):
        source_id, anchor = reference.split("#", 1)
        source = load_source(root, source_id)
        if anchor not in {item["anchor"] for item in source["segments"]}:
            raise SdlcError(f"未知来源 anchor: {reference}")
    run = ensure_run(root, "spec")
    path = _run_dir(root, run["run_id"]) / "checkpoints" / "spec.json"
    checkpoint = read_json(path, required=False) or {
        "schema_version": "1.0",
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
            item for item in checkpoint["decisions"]
            if item.get("id") != question["id"]
        ]
        decisions.append({**question, "recorded_at": utc_now()})
        checkpoint["decisions"] = sorted(decisions, key=lambda item: item["id"])
    for name in ("source_refs", "confirmed_facts", "assumptions", "risks"):
        if name in payload:
            if not isinstance(payload[name], list):
                raise SdlcError(f"spec checkpoint {name} 必须是数组")
            checkpoint[name] = payload[name]
    if "state" in payload:
        if payload["state"] not in {"interviewing", "ready", "confirmed", "published"}:
            raise SdlcError("非法 spec checkpoint state")
        checkpoint["state"] = payload["state"]
    checkpoint["updated_at"] = utc_now()
    write_json(path, checkpoint)
    append_event(
        root,
        run["run_id"],
        "spec.checkpoint",
        phase="spec",
        step="grilling",
        data={
            "question_id": (question or {}).get("id"),
            "state": checkpoint["state"],
            "decision_count": len(checkpoint["decisions"]),
        },
    )
    return {"ok": True, "checkpoint": checkpoint}


def spec_checkpoint(root: Path) -> dict[str, Any] | None:
    run = active_run(root)
    if not run:
        return None
    return read_json(
        _run_dir(root, run["run_id"]) / "checkpoints" / "spec.json",
        required=False,
    )


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
        "last_error": run.get("last_error"),
        "last_failure": run.get("last_failure"),
        "updated_at": run["updated_at"],
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
    value = {
        "schema_version": "1.0",
        "event_id": uuid.uuid4().hex,
        "run_id": run_id,
        "event": event,
        "phase": phase,
        "step": step,
        "attempt_id": attempt_id,
        "created_at": utc_now(),
        "data": data or {},
    }
    path = _run_dir(root, run_id) / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
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
    return read_json(_idempotency_path(root, run_id, key), required=False)


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
    attempts: list[dict[str, Any]] = []
    for path in directory.glob("*/*.json"):
        value = read_json(path, required=False)
        if value and value.get("state") == "running":
            attempts.append(value)
    return sorted(attempts, key=lambda item: item["attempt_id"])


def _reconcile_abandoned_attempts(root: Path, run: dict[str, Any]) -> None:
    recovered = False
    for attempt in _running_attempts(root, run["run_id"]):
        deadline_at = attempt.get("deadline_at")
        expired = bool(
            deadline_at
            and datetime.fromisoformat(deadline_at) <= datetime.now(timezone.utc)
        )
        if _owner_alive(attempt.get("owner")) and not expired:
            continue
        recovered = True
        reason = (
            "attempt deadline expired before completion"
            if expired
            else "owner process exited before attempt completion"
        )
        path = _attempt_path(
            root, run["run_id"], attempt["phase"], attempt["attempt_id"]
        )
        attempt.update({
            "state": "aborted",
            "finished_at": utc_now(),
            "error": reason,
        })
        write_json(path, attempt)
        append_event(
            root,
            run["run_id"],
            "attempt.aborted",
            phase=attempt["phase"],
            step=attempt["step"],
            attempt_id=attempt["attempt_id"],
            data={"error": attempt["error"], "recovered": True},
        )
    if recovered:
        run.update({
            "state": "aborted",
            "updated_at": utc_now(),
            "last_error": reason,
        })
        write_json(_run_dir(root, run["run_id"]) / "run.json", run)
        append_event(
            root,
            run["run_id"],
            "run.aborted",
            phase=run.get("phase"),
            data={"reason": run["last_error"], "recovered": True},
        )
