from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .common import SdlcError, atomic_write, utc_now
from .layout import evidence_root, state_root, work_root
from .records import read_compact_index, write_compact_index


STAGES = {
    "spec",
    "awaiting_spec_approval",
    "code",
    "human_review",
    "test",
    "awaiting_release_approval",
    "finalized",
}

TRANSITIONS = {
    "spec_prepared": ({"spec"}, "awaiting_spec_approval"),
    "spec_approved": ({"awaiting_spec_approval"}, "code"),
    "code_completed": ({"code"}, "human_review"),
    "implementation_issue": ({"human_review", "test"}, "code"),
    "requirements_issue": ({"human_review", "test"}, "spec"),
    "review_passed": ({"human_review"}, "test"),
    "test_issue": ({"test"}, "test"),
    "test_completed": ({"test"}, "awaiting_release_approval"),
    "finalized": ({"awaiting_release_approval"}, "finalized"),
}


def task_status(root: Path) -> dict[str, Any] | None:
    return read_compact_index(state_root(root) / "task.json", required=False)


def record_input(root: Path, text: str) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise SdlcError("用户原始需求不能为空")
    task = task_status(root)
    if task is None or task.get("stage") == "finalized":
        task = _create_task(root, previous=task)
    input_path = work_root(root) / "input.md"
    existing = input_path.read_text(encoding="utf-8") if input_path.is_file() else ""
    heading = f"## {utc_now()}\n\n"
    atomic_write(input_path, existing + heading + text.strip() + "\n\n")
    task["input_ref"] = input_path.relative_to(root).as_posix()
    task["updated_at"] = utc_now()
    write_compact_index(state_root(root) / "task.json", task)
    _append_event(root, task, "input.recorded", {"characters": len(text.strip())})
    return {"ok": True, "task": task}


def transition(root: Path, event: str) -> dict[str, Any]:
    task = task_status(root)
    if task is None:
        raise SdlcError("当前没有活动 Task；请先记录用户原始需求")
    if event not in TRANSITIONS:
        raise SdlcError(f"未知 Task 事件: {event}")
    allowed, target = TRANSITIONS[event]
    current = str(task.get("stage"))
    if current == target and event in {"test_issue"}:
        pass
    elif current not in allowed:
        raise SdlcError(f"Task 不能从 {current} 通过 {event} 进入 {target}")
    previous = current
    task["stage"] = target
    task["status"] = "completed" if target == "finalized" else "active"
    iterations = dict(task.get("iterations", {}))
    if event in {"spec_approved", "implementation_issue", "requirements_issue"}:
        key = "spec" if event == "requirements_issue" else "code"
        iterations[key] = int(iterations.get(key, 0)) + 1
    if event in {"review_passed", "test_issue"}:
        iterations["test"] = int(iterations.get("test", 0)) + 1
    task["iterations"] = iterations
    task["updated_at"] = utc_now()
    write_compact_index(state_root(root) / "task.json", task)
    _append_event(
        root,
        task,
        f"task.{event}",
        {"from": previous, "to": target},
    )
    return {"ok": True, "task": task, "from": previous, "to": target}


def set_pending_spec(root: Path, content_hash: str | None) -> dict[str, Any]:
    task = task_status(root)
    if task is None:
        raise SdlcError("当前没有活动 Task；请先记录用户原始需求")
    task["pending_spec_hash"] = content_hash
    task["updated_at"] = utc_now()
    write_compact_index(state_root(root) / "task.json", task)
    return task


def _create_task(
    root: Path,
    *,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    now = utc_now()
    task = {
        "schema_version": "1.0",
        "task_id": f"TASK-{uuid.uuid4().hex[:8].upper()}",
        "stage": "spec",
        "status": "active",
        "iterations": {"spec": 1, "code": 0, "test": 0},
        "previous_task_id": previous.get("task_id") if previous else None,
        "input_ref": None,
        "created_at": now,
        "updated_at": now,
    }
    write_compact_index(state_root(root) / "task.json", task)
    _append_event(root, task, "task.created", {"from": None, "to": "spec"})
    return task


def _append_event(
    root: Path,
    task: dict[str, Any],
    event: str,
    data: dict[str, Any],
) -> None:
    path = evidence_root(root) / "task-events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": utc_now(),
        "task_id": task["task_id"],
        "event": event,
        "stage": task["stage"],
        "data": data,
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
