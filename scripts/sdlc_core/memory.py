from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import current_spec_hashes, load_current_spec
from .common import read_json, sha256_file, sha256_json, utc_now, write_json
from .failures import failure_fingerprint


def delivery_memory(root: Path) -> dict[str, Any]:
    """Build a small, hash-invalidated memory from confirmed machine artifacts."""
    contract_root = root / ".sdlc-pipeline"
    lifecycle_path = contract_root / "lifecycle.json"
    scaffold_path = contract_root / "scaffold.json"
    try:
        spec_hashes = current_spec_hashes(root)
    except Exception:
        spec_hashes = {}
    journal = read_json(
        contract_root / "runs" / "journal" / "active.json",
        required=False,
    ) or {}
    active_run = None
    if journal.get("run_id"):
        active_run = read_json(
            contract_root / "runs" / "journal"
            / journal["run_id"] / "run.json",
            required=False,
        )
    binding = {
        "lifecycle_sha256": (
            sha256_file(lifecycle_path) if lifecycle_path.is_file() else None
        ),
        "scaffold_sha256": (
            sha256_file(scaffold_path) if scaffold_path.is_file() else None
        ),
        "spec_hashes": spec_hashes,
        "journal_updated_at": (active_run or {}).get("updated_at"),
    }
    path = contract_root / "runs" / "memory" / "delivery-memory.json"
    cached = read_json(path, required=False)
    if cached and cached.get("binding") == binding:
        return {**cached, "cached": True}

    lifecycle = read_json(lifecycle_path, required=False) or {}
    scaffold = read_json(scaffold_path, required=False) or {}
    active_rules = read_json(
        contract_root / "rules" / "active.json",
        required=False,
    ) or {"rules": []}
    try:
        spec = load_current_spec(root)
    except Exception:
        decisions: list[str] = []
    else:
        decisions = list(dict.fromkeys(
            item
            for item in spec["requirements"]["analysis"].get("decisions", [])
            if isinstance(item, str) and item.strip()
        ))
    memory = {
        "schema_version": "1.0",
        "binding": binding,
        "facts": {
            "project_type": lifecycle.get("project_type"),
            "template_id": scaffold.get("template_id"),
            "template_version": scaffold.get("template_version"),
            "extension_points": scaffold.get("extension_points", []),
            "active_rule_ids": [
                item.get("id") or item.get("name") or item.get("path")
                for item in active_rules.get("rules", [])
            ],
        },
        "decisions": decisions,
        "resolved_failures": _resolved_failures(root),
        "created_at": utc_now(),
        "cached": False,
    }
    memory["memory_id"] = sha256_json({
        "binding": binding,
        "facts": memory["facts"],
        "decisions": decisions,
        "resolved_failures": memory["resolved_failures"],
    })[:16]
    write_json(path, memory)
    return memory


def memory_summary(root: Path) -> dict[str, Any]:
    memory = delivery_memory(root)
    return {
        "memory_id": memory["memory_id"],
        "binding": memory["binding"],
        "fact_count": sum(
            1 for value in memory["facts"].values() if value not in (None, [], {})
        ),
        "decision_count": len(memory["decisions"]),
        "resolved_failure_count": len(memory["resolved_failures"]),
        "cached": memory["cached"],
    }


def _resolved_failures(root: Path) -> list[dict[str, str]]:
    directory = root / ".sdlc-pipeline" / "runs" / "journal"
    if not directory.is_dir():
        return []
    lessons: dict[str, dict[str, str]] = {}
    for run_dir in sorted(directory.glob("RUN-*"))[-20:]:
        attempts = []
        for path in sorted((run_dir / "attempts").glob("*/*.json")):
            value = read_json(path, required=False)
            if value:
                attempts.append(value)
        failures: dict[tuple[str, str], dict[str, Any]] = {}
        for attempt in sorted(attempts, key=lambda item: item["attempt_id"]):
            key = (attempt.get("phase", ""), attempt.get("step", ""))
            if attempt.get("state") == "failed" and attempt.get("error"):
                failures[key] = attempt
            elif attempt.get("state") == "succeeded" and key in failures:
                failed = failures.pop(key)
                fingerprint = failure_fingerprint(failed["error"])
                lessons[fingerprint["fingerprint"]] = {
                    "class": fingerprint["class"],
                    "fingerprint": fingerprint["fingerprint"],
                    "phase": key[0],
                    "step": key[1],
                    "resolved_by_input_hash": attempt.get("input_hash", ""),
                }
    return [lessons[key] for key in sorted(lessons)]
