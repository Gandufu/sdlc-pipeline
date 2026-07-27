from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from typing import Any

from .artifacts import load_current_spec, require_code_ready
from .common import SdlcError, read_json, sha256_file, utc_now, write_json
from .trace import changed_path_fingerprints, validate_diff, verify_extension_points

from .schema_validation import validate_schema_instance

MAX_CONTEXT_RESOURCES = 1_000


def validate_write_path(root: Path, path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise SdlcError("禁止写入项目之外的路径") from exc
    from .trace import allowed_design_paths, matches_path, scaffold

    contract = scaffold(root)
    if matches_path(relative, contract["protected_paths"]):
        raise SdlcError(f"禁止修改 protected path: {relative}")
    allowed = sorted(set(contract["allowed_paths"]) | set(allowed_design_paths(root)))
    if not matches_path(relative, allowed):
        raise SdlcError(f"路径不在设计/脚手架允许范围: {relative}")
    return {"ok": True, "path": relative}


def _validate_mapping_paths(
    root: Path,
    mapping: dict[str, Any],
    label: str,
) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
    from .trace import allowed_design_paths, matches_path, scaffold

    contract = scaffold(root)
    allowed = sorted(set(contract["allowed_paths"]) | set(allowed_design_paths(root)))
    normalized: dict[str, list[str]] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for identifier, raw_paths in mapping.items():
        if (
            not isinstance(raw_paths, list)
            or not raw_paths
            or any(not isinstance(item, str) or not item.strip() for item in raw_paths)
        ):
            raise SdlcError(f"{label}.{identifier} 必须是非空路径数组")
        paths: list[str] = []
        for raw in raw_paths:
            candidate = root / raw
            try:
                relative = candidate.resolve().relative_to(root.resolve()).as_posix()
            except ValueError as exc:
                raise SdlcError(f"{label}.{identifier} 路径越出项目: {raw}") from exc
            if not candidate.is_file():
                raise SdlcError(f"{label}.{identifier} 引用的文件不存在: {relative}")
            if matches_path(relative, contract["protected_paths"]):
                raise SdlcError(f"{label}.{identifier} 引用了 protected path: {relative}")
            if not matches_path(relative, allowed):
                raise SdlcError(f"{label}.{identifier} 路径不在允许范围: {relative}")
            if relative not in paths:
                paths.append(relative)
                evidence[relative] = {
                    "path": relative,
                    "sha256": sha256_file(candidate),
                    "size": candidate.stat().st_size,
                }
        normalized[identifier] = sorted(paths)
    return normalized, evidence


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    candidates = [text]
    candidates += re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    for candidate in reversed(candidates):
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    raise SdlcError("subagent 输出中没有可解析的 JSON handoff")


def _context_resources(root: Path) -> list[dict[str, Any]]:
    spec = load_current_spec(root)
    candidates: dict[str, tuple[int, str]] = {
        "docs/sdlc/current/requirements.json": (1, "requirement view"),
        "docs/sdlc/current/design.json": (1, "design view"),
        "docs/sdlc/current/test-plan.json": (1, "verification view"),
        ".sdlc-pipeline/lifecycle.json": (2, "lifecycle contract"),
        ".sdlc-pipeline/scaffold.json": (2, "scaffold contract"),
    }
    feature_contract = root / "docs/sdlc/current/feature-contract.json"
    if feature_contract.is_file():
        candidates["docs/sdlc/current/feature-contract.json"] = (
            1, "authoritative Feature Contract"
        )
    active_rules = read_json(
        root / ".sdlc-pipeline" / "rules" / "active.json",
        required=False,
    ) or {"rules": []}
    for rule in active_rules.get("rules", []):
        path = rule.get("path")
        if (
            not isinstance(path, str)
            or not path.startswith(".sdlc-pipeline/rules/")
            or not path.endswith(".md")
        ):
            raise SdlcError(f"active rule 路径非法: {path!r}")
        rule_path = root / path
        try:
            rule_path.resolve().relative_to(
                (root / ".sdlc-pipeline" / "rules").resolve()
            )
        except ValueError as exc:
            raise SdlcError(f"active rule 越出规则目录: {path}") from exc
        if not rule_path.is_file() or sha256_file(rule_path) != rule.get("sha256"):
            raise SdlcError(f"active rule 缺失或 hash 漂移: {path}")
        candidates[path] = (2, "active guidance; read when touched file matches")
    if (root / "docs" / "existing-framework.md").exists():
        candidates["docs/existing-framework.md"] = (2, "existing framework index")
    for item in spec["design"]["items"]:
        for pattern in item["allowed_paths"]:
            if "*" not in pattern:
                path = root / pattern
                if path.is_file():
                    candidates[pattern] = (2, "design-allowed implementation candidate")
                elif path.is_dir():
                    for candidate in path.rglob("*"):
                        if candidate.is_file() and candidate.stat().st_size <= 80_000:
                            candidates[
                                candidate.relative_to(root).as_posix()
                            ] = (2, "design-allowed implementation candidate")
    resources = []
    for name, (tier, reason) in sorted(
        candidates.items(), key=lambda item: (item[1][0], item[0])
    )[:MAX_CONTEXT_RESOURCES]:
        path = root / name
        if not path.is_file():
            continue
        resources.append({
            "path": name,
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
            "tier": tier,
            "reason": reason,
        })
    return resources


def build_context_pack(root: Path, role: str) -> dict[str, Any]:
    from .memory import delivery_memory

    spec = load_current_spec(root)
    requirements = spec["requirements"]["items"]
    designs = spec["design"]["items"]
    tests = spec["test_plan"]["items"]
    brief = {
        "requirement_ids": [item["id"] for item in requirements],
        "goals": [
            {"id": item["id"], "title": item["title"], "description": item["description"]}
            for item in requirements
        ],
        "design_ids": [item["id"] for item in designs],
        "extension_points": sorted({
            item["extension_point"] for item in designs
        }),
        "allowed_paths": sorted({
            path for item in designs for path in item["allowed_paths"]
        }),
        "test_ids": [item["id"] for item in tests],
        "acceptance": [
            criterion
            for item in requirements
            for criterion in item["acceptance_criteria"]
        ],
        "confirmed_decisions": delivery_memory(root)["decisions"],
    }
    pack = {
        "schema_version": "1.0",
        "mode": "progressive",
        "role": role,
        "brief": brief,
        "resources": _context_resources(root),
        "instruction": (
            "先使用 brief；只在实现需要时按 resources 路径读取对应文件。"
            "tier=1 是功能契约视图，tier=2 是实现或规则候选。"
        ),
    }
    directory = root / ".sdlc-pipeline" / "runs" / "context"
    path = directory / f"{role}-manifest.json"
    write_json(path, pack)
    characters = len(json.dumps(pack, ensure_ascii=False))
    return {
        "paths": [path.relative_to(root).as_posix()],
        "parts": 1,
        "characters": characters,
        "repeated_chars": 0,
        "resource_count": len(pack["resources"]),
        "mode": "progressive",
    }


def before_task(root: Path, role: str) -> dict[str, Any]:
    if role != "coder":
        raise SdlcError(f"不允许的 subagent: {role}")
    from .status import status

    current = status(root)
    if role == "coder" and not (
        current["gates"]["init"] and current["gates"]["spec"]
    ):
        raise SdlcError("coder 门禁要求 init 与 spec 均通过")
    if role == "coder":
        require_code_ready(load_current_spec(root))
    verify_extension_points(root)
    before_path = root / ".sdlc-pipeline" / "runs" / f"{role}-before.json"
    spec_pointer = read_json(
        root / "docs" / "sdlc" / "spec-current.json",
        required=False,
    ) or {}
    previous = read_json(before_path, required=False)
    reuse_baseline = (
        role == "coder"
        and previous is not None
        and previous.get("spec_bundle_id") == spec_pointer.get("bundle_id")
        and not current["gates"]["code"]
    )
    if not reuse_baseline:
        before = changed_path_fingerprints(root)
        write_json(before_path, {
            "created_at": utc_now(),
            "spec_bundle_id": spec_pointer.get("bundle_id"),
            "changed_paths": [item["path"] for item in before["entries"]],
            "worktree": before,
        })
    context = build_context_pack(root, role)
    from .runs import record_tokens

    record_tokens(
        root,
        role,
        repeated_chars=context["repeated_chars"],
        source="context-pack",
    )
    role_instruction = (
        "coder 只实现当前 Feature Slice 并运行聚焦检查；"
        "禁止调用完整 compile/restart/health/test，权威交付验证只由 Core 执行。"
    )
    return {
        "ok": True,
        "role": role,
        "baseline": "reused" if reuse_baseline else "created",
        "context_pack": context,
        "instruction": (
            "先读取 context manifest 的 brief，再按需读取 resources，禁止预读全部文件。"
            + role_instruction
            + "最终只返回约定 JSON handoff。"
        ),
    }


def validate_coder_handoff(root: Path, text: str) -> dict[str, Any]:
    value = _extract_json(text)
    validate_schema_instance(root, "handoff.schema.json", value)
    before = read_json(root / ".sdlc-pipeline" / "runs" / "coder-before.json")
    diff = validate_diff(root, before.get("worktree", before.get("changed_paths", [])))
    actual = sorted(set(diff["changed_paths"]))
    spec = load_current_spec(root)
    code_paths = [
        path for path in actual
        if (root / path).is_file()
        and not path.startswith("tests/")
        and not path.startswith("test/")
        and not path.startswith("docs/sdlc/")
        and not path.startswith(".sdlc-pipeline/")
    ]
    test_paths = [
        path for path in actual
        if (root / path).is_file()
        and (path.startswith("tests/") or path.startswith("test/"))
    ]
    if not test_paths:
        test_paths = sorted(
            path.relative_to(root).as_posix()
            for directory in (root / "tests", root / "test")
            if directory.is_dir()
            for path in directory.rglob("*")
            if path.is_file()
        )
    design_mapping = {
        item["id"]: [
            path for path in code_paths
            if any(
                path == allowed.rstrip("/")
                or path.startswith(allowed.rstrip("/") + "/")
                or fnmatch.fnmatch(path, allowed)
                for allowed in item["allowed_paths"]
            )
        ]
        for item in spec["design"]["items"]
    }
    missing_design = sorted(
        identifier for identifier, paths in design_mapping.items() if not paths
    )
    if missing_design:
        raise SdlcError(f"Feature 设计没有代码证据: {missing_design}")
    test_mapping = {
        item["id"]: list(test_paths)
        for item in spec["test_plan"]["items"]
    }
    design_mapping, design_evidence = _validate_mapping_paths(
        root, design_mapping, "design_to_code"
    )
    test_evidence: dict[str, Any] = {}
    if test_paths:
        test_mapping, test_evidence = _validate_mapping_paths(
            root, test_mapping, "test_to_files"
        )
    value["design_to_code"] = design_mapping
    value["test_to_files"] = test_mapping
    value["changed_files"] = actual
    value["mapping_evidence"] = {
        "design": design_evidence,
        "tests": test_evidence,
    }
    value["validated_at"] = utc_now()
    value["compiled_claim_ignored"] = True
    write_json(root / ".sdlc-pipeline" / "runs" / "coder-handoff.json", value)
    return {"ok": True, "handoff": value, "diff": diff}


def after_task(root: Path, role: str, output: str) -> dict[str, Any]:
    if role == "coder":
        return validate_coder_handoff(root, output)
    raise SdlcError(f"不允许的 subagent: {role}")
