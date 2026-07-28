from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_store import current_baseline
from .artifacts import load_test_results
from .common import SdlcError, git, read_json, sha256_file, sha256_json
from .layout import evidence_root, scaffold_path
from .records import read_markdown_record, write_markdown_record
from .schema_validation import validate_schema_instance


def build_delivery_trace(
    root: Path,
    *,
    changed_files: list[str],
    test_results_path: str,
) -> dict[str, Any]:
    selected = current_baseline(root)
    if not selected:
        raise SdlcError("没有已发布 spec baseline")
    baseline, manifest = selected
    requirements = _documents(baseline, manifest, "requirements")
    designs = _documents(baseline, manifest, "designs")
    verification = _documents(baseline, manifest, "verification")
    scaffold = read_json(scaffold_path(root))
    extension_paths = {
        item["id"]: item["path"].rstrip("/")
        for item in scaffold.get("extension_points", [])
    }
    code_files = [
        path
        for path in sorted(set(changed_files))
        if not path.startswith(("tests/", "test/", "docs/", ".sdlc-pipeline/"))
    ]
    evidence: dict[str, dict[str, str]] = {}
    for relative in code_files:
        path = root / relative
        try:
            normalized = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError as exc:
            raise SdlcError(f"changed file 越出项目: {relative}") from exc
        if not path.is_file():
            continue
        evidence[normalized] = {"path": normalized, "sha256": sha256_file(path)}

    design_files: dict[str, set[str]] = {}
    for design in designs.values():
        prefixes = [extension_paths[item] for item in design["extension_points"]]
        design_files[design["id"]] = {
            path
            for path in evidence
            if any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)
        }
    file_owners = {
        path: {
            identifier
            for identifier, paths in design_files.items()
            if path in paths
        }
        for path in evidence
    }

    results_path = root / test_results_path
    try:
        relative_results = results_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise SdlcError("test results 路径越出项目") from exc
    results = load_test_results(root, test_results_path)
    passed = {
        item["id"]
        for item in results.get("results", [])
        if item.get("status") == "pass"
    }
    commit = git(root, "rev-parse", "HEAD", check=False)
    rows: list[dict[str, Any]] = []
    incomplete: list[str] = []
    for requirement in requirements.values():
        requirement_designs = [
            design
            for design in designs.values()
            if requirement["id"] in design["requirement_ids"]
        ]
        design_ids = [item["id"] for item in requirement_designs]
        paths = sorted({
            path
            for identifier in design_ids
            for path in design_files.get(identifier, set())
        })
        tests = [
            item
            for item in verification.values()
            if requirement["id"] in item["requirement_ids"] and item["mandatory"]
        ]
        verification_evidence = [
            {
                "test_id": item["id"],
                "selector": item["selector"],
                "result_ref": f"{relative_results}#{item['id']}",
                "precision": "direct",
            }
            for item in tests
            if item["id"] in passed and item.get("selector")
        ]
        precision = (
            "shared"
            if any(len(file_owners[path]) > 1 for path in paths)
            else "scoped"
        )
        row = {
            "requirement_id": requirement["id"],
            "design_ids": design_ids,
            "changed_files": [evidence[path] for path in paths],
            "verification": verification_evidence,
            "commits": [commit] if commit else [],
            "precision": precision,
        }
        rows.append(row)
        if not design_ids:
            incomplete.append(f"{requirement['id']}:missing_design")
        if not paths:
            incomplete.append(f"{requirement['id']}:missing_changed_files")
        if len(verification_evidence) != len(tests):
            incomplete.append(f"{requirement['id']}:missing_verification_result")
    uncovered_designs = sorted(
        identifier for identifier, paths in design_files.items() if not paths
    )
    incomplete += [f"{identifier}:missing_changed_files" for identifier in uncovered_designs]
    trace = {
        "schema_version": "3.0",
        "baseline_id": manifest["baseline_id"],
        "source_fingerprint": sha256_json(list(evidence.values())),
        "rows": rows,
        "ok": not incomplete,
        "incomplete": sorted(set(incomplete)),
    }
    validate_schema_instance(
        root, "artifacts/delivery-trace.schema.json", trace
    )
    write_markdown_record(
        evidence_root(root) / "delivery-trace.md",
        trace,
        title="Delivery trace",
        summary_lines=[
            f"- Baseline: `{manifest['baseline_id']}`",
            f"- Complete: `{str(trace['ok']).lower()}`",
        ],
    )
    return trace


def _documents(
    baseline: Path, manifest: dict[str, Any], folder: str
) -> dict[str, dict[str, Any]]:
    return {
        record["id"]: read_markdown_record(baseline / record["content_ref"])
        for record in manifest[folder]
    }
