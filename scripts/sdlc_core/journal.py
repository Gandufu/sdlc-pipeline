from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from .common import SdlcError, atomic_write, sha256_json, utc_now
from .layout import evidence_root, relative_to_project, state_root, work_root
from .records import (
    read_compact_index,
    write_compact_index,
    write_markdown_record,
)


TERMINAL_STATES = {"succeeded", "failed", "blocked", "aborted"}


def journal_root(root: Path) -> Path:
    return state_root(root) / "runs"


def active_run(root: Path) -> dict[str, Any] | None:
    pointer = read_compact_index(state_root(root) / "active.json", required=False)
    return (
        read_compact_index(_run_dir(root, pointer["run_id"]) / "index.json", required=False)
        if pointer else None
    )


def ensure_run(root: Path, phase: str) -> dict[str, Any]:
    run = active_run(root)
    if run and run.get("state") not in {"succeeded", "aborted"}:
        run.update({"phase": phase, "state": "running", "updated_at": utc_now()})
        write_compact_index(_run_dir(root, run["run_id"]) / "index.json", run)
        return run
    run_id = f"RUN-{uuid.uuid4().hex[:12].upper()}"
    run = {
        "schema_version": "1.0",
        "run_id": run_id,
        "state": "running",
        "phase": phase,
        "attempt_count": 0,
        "last_error_ref": None,
        "last_failure": None,
        "created_at": utc_now(),
        "updated_at": utc_now(),
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
) -> dict[str, Any]:
    run = ensure_run(root, phase)
    number = int(run.get("attempt_count", 0)) + 1
    attempt = {
        "schema_version": "1.0",
        "run_id": run["run_id"],
        "attempt_id": f"A{number:06d}",
        "phase": phase,
        "step": step,
        "operation": operation,
        "state": "running",
        "input_hash": sha256_json(payload),
        "idempotency_key": idempotency_key,
        "owner_pid": owner_pid or os.getpid(),
        "started_at": utc_now(),
        "last_heartbeat_at": utc_now(),
        "finished_at": None,
        "result_ref": None,
        "error_ref": None,
    }
    run.update({"attempt_count": number, "updated_at": utc_now()})
    write_compact_index(_run_dir(root, run["run_id"]) / "index.json", run)
    write_compact_index(_attempt_path(root, attempt), attempt)
    return {"cached": False, **attempt}


def running_attempt(root: Path, *, operation: str) -> dict[str, Any] | None:
    run = active_run(root)
    if not run:
        return None
    paths = sorted((_run_dir(root, run["run_id"]) / "attempts").glob("*.json"))
    matches = [
        read_compact_index(path) for path in paths
        if (value := read_compact_index(path)).get("operation") == operation
        and value.get("state") == "running"
    ]
    return matches[-1] if matches else None


def heartbeat_attempt(
    root: Path, *, operation: str, owner_pid: int | None = None
) -> dict[str, Any]:
    attempt = running_attempt(root, operation=operation)
    if not attempt:
        return {"ok": True, "active": False}
    if owner_pid is not None and attempt.get("owner_pid") != owner_pid:
        raise SdlcError("heartbeat owner 与 dispatch owner 不匹配")
    attempt["last_heartbeat_at"] = utc_now()
    write_compact_index(_attempt_path(root, attempt), attempt)
    return {"ok": True, "active": True, "attempt_id": attempt["attempt_id"]}


def cancel_running_attempt(
    root: Path, *, operation: str, reason: str
) -> dict[str, Any]:
    attempt = running_attempt(root, operation=operation)
    if not attempt:
        return {"ok": True, "cancelled": False}
    finish_attempt(root, attempt, state="aborted", error=reason)
    return {"ok": True, "cancelled": True, "attempt_id": attempt["attempt_id"]}


def finish_attempt(
    root: Path,
    attempt: dict[str, Any],
    *,
    state: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    if state not in TERMINAL_STATES:
        raise SdlcError(f"非法 attempt state: {state}")
    stored = read_compact_index(_attempt_path(root, attempt))
    result_ref = None
    if result is not None:
        path = work_root(root) / "runs" / attempt["run_id"] / f"{attempt['attempt_id']}.md"
        write_markdown_record(path, result, title=f"Attempt {attempt['attempt_id']} result")
        result_ref = relative_to_project(root, path)
    error_ref = None
    if error:
        path = evidence_root(root) / "errors" / attempt["run_id"] / f"{attempt['attempt_id']}.md"
        write_markdown_record(path, {"message": error}, title="Attempt error")
        error_ref = relative_to_project(root, path)
    stored.update({
        "state": state,
        "finished_at": utc_now(),
        "result_ref": result_ref,
        "error_ref": error_ref,
    })
    write_compact_index(_attempt_path(root, attempt), stored)
    run = read_compact_index(_run_dir(root, attempt["run_id"]) / "index.json")
    repeated = (
        int((run.get("last_failure") or {}).get("repeat_count", 0)) + 1
        if error and (run.get("last_failure") or {}).get("message") == error else 1
    )
    run.update({
        "state": "blocked" if error and repeated >= 2 else (
            "running" if state == "succeeded" else state
        ),
        "last_error_ref": error_ref,
        "last_failure": {"message": error, "repeat_count": repeated} if error else run.get("last_failure"),
        "updated_at": utc_now(),
    })
    write_compact_index(_run_dir(root, run["run_id"]) / "index.json", run)


def close_run(root: Path, state: str = "succeeded") -> None:
    run = active_run(root)
    if not run:
        return
    run.update({"state": state, "updated_at": utc_now()})
    write_compact_index(_run_dir(root, run["run_id"]) / "index.json", run)


def append_event(
    root: Path,
    run_id: str,
    event: str,
    *,
    phase: str | None = None,
    **data: Any,
) -> None:
    path = _run_dir(root, run_id) / "events.md"
    current = path.read_text(encoding="utf-8") if path.is_file() else f"# Run {run_id}\n\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(
        path,
        current + f"- `{utc_now()}` `{event}` phase=`{phase or ''}`\n",
    )


def _run_dir(root: Path, run_id: str) -> Path:
    return state_root(root) / "runs" / run_id


def _attempt_path(root: Path, attempt: dict[str, Any]) -> Path:
    return _run_dir(root, attempt["run_id"]) / "attempts" / f"{attempt['attempt_id']}.json"
