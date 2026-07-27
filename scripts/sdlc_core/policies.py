from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

from .common import SdlcError, git, read_json, sha256_file
from .schema_validation import validate_schema_instance


def active_policy_packs(root: Path) -> list[dict[str, Any]]:
    active = read_json(
        root / ".sdlc-pipeline" / "rules" / "active.json",
        required=False,
    ) or {"rules": []}
    packs = []
    for rule in active.get("rules", []):
        path = rule.get("policy_path")
        expected = rule.get("policy_sha256")
        if not path:
            continue
        candidate = root / path
        if not candidate.is_file() or sha256_file(candidate) != expected:
            raise SdlcError(f"active policy 缺失或 hash 漂移: {path}")
        pack = read_json(candidate)
        validate_schema_instance(root, "rule-policy.schema.json", pack)
        if pack["rule_id"] != rule["id"]:
            raise SdlcError(f"active policy rule_id 不匹配: {path}")
        packs.append(pack)
    return packs


def evaluate_hard_policies(root: Path) -> dict[str, Any]:
    violations = []
    evaluated = []
    output = git(
        root, "status", "--short", "--untracked-files=all", check=False
    )
    paths = sorted({
        line[3:].replace("\\", "/")
        for line in output.splitlines()
        if len(line) > 3
    })
    for pack in active_policy_packs(root):
        for invariant in pack.get("hard_invariants", []):
            identifier = f"{pack['rule_id']}:{invariant['id']}"
            evaluated.append(identifier)
            kind = invariant["kind"]
            if kind == "forbidden_regex":
                pattern = re.compile(invariant["pattern"])
                for relative in paths:
                    candidate = root / relative
                    if (
                        candidate.is_file()
                        and _matches_any(relative, invariant["paths"])
                        and candidate.stat().st_size <= invariant.get("max_bytes", 500_000)
                    ):
                        content = candidate.read_text(
                            encoding="utf-8", errors="replace"
                        )
                        match = pattern.search(content)
                        if match:
                            violations.append({
                                "policy": identifier,
                                "path": relative,
                                "kind": kind,
                                "detail": match.group(0)[:200],
                            })
            elif kind == "required_file":
                for relative in invariant["paths"]:
                    if not (root / relative).is_file():
                        violations.append({
                            "policy": identifier,
                            "path": relative,
                            "kind": kind,
                            "detail": "missing",
                        })
            else:
                raise SdlcError(f"未知 hard policy kind: {kind}")
    report = {
        "ok": not violations,
        "evaluated": evaluated,
        "violations": violations,
    }
    return report


def executable_verifiers(root: Path, phase: str) -> list[dict[str, Any]]:
    return [
        {"rule_id": pack["rule_id"], **verifier}
        for pack in active_policy_packs(root)
        for verifier in pack.get("executable_verifiers", [])
        if verifier["phase"] == phase
    ]
def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(
        fnmatch.fnmatch(path, pattern)
        or path == pattern.rstrip("/")
        or path.startswith(pattern.rstrip("/") + "/")
        for pattern in patterns
    )
