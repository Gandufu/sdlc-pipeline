from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

from .artifacts import load_current_spec
from .common import (
    SdlcError,
    git,
    read_json,
    sha256_contract_file,
    sha256_file,
    sha256_json,
)


def scaffold(root: Path) -> dict[str, Any]:
    path = root / ".sdlc-pipeline" / "scaffold.json"
    data = read_json(path)
    required = {
        "schema_version", "template_id", "template_version", "protected_paths",
        "extension_points", "allowed_paths", "lifecycle_hash", "key_files",
    }
    missing = sorted(required - set(data))
    if missing:
        raise SdlcError(f"scaffold.json 缺少字段: {', '.join(missing)}")
    return data


def _hash_matches(path: Path, expected: str) -> tuple[bool, str | None]:
    if not path.exists():
        return False, None
    actual = sha256_file(path)
    canonical = sha256_contract_file(path)
    return expected in {actual, canonical}, actual


def verify_scaffold(root: Path) -> dict[str, Any]:
    contract = scaffold(root)
    lifecycle = root / ".sdlc-pipeline" / "lifecycle.json"
    drift: list[str] = []
    issues: list[dict[str, Any]] = []
    matches, actual = _hash_matches(lifecycle, contract["lifecycle_hash"])
    if not matches:
        drift.append(".sdlc-pipeline/lifecycle.json")
        issues.append({
            "path": ".sdlc-pipeline/lifecycle.json",
            "reason": "missing" if actual is None else "hash_mismatch",
            "expected_sha256": contract["lifecycle_hash"],
            "actual_sha256": actual,
        })
    for item in contract["key_files"]:
        path = root / item["path"]
        matches, actual = _hash_matches(path, item["sha256"])
        if not matches:
            drift.append(item["path"])
            issues.append({
                "path": item["path"],
                "reason": "missing" if actual is None else "hash_mismatch",
                "expected_sha256": item["sha256"],
                "actual_sha256": actual,
            })
    return {
        "ok": not drift,
        "drift": sorted(set(drift)),
        "issues": issues,
        "contract": contract,
    }


def changed_paths(root: Path, base: str | None = None) -> list[str]:
    if base:
        output = git(root, "diff", "--name-only", f"{base}...HEAD", check=False)
    else:
        output = git(
            root, "status", "--short", "--untracked-files=all", check=False
        )
        return sorted({line[3:].replace("\\", "/") for line in output.splitlines() if len(line) > 3})
    return sorted({line.replace("\\", "/") for line in output.splitlines() if line})


def worktree_fingerprint(root: Path) -> dict[str, Any]:
    entries = []
    for name in changed_paths(root):
        path = root / name
        entries.append({
            "path": name,
            "state": "file" if path.is_file() else "deleted_or_directory",
            "sha256": sha256_file(path) if path.is_file() else None,
        })
    return {"sha256": sha256_json(entries), "entries": entries}


def matches_path(path: str, patterns: list[str]) -> bool:
    return any(
        path == pattern.rstrip("/") or path.startswith(pattern.rstrip("/") + "/")
        or fnmatch.fnmatch(path, pattern)
        for pattern in patterns
    )


def allowed_design_paths(root: Path) -> list[str]:
    spec = load_current_spec(root)
    return sorted(
        {
            pattern
            for item in spec["design"]["items"]
            for pattern in item["allowed_paths"]
        }
    )


def validate_diff(root: Path, before: list[str] | None = None) -> dict[str, Any]:
    contract = scaffold(root)
    actual = changed_paths(root)
    if before is not None:
        actual = sorted(set(actual) - set(before))
    protected = [path for path in actual if matches_path(path, contract["protected_paths"])]
    allowed_patterns = sorted(
        set(contract["allowed_paths"]) | set(allowed_design_paths(root))
    )
    outside = [
        path for path in actual
        if not matches_path(path, allowed_patterns)
        and not path.startswith("docs/sdlc/")
        and not path.startswith(".sdlc-pipeline/runs/")
    ]
    if protected:
        raise SdlcError(f"修改了 protected path: {protected}")
    if outside:
        raise SdlcError(f"修改超出设计/脚手架允许范围: {outside}")
    return {"ok": True, "changed_paths": actual, "allowed_patterns": allowed_patterns}


def verify_extension_points(root: Path) -> dict[str, Any]:
    contract = scaffold(root)
    declared = {item["id"] for item in contract["extension_points"]}
    spec = load_current_spec(root)
    used = {item["extension_point"] for item in spec["design"]["items"]}
    unknown = sorted(used - declared)
    if unknown:
        raise SdlcError(f"设计引用未知 extension point: {unknown}")
    return {"ok": True, "used": sorted(used)}


def trace_matrix(root: Path, code_map: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = load_current_spec(root)
    code_map = code_map or {}
    rows = []
    for requirement in spec["requirements"]["items"]:
        r_id = requirement["id"]
        designs = [
            item for item in spec["design"]["items"]
            if r_id in item["requirement_ids"]
        ]
        for design in designs:
            tests = [
                item for item in spec["test_plan"]["items"]
                if r_id in item["requirement_ids"] and design["id"] in item["design_ids"]
            ]
            rows.append({
                "requirement_id": r_id,
                "design_id": design["id"],
                "code_paths": code_map.get(design["id"], []),
                "test_ids": [item["id"] for item in tests],
                "test_paths": {
                    item["id"]: code_map.get("tests", {}).get(item["id"], [])
                    for item in tests
                },
            })
    incomplete = [
        row for row in rows
        if not row["code_paths"] or not row["test_ids"]
        or any(not paths for paths in row["test_paths"].values())
    ]
    return {"ok": not incomplete, "rows": rows, "incomplete": incomplete}


def incremental_eligibility(root: Path) -> dict[str, Any]:
    drift = verify_scaffold(root)
    reasons: list[str] = []
    if not drift["ok"]:
        reasons.append("scaffold_or_lifecycle_drift")
    version_root = root / "docs" / "sdlc" / "versions"
    manifests = sorted(version_root.glob("V????/manifest.json")) if version_root.exists() else []
    if not manifests:
        reasons.append("missing_parent_manifest")
    spec = load_current_spec(root)
    flags = spec["requirements"].get("change_flags", {})
    for key in (
        "public_interface", "dependency", "data_model", "security",
        "lifecycle", "protected_path",
    ):
        if flags.get(key):
            reasons.append(key)
    return {"eligible": not reasons, "reasons": reasons}
