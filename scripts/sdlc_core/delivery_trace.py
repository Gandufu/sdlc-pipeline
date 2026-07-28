from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_store import current_bundle
from .common import SdlcError, git, read_json, sha256_file, sha256_json, write_json
from .schema_validation import validate_schema_instance


def build_delivery_trace(
    root: Path,
    *,
    changed_files: list[str],
    test_results_path: str,
) -> dict[str, Any]:
    selected = current_bundle(root, "spec")
    if not selected:
        raise SdlcError("没有已发布 spec bundle")
    bundle, manifest = selected
    metadata = manifest.get("metadata", {})
    if metadata.get("schema_version") != "2.0":
        raise SdlcError("Delivery Trace v2 只适用于 Schema v2 spec bundle")
    requirements = _documents(bundle, "requirements")
    designs = _documents(bundle, "designs")
    verification = _documents(bundle, "verification")
    scaffold = read_json(root / ".sdlc-pipeline" / "scaffold.json")
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
    results = read_json(results_path)
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
        "schema_version": "2.0",
        "spec_bundle_id": manifest["bundle_id"],
        "source_fingerprint": sha256_json(list(evidence.values())),
        "rows": rows,
        "ok": not incomplete,
        "incomplete": sorted(set(incomplete)),
    }
    validate_schema_instance(root, "v2/delivery-trace.schema.json", trace)
    write_json(root / ".sdlc-pipeline" / "runs" / "delivery-trace.json", trace)
    return trace


def _documents(bundle: Path, folder: str) -> dict[str, dict[str, Any]]:
    directory = bundle / folder
    if not directory.is_dir():
        raise SdlcError(f"Schema v2 spec bundle 缺少 {folder}/")
    return {
        path.stem: read_json(path)
        for path in sorted(directory.glob("*.json"))
    }
