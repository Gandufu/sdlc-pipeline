from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import current_spec_hashes, load_current_spec
from .common import read_json, sha256_file, sha256_json, utc_now
from .failures import failure_fingerprint
from .journal import active_run, journal_root
from .layout import lifecycle_path, scaffold_path
from .records import read_compact_index, read_markdown_record


def delivery_memory(root: Path) -> dict[str, Any]:
    """Build a small, hash-invalidated memory from confirmed machine artifacts."""
    lifecycle = lifecycle_path(root)
    scaffold_file = scaffold_path(root)
    try:
        spec_hashes = current_spec_hashes(root)
    except Exception:
        spec_hashes = {}
    current_run = active_run(root)
    binding = {
        "lifecycle_sha256": (
            sha256_file(lifecycle) if lifecycle.is_file() else None
        ),
        "scaffold_sha256": (
            sha256_file(scaffold_file) if scaffold_file.is_file() else None
        ),
        "spec_hashes": spec_hashes,
        "journal_updated_at": (current_run or {}).get("updated_at"),
    }

    lifecycle_contract = read_json(lifecycle, required=False) or {}
    scaffold = read_json(scaffold_file, required=False) or {}
    active_rules = read_json(
        root / ".sdlc-pipeline" / "contracts" / "active-rules.json",
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
            "project_type": lifecycle_contract.get("project_type"),
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
    directory = journal_root(root)
    if not directory.is_dir():
        return []
    lessons: dict[str, dict[str, str]] = {}
    for run_dir in sorted(directory.glob("RUN-*"))[-20:]:
        attempts = []
        for path in sorted((run_dir / "attempts").glob("*/*.json")):
            value = read_compact_index(path, required=False)
            if value:
                attempts.append(value)
        failures: dict[tuple[str, str], dict[str, Any]] = {}
        for attempt in sorted(attempts, key=lambda item: item["attempt_id"]):
            key = (attempt.get("phase", ""), attempt.get("step", ""))
            if attempt.get("state") == "failed" and attempt.get("error_ref"):
                failure_record = read_markdown_record(
                    root / attempt["error_ref"], required=False
                ) or {}
                message = failure_record.get("message")
                if isinstance(message, str):
                    failures[key] = {**attempt, "message": message}
            elif attempt.get("state") == "succeeded" and key in failures:
                failed = failures.pop(key)
                fingerprint = failure_fingerprint(failed["message"])
                lessons[fingerprint["fingerprint"]] = {
                    "class": fingerprint["class"],
                    "fingerprint": fingerprint["fingerprint"],
                    "phase": key[0],
                    "step": key[1],
                    "resolved_by_input_hash": attempt.get("input_hash", ""),
                }
    return [lessons[key] for key in sorted(lessons)]
