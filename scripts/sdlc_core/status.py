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
from .layout import contracts_root, lifecycle_path, runtime_root
from .journal import journal_status, spec_work_index
from .memory import memory_summary
from .runs import active_identity_matches, pid_alive, read_active
from .trace import verify_scaffold
from .trace import (
    implementation_fingerprint,
    test_source_fingerprint,
    worktree_fingerprint,
)
from .versions import current_version, parent_manifest
from .spec_candidates import candidate_status
from .spec_publisher import retry_publication_cleanup
from .stores import read_evidence_record, read_work_record


def status(root: Path) -> dict[str, Any]:
    publication_cleanup = retry_publication_cleanup(root)
    gates: dict[str, bool] = {}
    missing: list[str] = []
    diagnostics: list[dict[str, str]] = []
    parent = parent_manifest(root)
    fingerprint = worktree_fingerprint(root)
    code_fingerprint = implementation_fingerprint(root)
    closed_baseline = bool(
        parent and parent.get("status") == "closed" and not fingerprint["entries"]
    )
    contract_root = contracts_root(root)
    contracts_present = all(
        (contract_root / name).is_file()
        for name in ("lifecycle.json", "scaffold.json")
    )
    init = read_evidence_record(root, "init", required=False)
    init_completed = bool(
        contracts_present and init and init.get("status") == "pass"
    )
    gates["init"] = closed_baseline or init_completed
    if not gates["init"]:
        missing.append(".sdlc-pipeline/evidence/records/init.md(pass)")
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
    code = read_evidence_record(root, "code", required=False)
    gates["code"] = closed_baseline or bool(
        code and code.get("ok")
        and code.get("spec_hashes") == spec_hashes
        and code.get("source_fingerprint") == code_fingerprint
    )
    if not gates["code"]:
        missing.append("compile/package/preview/health/artifact evidence")
    candidate = read_work_record(root, "version-candidate", required=False)
    lifecycle_contract_path = lifecycle_path(root)
    lifecycle_sha256 = (
        sha256_file(lifecycle_contract_path)
        if lifecycle_contract_path.is_file()
        else None
    )
    expected_test_binding = {
        "spec_hashes": spec_hashes,
        "lifecycle_sha256": lifecycle_sha256,
        "source_fingerprint": (code or {}).get("source_fingerprint"),
        "test_source_fingerprint": test_source_fingerprint(root),
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
        templates = template_registry(runtime_root(root))
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
        contract_root / "active-rules.json",
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
        "preview": {
            "running": bool(active_safe and code and code.get("preview", {}).get("running")),
            "access_url": (
                code.get("preview", {}).get("access_url")
                if active_safe and code
                else None
            ),
        },
        "unfinished_run": candidate if candidate and candidate.get("status") != "closed" else None,
        "affected_ids": ids,
        "blocking_questions": [
            {"id": item["id"], "question": item["question"]}
            for item in blocking_questions
        ],
        "scaffold": {"ok": drift["ok"], "drift": drift["drift"]},
        "lifecycle_tests": lifecycle_tests,
        "init_state": init_state,
        "templates": templates,
        "active_rules": active_rules,
        "template_registry_error": template_error,
        "can_enter_next": prerequisites[stage],
        "journal": journal_status(root),
        "spec_work": {
            "active": (spec_work := spec_work_index(root)) is not None,
            **(spec_work or {}),
        },
        "spec_candidate": candidate_status(root),
        "publication_cleanup": publication_cleanup,
        "memory": memory_summary(root),
        "diagnostics": diagnostics,
    }
