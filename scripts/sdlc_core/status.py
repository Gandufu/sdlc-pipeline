from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import (
    current_spec_hashes,
    lifecycle_test_commands,
    load_current_spec,
    unresolved_blocking_questions,
)
from .bootstrap import template_registry
from .common import read_json
from .common import sha256_file
from .journal import journal_status, spec_checkpoint as load_spec_checkpoint
from .memory import memory_summary
from .runs import active_identity_matches, pid_alive, read_active
from .trace import incremental_eligibility, verify_scaffold
from .trace import worktree_fingerprint
from .versions import current_version, parent_manifest


def status(root: Path) -> dict[str, Any]:
    gates: dict[str, bool] = {}
    missing: list[str] = []
    diagnostics: list[dict[str, str]] = []
    parent = parent_manifest(root)
    fingerprint = worktree_fingerprint(root)
    closed_baseline = bool(
        parent and parent.get("status") == "closed" and not fingerprint["entries"]
    )
    contract_root = root / ".sdlc-pipeline"
    contracts_present = all(
        (contract_root / name).is_file()
        for name in ("lifecycle.json", "scaffold.json")
    )
    init = read_json(root / "docs" / "sdlc" / "init-report.json", required=False)
    init_completed = bool(
        contracts_present and init and init.get("status") == "pass"
    )
    gates["init"] = closed_baseline or init_completed
    if not gates["init"]:
        missing.append("docs/sdlc/init-report.json(pass)")
    spec = None
    spec_hashes: dict[str, str] | None = None
    blocking_questions: list[dict[str, Any]] = []
    try:
        spec = load_current_spec(root)
        spec_hashes = current_spec_hashes(root)
        gates["spec"] = True
        blocking_questions = unresolved_blocking_questions(spec)
    except Exception as exc:
        diagnostics.append({
            "code": "spec_invalid_or_missing",
            "message": str(exc),
        })
        gates["spec"] = False
        missing.append("requirements/design/test-plan")
    code = read_json(root / ".sdlc-pipeline" / "runs" / "code-evidence.json", required=False)
    gates["code"] = closed_baseline or bool(
        code and code.get("ok")
        and code.get("spec_hashes") == spec_hashes
        and code.get("source_fingerprint") == fingerprint
    )
    if not gates["code"]:
        missing.append("compile/restart/health/artifact evidence")
    candidate = read_json(
        root / ".sdlc-pipeline" / "runs" / "version-candidate.json",
        required=False,
    )
    lifecycle_path = root / ".sdlc-pipeline" / "lifecycle.json"
    lifecycle_sha256 = sha256_file(lifecycle_path) if lifecycle_path.is_file() else None
    expected_test_binding = {
        "spec_hashes": spec_hashes,
        "lifecycle_sha256": lifecycle_sha256,
        "source_fingerprint": (code or {}).get("source_fingerprint"),
    }
    gates["test"] = closed_baseline or bool(
        candidate and candidate.get("status") in {"ready", "closed"}
        and candidate.get("binding") == expected_test_binding
        and gates["code"]
    )
    if not gates["test"]:
        missing.append("mandatory test results")
    active = read_active(root)
    active_pid = int((active or {}).get("pid", 0))
    stage = "init"
    active_safe = bool(
        active_pid and pid_alive(active_pid) and active_identity_matches(active)
    )
    if active_pid and pid_alive(active_pid) and not active_safe:
        diagnostics.append({
            "code": "active_process_identity_mismatch",
            "message": f"PID {active_pid} 存活但创建身份不匹配",
        })
    if gates["init"]:
        stage = "spec"
    if gates["spec"]:
        stage = "code"
    if gates["code"]:
        stage = "test"
    if gates["test"]:
        stage = "version"
    prerequisites = {
        "init": False,
        "spec": gates["init"],
        "code": gates["spec"] and not blocking_questions,
        "test": gates["code"],
        "version": gates["test"],
    }
    ids = {"R": [], "D": [], "T": []}
    if spec:
        ids = {
            "R": [x["id"] for x in spec["requirements"]["items"]],
            "D": [x["id"] for x in spec["design"]["items"]],
            "T": [x["id"] for x in spec["test_plan"]["items"]],
        }
    try:
        drift = verify_scaffold(root)
    except Exception as exc:
        drift = {"ok": False, "drift": [str(exc)]}
    try:
        incremental = incremental_eligibility(root) if spec else {
            "eligible": False, "reasons": ["missing_spec"]
        }
    except Exception as exc:
        incremental = {"eligible": False, "reasons": [str(exc)]}
    try:
        test_commands = lifecycle_test_commands(root)
        lifecycle_tests = {
            "available": sorted(test_commands),
            "commands": test_commands,
        }
    except Exception as exc:
        lifecycle_tests = {
            "available": [],
            "commands": {},
            "error": str(exc),
        }
    try:
        templates = template_registry()
    except Exception as exc:
        templates = []
        template_error = str(exc)
    else:
        template_error = None
    scaffold_contract = read_json(
        contract_root / "scaffold.json",
        required=False,
    ) or {}
    active_rules = read_json(
        contract_root / "rules" / "active.json",
        required=False,
    )
    init_state = {
        "completed": init_completed,
        "report_status": (init or {}).get("status"),
        "report_created_at": (init or {}).get("created_at"),
        "contracts_present": contracts_present,
        "template_id": scaffold_contract.get("template_id"),
    }
    return {
        "ok": True,
        "current_version": current_version(root),
        "parent_version": parent.get("version") if parent else None,
        "stage": stage,
        "gates": gates,
        "missing": missing,
        "active_pid": active_pid if active_safe else None,
        "unfinished_run": candidate if candidate and candidate.get("status") != "closed" else None,
        "affected_ids": ids,
        "blocking_questions": [
            {"id": item["id"], "question": item["question"]}
            for item in blocking_questions
        ],
        "scaffold": {"ok": drift["ok"], "drift": drift["drift"]},
        "incremental": incremental,
        "lifecycle_tests": lifecycle_tests,
        "init_state": init_state,
        "templates": templates,
        "active_rules": active_rules,
        "template_registry_error": template_error,
        "can_enter_next": prerequisites[stage],
        "journal": journal_status(root),
        "spec_checkpoint": load_spec_checkpoint(root),
        "memory": memory_summary(root),
        "diagnostics": diagnostics,
    }
