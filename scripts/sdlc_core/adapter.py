from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .artifacts import load_current_spec, require_code_ready
from .common import SdlcError, read_json, sha256_json, utc_now
from .journal import active_run
from .layout import state_root
from .records import read_compact_index
from .stores import (
    read_work_record,
    write_work_record,
)
from .trace import (
    changed_path_fingerprints,
    implementation_fingerprint,
    validate_diff,
    verify_extension_points,
)

from .schema_validation import validate_schema_instance


def _active_failure_ref(root: Path, role: str) -> str | None:
    if role != "coder":
        return None
    run = active_run(root) or {}
    run_id = run.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return None
    attempts_dir = state_root(root) / "runs" / run_id / "attempts"
    attempts = [
        read_compact_index(path)
        for path in sorted(attempts_dir.glob("*.json"), reverse=True)
    ]
    current_source_hash = implementation_fingerprint(root)["sha256"]
    expected_input_hash = sha256_json({
        "action": "compile_restart_verify",
        "source_fingerprint": current_source_hash,
    })
    failed = [
        item for item in attempts
        if item.get("state") == "failed"
        and item.get("phase") == "code"
        and isinstance(item.get("error_ref"), str)
        and item.get("operation") == "lifecycle"
        and item.get("step") == "compile_restart_verify"
        and item.get("input_hash") == expected_input_hash
    ]
    selected = failed[0] if failed else None
    if not selected:
        return None
    value = selected["error_ref"]
    normalized = value.replace("\\", "/")
    if not normalized.startswith(".sdlc-pipeline/evidence/errors/"):
        raise SdlcError(f"非法 failure_ref: {value}")
    if not (root / normalized).is_file():
        raise SdlcError(f"failure_ref 不可读: {value}")
    return normalized


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.startswith(("tests/", "test/"))


def _declared_test_paths(root: Path) -> set[str]:
    return {
        item["selector"].replace("\\", "/")
        for item in load_current_spec(root)["test_plan"]["items"]
        if item.get("selector")
    }


def _preflight_unit_test_paths(root: Path) -> set[str]:
    """Return existing unit tests which the contract-owned preflight may run.

    Test preflight is executed after tester handoff.  When it invokes the
    template's full unit suite, stale scaffold unit tests must be maintainable
    by the tester even if the published Spec only declares functional tests.
    Restrict the exception to already-existing files under the contract's unit
    selector patterns; the tester still cannot create arbitrary test sources.
    """
    from .lifecycle import preflight_unit_test_paths

    return preflight_unit_test_paths(root)


def _tester_writable_paths(root: Path) -> set[str]:
    return _declared_test_paths(root) | _preflight_unit_test_paths(root)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    candidates = [text]
    candidates += re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    for candidate in reversed(candidates):
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    decoder = json.JSONDecoder()
    embedded: list[dict[str, Any]] = []
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            embedded.append(value)
    if embedded:
        return embedded[-1]
    raise SdlcError("subagent 输出中没有可解析的 JSON handoff")


