from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .artifacts import load_current_spec
from .common import SdlcError, read_json, utc_now
from .journal import active_run, resolve_rework, running_attempt, start_rework
from .runs import stop_active
from .schema_validation import validate_schema_instance
from .sources import load_source
from .stores import read_evidence_record, write_evidence_record
from .layout import state_root


_FEEDBACK_ID = re.compile(r"^FB-([0-9]{4})$")
_TARGET_PHASE = {
    "implementation": "code",
    "spec": "spec",
    "test_contract": "spec",
}


def prepare_rework(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    validate_schema_instance(root, "interactions/rework.schema.json", payload)
    from .status import status

    current = status(root)
    run = active_run(root)
    if (
        (not run or run.get("state") in {"succeeded", "aborted"})
        and current.get("current_version")
    ):
        raise SdlcError("已结束的 Run 不能原地返工；请创建新的修复 Task/Run")
    if not current["gates"]["spec"]:
        raise SdlcError("返工要求已发布 Spec baseline")
    active = current.get("rework")
    if active and active.get("status") == "active":
        raise SdlcError(
            f"已有未完成返工 {active['feedback_id']}，不能并行创建新的 Feedback"
        )
    origin = payload["origin"]
    if origin in {"manual_preview", "manual_acceptance"} and not current["gates"]["code"]:
        raise SdlcError("人工反馈返工要求当前 code gate 已通过")
    if origin == "automated_test":
        journal = current["journal"]
        if not (
            journal.get("state") == "failed"
            and journal.get("phase") == "test"
        ):
            raise SdlcError("automated_test 返工要求已记录 failed test attempt")
    _validate_affected_ids(root, payload["affected_ids"])
    _validate_source_refs(root, payload["source_refs"])
    feedback_id = _next_feedback_id(root)
    spec_pointer = read_json(
        root / "docs" / "sdlc" / "current.json",
        required=True,
    )
    return {
        **payload,
        "feedback_id": feedback_id,
        "reported_baseline_id": spec_pointer["baseline_id"],
        "target_phase": _TARGET_PHASE[payload["classification"]],
        "status": "active",
        "stage": "reported",
        "reported_at": utc_now(),
        "resolved_at": None,
    }


def begin_rework(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    feedback = prepare_rework(root, payload)
    write_evidence_record(
        root,
        f"feedback/{feedback['feedback_id']}",
        feedback,
        state="active",
        title=f"Feedback {feedback['feedback_id']}",
    )
    preview_stop = stop_active(root)
    start_rework(
        root,
        feedback_id=feedback["feedback_id"],
        target_phase=feedback["target_phase"],
        origin=feedback["origin"],
        classification=feedback["classification"],
    )
    stored = {**feedback, "preview_stop": preview_stop}
    write_evidence_record(
        root,
        f"feedback/{feedback['feedback_id']}",
        stored,
        state="active",
        title=f"Feedback {feedback['feedback_id']}",
    )
    return {
        "ok": True,
        "feedback_id": feedback["feedback_id"],
        "target_phase": feedback["target_phase"],
        "stage": "reported",
        "preview_stop": preview_stop,
    }


def active_feedback(root: Path) -> dict[str, Any] | None:
    feedback = feedback_status(root)
    if feedback is None or feedback.get("status") != "active":
        return None
    return feedback


def feedback_status(root: Path) -> dict[str, Any] | None:
    run = active_run(root)
    rework = (run or {}).get("rework")
    if not isinstance(rework, dict):
        return None
    feedback_id = rework.get("feedback_id")
    if not isinstance(feedback_id, str):
        raise SdlcError("active rework 缺少 feedback_id")
    feedback = read_evidence_record(
        root,
        f"feedback/{feedback_id}",
        required=False,
    )
    if feedback is None:
        raise SdlcError(f"rework 缺少 Feedback evidence: {feedback_id}")
    return {**feedback, **rework}


def resolve_feedback(
    root: Path,
    *,
    binding: dict[str, Any],
    test_results: str,
) -> dict[str, Any] | None:
    feedback = active_feedback(root)
    if feedback is None:
        return None
    resolved = resolve_rework(root)
    if resolved is None:
        return None
    value = {
        **feedback,
        **resolved,
        "resolution": {
            "binding": binding,
            "test_results": test_results,
        },
    }
    write_evidence_record(
        root,
        f"feedback/{feedback['feedback_id']}",
        value,
        state="resolved",
        title=f"Feedback {feedback['feedback_id']}",
    )
    return value


def authorize_coder_source_query(
    root: Path,
    source_id: str,
    anchor: str,
) -> None:
    attempt = running_attempt(root, operation="task-before")
    if not attempt or attempt.get("step") != "task-before:coder":
        raise SdlcError("coder Source 查询要求 active coder attempt")
    spec = load_current_spec(root)
    allowed = {
        f"{reference['source_id']}#{reference['anchor']}"
        for item in spec["requirements"]["items"]
        for reference in item.get("source_refs", [])
    }
    feedback = active_feedback(root)
    if feedback is not None:
        allowed.update(feedback.get("source_refs", []))
    reference = f"{source_id}#{anchor}"
    if reference not in allowed:
        raise SdlcError(
            "coder 只能查询当前 Spec/Feedback context 声明的 Source anchor: "
            f"{reference}"
        )


def _next_feedback_id(root: Path) -> str:
    directory = state_root(root) / "evidence" / "feedback"
    numbers = []
    if directory.is_dir():
        for path in directory.glob("FB-*.json"):
            match = _FEEDBACK_ID.fullmatch(path.stem)
            if match:
                numbers.append(int(match.group(1)))
    return f"FB-{max(numbers, default=0) + 1:04d}"


def _validate_affected_ids(root: Path, affected_ids: list[str]) -> None:
    spec = load_current_spec(root)
    known = {
        item["id"]
        for group in ("requirements", "design", "test_plan")
        for item in spec[group]["items"]
    }
    known.update(
        criterion["id"]
        for item in spec["requirements"]["items"]
        for criterion in item["acceptance_criteria"]
    )
    unknown = sorted(set(affected_ids) - known)
    if unknown:
        raise SdlcError(f"Feedback affected_ids 不属于当前 Spec: {unknown}")


def _validate_source_refs(root: Path, references: list[str]) -> None:
    for reference in references:
        source_id, anchor = reference.split("#", 1)
        source = load_source(root, source_id)
        if anchor not in {item["anchor"] for item in source["segments"]}:
            raise SdlcError(f"未知来源 anchor: {reference}")
