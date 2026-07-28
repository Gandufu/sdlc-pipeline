from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from typing import Any

from .artifacts import load_current_spec, require_code_ready
from .common import SdlcError, read_json, sha256_file, utc_now, write_json
from .trace import (
    TOOLING_CONFIG_PATHS,
    changed_path_fingerprints,
    validate_diff,
    verify_extension_points,
)

from .schema_validation import validate_schema_instance

MAX_CONTEXT_RESOURCES = 10
MAX_IMPLEMENTATION_RESOURCES = 6


def validate_write_path(root: Path, path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise SdlcError("禁止写入项目之外的路径") from exc
    from .trace import allowed_change_paths, matches_path, scaffold

    contract = scaffold(root)
    if matches_path(relative, contract["protected_paths"]):
        raise SdlcError(f"禁止修改 protected path: {relative}")
    allowed = allowed_change_paths(root)
    if not matches_path(relative, allowed):
        raise SdlcError(f"路径不在设计/脚手架允许范围: {relative}")
    return {"ok": True, "path": relative}


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
        "docs/sdlc/current/feature-map.json": (1, "authoritative Feature Map"),
    }
    for folder, reason in (
        ("requirements", "authoritative Requirement"),
        ("designs", "authoritative Design"),
        ("verification", "authoritative Verification"),
    ):
        directory = root / "docs" / "sdlc" / "current" / folder
        if directory.is_dir():
            for path in sorted(directory.glob("*.json")):
                candidates[path.relative_to(root).as_posix()] = (1, reason)
    implementation_candidates: set[str] = set()
    for item in spec["design"]["items"]:
        for pattern in item["allowed_paths"]:
            wildcard = min(
                [index for token in ("*", "?", "[") if (index := pattern.find(token)) >= 0],
                default=len(pattern),
            )
            prefix = pattern[:wildcard].rstrip("/")
            path = root / prefix if prefix else root
            if path.is_file():
                implementation_candidates.add(path.relative_to(root).as_posix())
                continue
            directory = path if path.is_dir() else path.parent
            if not directory.is_dir():
                continue
            for candidate in sorted(directory.rglob("*")):
                if len(implementation_candidates) >= MAX_IMPLEMENTATION_RESOURCES:
                    break
                if (
                    candidate.is_file()
                    and candidate.stat().st_size <= 80_000
                    and ".sdlc-pipeline/scripts" not in candidate.as_posix()
                    and ".opencode" not in candidate.parts
                    and ".sdlc-pipeline" not in candidate.parts
                    and any(
                        fnmatch.fnmatch(candidate.relative_to(root).as_posix(), allowed)
                        or candidate.relative_to(root).as_posix() == allowed.rstrip("/")
                        or candidate.relative_to(root).as_posix().startswith(
                            allowed.rstrip("/") + "/"
                        )
                        for allowed in item["allowed_paths"]
                    )
                ):
                    implementation_candidates.add(
                        candidate.relative_to(root).as_posix()
                    )
    for name in sorted(implementation_candidates)[:MAX_IMPLEMENTATION_RESOURCES]:
        candidates[name] = (2, "design-allowed business implementation candidate")
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
        candidates[path] = (3, "active guidance; read only for the matching stack")
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
    first_requirement = requirements[0] if requirements else None
    first_requirement_id = first_requirement["id"] if first_requirement else None
    first_delivery = None
    if first_requirement_id:
        first_delivery = {
            "requirement_id": first_requirement_id,
            "design_ids": [
                item["id"] for item in designs
                if first_requirement_id in item["requirement_ids"]
            ],
            "test_ids": [
                item["id"] for item in tests
                if first_requirement_id in item["requirement_ids"]
            ],
        }
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
        "tooling_paths": TOOLING_CONFIG_PATHS,
        "test_ids": [item["id"] for item in tests],
        "first_delivery": first_delivery,
        "verification": [
            {
                "id": item["id"],
                "command": item["command"],
                "selector": item["selector"],
                "expected": item["expected"],
            }
            for item in tests
        ],
        "acceptance": [
            criterion
            for item in requirements
            for criterion in item["acceptance_criteria"]
        ],
        "source_refs": sorted({
            f"{ref['source_id']}#{ref['anchor']}"
            for item in requirements
            for ref in item.get("source_refs", [])
        }),
        "confirmed_decisions": delivery_memory(root)["decisions"],
    }
    pack = {
        "schema_version": "1.0",
        "mode": "progressive",
        "role": role,
        "brief": brief,
        "resources": _context_resources(root),
        "instruction": (
            "以 brief 为实现事实；只在修改需要时读取 resources。"
            "禁止读取 .sdlc-pipeline/scripts/** 来理解 Core。"
            "tier=1 是权威契约，tier=2 是业务实现候选，tier=3 是 active rule。"
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
        "先以 brief.first_delivery 指定的 R/D/T 作为第一个纵向交付切片；"
        "读取 manifest 后不得预读全部 resources 或枚举源码目录，"
        "第 4 次工具调用前必须在 allowed_paths 内开始真实实现；"
        "coder 只实现当前 Feature Slice 和登记的 functional 文件；"
        "code 阶段不运行依赖项目启动的 functional 测试，"
        "禁止调用 compile/restart/health/test；验证统一由 Core 执行。"
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
    if not actual:
        raise SdlcError(
            "coder handoff 未产生允许的业务改动；请完成当前 Feature Slice 后再提交 handoff"
        )
    value["changed_files"] = actual
    value["validated_at"] = utc_now()
    value["compiled_claim_ignored"] = True
    value["mapping_strategy"] = "post-code-delivery-trace"
    write_json(root / ".sdlc-pipeline" / "runs" / "coder-handoff.json", value)
    return {"ok": True, "handoff": value, "diff": diff}


def after_task(root: Path, role: str, output: str) -> dict[str, Any]:
    if role == "coder":
        return validate_coder_handoff(root, output)
    raise SdlcError(f"不允许的 subagent: {role}")