def build_stage_brief(root: Path, role: str) -> dict[str, Any]:
    spec = load_current_spec(root)
    requirements = spec["requirements"]["items"]
    designs = spec["design"]["items"]
    tests = spec["test_plan"]["items"]
    from .task_state import task_status

    task = task_status(root) or {}
    iterations = task.get("iterations") or {}
    brief: dict[str, Any] = {
        "schema_version": "1.0",
        "role": role,
        "task_id": task.get("task_id"),
        "stage": task.get("stage"),
        "iteration": int(iterations.get("test" if role == "tester" else "code", 0)),
    }
    if role == "tester":
        coder_handoff = read_work_record(
            root,
            "coder-handoff",
            required=False,
        ) or {}
        brief.update({
            "verification": [
                {
                    "id": item["id"],
                    "level": item["level"],
                    "preconditions": item["preconditions"],
                    "command": item["command"],
                    "selector": item.get("selector"),
                    "expected": item["expected"],
                    "mandatory": item["mandatory"],
                }
                for item in tests
            ],
            "changed_files": coder_handoff.get("changed_files", []),
            "test_targets": sorted(_tester_writable_paths(root)),
            "preflight_unit_test_paths": sorted(_preflight_unit_test_paths(root)),
        })
        return brief

    input_ref = task.get("input_ref")
    if isinstance(input_ref, str) and input_ref:
        brief["input_ref"] = input_ref
    failure_ref = _active_failure_ref(root, "coder")
    if failure_ref:
        brief["failure_ref"] = failure_ref
    brief.update({
        "requirements": [
            {
                "id": item["id"],
                "title": item["title"],
                "goal": item["goal"],
                "scope": item["scope"],
                "non_goals": item["non_goals"],
                "acceptance": item["acceptance_criteria"],
            }
            for item in requirements
        ],
        "design": [
            {
                "id": item["id"],
                "modules": [
                    {
                        "name": module["name"],
                        "responsibility": module["responsibility"],
                    }
                    for module in item["modules"]
                ],
                "allowed_paths": item["allowed_paths"],
                "extension_point": item["extension_point"],
            }
            for item in designs
        ],
    })
    return brief


def before_task(root: Path, role: str) -> dict[str, Any]:
    if role not in {"coder", "tester"}:
        raise SdlcError(f"不允许的 subagent: {role}")
    from .status import status
    from .task_state import task_status

    current = status(root)
    task = task_status(root)
    if role == "coder" and not (
        current["gates"]["init"] and current["gates"]["spec"]
    ):
        raise SdlcError("coder 门禁要求 init 与 spec 均通过")
    if (
        role == "coder"
        and current["gates"]["code"]
        and (task or {}).get("stage") != "code"
    ):
        raise SdlcError(
            "code gate 已通过；请先把 Task 流转回 code"
        )
    if role == "tester" and not current["gates"]["code"]:
        raise SdlcError("tester 门禁要求 code gate 已通过")
    if role == "coder":
        require_code_ready(load_current_spec(root))
    verify_extension_points(root)
    spec_pointer = read_json(root / "docs" / "sdlc" / "current.json", required=False) or {}
    implementation: dict[str, Any] | None = None
    if role == "tester":
        implementation = implementation_fingerprint(root)
        previous_dispatch = read_work_record(
            root,
            "tester-dispatch",
            required=False,
        )
        write_work_record(
            root,
            "tester-dispatch",
            {
                "baseline_id": spec_pointer.get("baseline_id"),
                "implementation_fingerprint": implementation["sha256"],
                "created_at": utc_now(),
            },
            state="captured",
            title="Tester dispatch boundary",
        )
    previous = read_work_record(root, f"task/{role}-before", required=False)
    reuse_baseline = (
        previous is not None
        and previous.get("baseline_id") == spec_pointer.get("baseline_id")
        and (
            role != "tester"
            or previous.get("implementation_fingerprint") == implementation["sha256"]
        )
        and not current["gates"]["test" if role == "tester" else "code"]
    )
    if not reuse_baseline:
        before = changed_path_fingerprints(root)
        before_record = {
            "created_at": utc_now(),
            "baseline_id": spec_pointer.get("baseline_id"),
            "changed_paths": [item["path"] for item in before["entries"]],
            "worktree": before,
        }
        if implementation is not None:
            before_record["implementation_fingerprint"] = implementation["sha256"]
        write_work_record(
            root,
            f"task/{role}-before",
            before_record,
            state="captured",
            title=f"{role} task before snapshot",
        )
    brief = build_stage_brief(root, role)
    requirement_count = len(load_current_spec(root)["requirements"]["items"])
    return {
        "ok": True,
        "role": role,
        "requirement_count": requirement_count,
        "baseline": "reused" if reuse_baseline else "created",
        "brief": brief,
        "instruction": "严格按 brief 完成本阶段，并返回 Agent 约定的裸 JSON handoff。",
    }


