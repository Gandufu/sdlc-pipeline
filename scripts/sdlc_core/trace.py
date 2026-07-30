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
from .layout import lifecycle_path, scaffold_path

from .schema_validation import validate_schema_instance

TOOLING_CONFIG_PATHS = [
    "vitest.config.ts",
    "vitest.config.js",
    "vitest.config.mts",
    "vitest.config.mjs",
    "eslint.config.mjs",
    "eslint.config.js",
    "eslint.config.cjs",
    "eslint.config.ts",
]

def scaffold(root: Path) -> dict[str, Any]:
    path = scaffold_path(root)
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
    lifecycle = lifecycle_path(root)
    drift: list[str] = []
    issues: list[dict[str, Any]] = []
    matches, actual = _hash_matches(lifecycle, contract["lifecycle_hash"])
    if not matches:
        drift.append(".sdlc-pipeline/contracts/lifecycle.json")
        issues.append({
            "path": ".sdlc-pipeline/contracts/lifecycle.json",
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
        if _is_pipeline_managed_path(name):
            continue
        path = root / name
        entries.append({
            "path": name,
            "state": "file" if path.is_file() else "deleted_or_directory",
            "sha256": sha256_file(path) if path.is_file() else None,
        })
    return {"sha256": sha256_json(entries), "entries": entries}


def _is_pipeline_managed_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return (
        normalized.startswith((".opencode/", ".sdlc-pipeline/", "docs/sdlc/"))
        or normalized in {"AGENTS.md", "opencode.json"}
    )


def worktree_fingerprint(root: Path) -> dict[str, Any]:
    entries = _delivery_entries(root)
    return {"sha256": sha256_json(entries), "entries": entries}


def implementation_fingerprint(root: Path) -> dict[str, Any]:
    """Fingerprint production/tooling changes while excluding test sources."""
    entries = [
        item for item in _delivery_entries(root)
        if not item["path"].startswith(("tests/", "test/"))
    ]
    return {"sha256": sha256_json(entries), "entries": entries}


def test_source_fingerprint(root: Path) -> dict[str, Any]:
    """Fingerprint the complete project test tree independently of code evidence."""
    entries: list[dict[str, Any]] = []
    for folder in ("tests", "test"):
        directory = root / folder
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if (
                not path.is_file()
                or any(
                    part in {"node_modules", "__pycache__", ".cache"}
                    for part in path.parts
                )
                or path.suffix == ".pyc"
            ):
                continue
            entries.append({
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
            })
    return {"sha256": sha256_json(entries), "entries": entries}


def _delivery_entries(root: Path) -> list[dict[str, Any]]:
    return [
        item for item in changed_path_fingerprints(root)["entries"]
        if not item["path"].startswith("docs/sdlc/test-results/")
        and not item["path"].startswith("docs/sdlc/baselines/")
        and item["path"] != "docs/sdlc/current.json"
        and not item["path"].startswith(".sdlc-pipeline/state/")
        and not item["path"].startswith(".sdlc-pipeline/work/")
        and not item["path"].startswith(".sdlc-pipeline/evidence/")
    ]


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


def allowed_change_paths(root: Path) -> list[str]:
    contract = scaffold(root)
    return sorted(
        set(contract["allowed_paths"])
        | set(allowed_design_paths(root))
        | set(TOOLING_CONFIG_PATHS)
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
            if not _is_pipeline_managed_path(item["path"])
        }
        actual = sorted(
            path for path in set(before_by_path) | set(current_by_path)
            if before_by_path.get(path) != current_by_path.get(path)
        )
    elif before is not None:
        actual = sorted(set(actual) - set(before))
    protected = [path for path in actual if matches_path(path, contract["protected_paths"])]
    allowed_patterns = allowed_change_paths(root)
    outside = [
        path for path in actual
        if not matches_path(path, allowed_patterns)
        and not path.startswith("docs/sdlc/")
        and not path.startswith(".sdlc-pipeline/state/")
        and not path.startswith(".sdlc-pipeline/work/")
        and not path.startswith(".sdlc-pipeline/evidence/")
    ]
    return {
        "ok": True,
        "changed_paths": actual,
        "allowed_patterns": allowed_patterns,
        "scope_observations": {
            "protected_paths": protected,
            "outside_declared_scope": outside,
        },
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
