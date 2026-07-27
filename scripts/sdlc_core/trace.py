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

from .schema_validation import validate_schema_instance

def scaffold(root: Path) -> dict[str, Any]:
    path = root / ".sdlc-pipeline" / "scaffold.json"
    data = read_json(path)
    validate_schema_instance(root, "scaffold.schema.json", data)
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
            root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            check=False,
        )
        entries = output.split("\0")
        paths: set[str] = set()
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if len(entry) < 4:
                continue
            status = entry[:2]
            paths.add(entry[3:].replace("\\", "/"))
            if "R" in status or "C" in status:
                # In ``-z`` mode rename/copy records carry the second path as
                # the following NUL-delimited field. The destination in the
                # status record is the path whose current contents matter.
                index += 1
        return sorted(paths)
    return sorted({line.replace("\\", "/") for line in output.splitlines() if line})


def changed_path_fingerprints(root: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for name in changed_paths(root):
        path = root / name
        entries.append({
            "path": name,
            "state": "file" if path.is_file() else "deleted_or_directory",
            "sha256": sha256_file(path) if path.is_file() else None,
        })
    return {"sha256": sha256_json(entries), "entries": entries}


def worktree_fingerprint(root: Path) -> dict[str, Any]:
    entries = [
        item for item in changed_path_fingerprints(root)["entries"]
        if not item["path"].startswith("docs/sdlc/test-results/")
        and not item["path"].startswith("docs/sdlc/bundles/")
        and item["path"] != "docs/sdlc/spec-current.json"
    ]
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


def validate_diff(
    root: Path,
    before: dict[str, Any] | list[str] | None = None,
) -> dict[str, Any]:
    contract = scaffold(root)
    current = changed_path_fingerprints(root)
    current_by_path = {item["path"]: item for item in current["entries"]}
    actual = sorted(current_by_path)
    if isinstance(before, dict):
        before_by_path = {
            item["path"]: item for item in before.get("entries", [])
        }
        actual = sorted(
            path for path in set(before_by_path) | set(current_by_path)
            if before_by_path.get(path) != current_by_path.get(path)
        )
    elif before is not None:
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
    return {
        "ok": True,
        "changed_paths": actual,
        "allowed_patterns": allowed_patterns,
        "fingerprints": [
            current_by_path.get(path, {"path": path, "state": "clean", "sha256": None})
            for path in actual
        ],

    }

def verify_extension_points(root: Path) -> dict[str, Any]:
    contract = scaffold(root)
    declared = {item["id"] for item in contract["extension_points"]}
    spec = load_current_spec(root)
    used = {item["extension_point"] for item in spec["design"]["items"]}
    unknown = sorted(used - declared)
    if unknown:
        raise SdlcError(f"设计引用未知 extension point: {unknown}")
    return {"ok": True, "used": sorted(used)}


def _file_evidence(root: Path, paths: Any) -> tuple[list[dict[str, Any]], list[str]]:
    evidence: list[dict[str, Any]] = []
    invalid: list[str] = []
    if not isinstance(paths, list):
        return evidence, [repr(paths)]
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            invalid.append(repr(raw))
            continue
        candidate = root / raw
        try:
            relative = candidate.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            invalid.append(raw)
            continue
        if not candidate.is_file():
            invalid.append(relative)
            continue
        evidence.append({
            "path": relative,
            "sha256": sha256_file(candidate),
            "size": candidate.stat().st_size,
        })
    return evidence, sorted(set(invalid))


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
            code_paths = code_map.get(design["id"], [])
            code_evidence, invalid_paths = _file_evidence(root, code_paths)
            raw_test_map = code_map.get("tests", {})
            if not isinstance(raw_test_map, dict):
                raw_test_map = {}
            test_paths = {
                item["id"]: raw_test_map.get(item["id"], [])
                for item in tests
            }
            test_evidence: dict[str, list[dict[str, Any]]] = {}
            for identifier, paths in test_paths.items():
                evidence, invalid = _file_evidence(root, paths)
                test_evidence[identifier] = evidence
                invalid_paths.extend(invalid)
            rows.append({
                "requirement_id": r_id,
                "design_id": design["id"],
                "code_paths": code_paths,
                "code_evidence": code_evidence,
                "test_ids": [item["id"] for item in tests],
                "test_paths": test_paths,
                "test_evidence": test_evidence,
                "invalid_paths": sorted(set(invalid_paths)),
            })
    incomplete = [
        row for row in rows
        if not row["code_paths"] or not row["test_ids"]
        or any(not paths for paths in row["test_paths"].values())
        or not row["code_evidence"] or row["invalid_paths"]
        or any(not paths for paths in row["test_evidence"].values())
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