def validate_coder_handoff(root: Path, text: str) -> dict[str, Any]:
    value = _extract_json(text)
    validate_schema_instance(root, "handoff.schema.json", value)
    before = read_work_record(root, "task/coder-before")
    diff = validate_diff(root, before.get("worktree", before.get("changed_paths", [])))
    actual = sorted(set(diff["changed_paths"]))
    if not actual:
        raise SdlcError(
            "coder handoff 未产生实现改动；请完成当前 Feature Slice 后再提交 handoff"
        )
    from .task_state import task_status

    task = task_status(root) or {}
    value["task_id"] = task.get("task_id")
    value["stage_iteration"] = int(
        (task.get("iterations") or {}).get("code", 0)
    )
    value["changed_files"] = actual
    value["validated_at"] = utc_now()
    value["compiled_claim_ignored"] = True
    value["mapping_strategy"] = "post-code-delivery-trace"
    write_work_record(
        root,
        "coder-handoff",
        value,
        state="validated",
        title="Coder handoff",
    )
    return {"ok": True, "handoff": value, "diff": diff}


def validate_tester_handoff(root: Path, text: str) -> dict[str, Any]:
    recovery_reason: str | None = None
    try:
        value = _extract_json(text)
    except SdlcError as error:
        # Some OpenCode task transports can lose the tester's final JSON even
        # after its constrained writes have completed.  Do not manufacture a
        # claim on behalf of the agent: only recover a receipt after the same
        # declared-selector checks below have independently proved that test
        # sources were delivered.  The receipt remains
        # explicitly marked so the release audit can distinguish it.
        recovery_reason = str(error)
        value = {
            "summary": "Core 根据已声明测试改动恢复 tester handoff 收据",
            "open_issues": [],
            "full_scan": False,
            "full_scan_reason": "subagent JSON handoff 缺失；Core 将核验声明的测试文件和 diff",
        }
    validate_schema_instance(root, "handoff.schema.json", value)
    before = read_work_record(root, "task/tester-before")
    diff = validate_diff(
        root,
        before.get("worktree", before.get("changed_paths", [])),
    )
    actual = sorted(set(diff["changed_paths"]))
    declared = _declared_test_paths(root)
    allowed = _tester_writable_paths(root)
    outside = [path for path in actual if path not in allowed]
    if outside:
        raise SdlcError(
            "tester handoff 只能包含 Spec 声明的测试脚本或"
            f"预检必需的既有单元测试: {outside}"
        )
    missing = sorted(path for path in declared if not (root / path).is_file())
    if missing:
        raise SdlcError(f"Spec 声明的测试脚本不存在: {missing}")
    if recovery_reason is not None and not actual:
        raise SdlcError(recovery_reason)
    from .task_state import task_status

    task = task_status(root) or {}
    value["task_id"] = task.get("task_id")
    value["stage_iteration"] = int(
        (task.get("iterations") or {}).get("test", 0)
    )
    value["changed_files"] = actual
    value["validated_at"] = utc_now()
    value["mapping_strategy"] = "post-test-delivery-trace"
    if recovery_reason is not None:
        value["output_recovery"] = {
            "mode": "declared-test-diff",
            "reason": recovery_reason,
            "observed_paths": actual,
        }
    write_work_record(
        root,
        "tester-handoff",
        value,
        state="validated",
        title=(
            "Tester handoff (Core recovery)"
            if recovery_reason is not None else "Tester handoff"
        ),
    )
    return {"ok": True, "handoff": value, "diff": diff}


def after_task(root: Path, role: str, output: str) -> dict[str, Any]:
    if role == "coder":
        return validate_coder_handoff(root, output)
    if role == "tester":
        return validate_tester_handoff(root, output)
    raise SdlcError(f"不允许的 subagent: {role}")
