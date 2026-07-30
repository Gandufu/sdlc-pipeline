from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from typing import Any

from .artifacts import load_current_spec, require_code_ready
from .artifact_store import current_baseline
from .common import SdlcError, read_json, sha256_file, utc_now
from .layout import contracts_root, rules_root, runtime_root
from .stores import (
    read_work_record,
    record_index,
    write_work_record,
)
from .trace import (
    TOOLING_CONFIG_PATHS,
    changed_path_fingerprints,
    implementation_fingerprint,
    validate_diff,
    verify_extension_points,
)

from .schema_validation import validate_schema_instance

MAX_CONTEXT_RESOURCES = 10
MAX_IMPLEMENTATION_RESOURCES = 6


def validate_write_path(
    root: Path,
    path_value: str,
    *,
    role: str | None = None,
) -> dict[str, Any]:
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise SdlcError("禁止写入项目之外的路径") from exc
    from .trace import allowed_change_paths, matches_path, scaffold

    if role == "coder" and _is_test_path(relative):
        raise SdlcError(f"coder 禁止修改测试脚本: {relative}")
    if role == "tester":
        if relative not in _tester_writable_paths(root):
            raise SdlcError(
                "tester 只能修改 Spec 声明的测试脚本或"
                f"预检必需的既有单元测试: {relative}"
            )
    contract = scaffold(root)
    if matches_path(relative, contract["protected_paths"]):
        raise SdlcError(f"禁止修改 protected path: {relative}")
    allowed = allowed_change_paths(root)
    if not matches_path(relative, allowed):
        raise SdlcError(f"路径不在设计/脚手架允许范围: {relative}")
    return {"ok": True, "path": relative}


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.startswith(("tests/", "test/"))


def _declared_test_paths(root: Path) -> set[str]:
    return {
        item["selector"].replace("\\", "/")
        for item in load_current_spec(root)["test_plan"]["items"]
        if item.get("selector")
    }


def _preflight_unit_test_paths(root: Path) -> set[str]:
    """Return existing unit tests which the contract-owned preflight may run.

    Test preflight is executed after tester handoff.  When it invokes the
    template's full unit suite, stale scaffold unit tests must be maintainable
    by the tester even if the published Spec only declares functional tests.
    Restrict the exception to already-existing files under the contract's unit
    selector patterns; the tester still cannot create arbitrary test sources.
    """
    from .lifecycle import preflight_unit_test_paths

    return preflight_unit_test_paths(root)


def _tester_writable_paths(root: Path) -> set[str]:
    return _declared_test_paths(root) | _preflight_unit_test_paths(root)


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


def _context_resources(root: Path, role: str) -> list[dict[str, Any]]:
    spec = load_current_spec(root)
    selected = current_baseline(root)
    if not selected:
        raise SdlcError("缺少已发布的 spec baseline")
    baseline, _ = selected
    candidates: dict[str, tuple[int, str]] = {
        (baseline / "spec.md").relative_to(root).as_posix(): (
            1,
            "authoritative Spec preview",
        ),
    }
    for group, reason in (
        ("requirements", "authoritative Requirement"),
        ("design", "authoritative Design"),
    ):
        for item in spec[group]["items"]:
            candidates[item["content_ref"]] = (1, reason)
    if role == "tester":
        for item in spec["test_plan"]["items"]:
            candidates[item["content_ref"]] = (
                1,
                "authoritative Verification",
            )
            selector = item.get("selector")
            if selector and (root / selector).is_file():
                candidates[selector] = (2, "declared test source")
    implementation_candidates: set[str] = set()
    for item in spec["design"]["items"]:
        for pattern in item["allowed_paths"]:
            if _is_test_path(pattern.rstrip("/") + "/"):
                continue
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
                    and runtime_root(root).as_posix() not in candidate.as_posix()
                    and ".opencode" not in candidate.parts
                    and ".sdlc-pipeline" not in candidate.parts
                    and not _is_test_path(
                        candidate.relative_to(root).as_posix()
                    )
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
        contracts_root(root) / "active-rules.json", required=False
    ) or {"rules": []}
    for rule in active_rules.get("rules", []):
        path = rule.get("path")
        if (
            not isinstance(path, str)
            or not path.startswith(".sdlc-pipeline/runtime/rules/")
            or not path.endswith(".md")
        ):
            raise SdlcError(f"active rule 路径非法: {path!r}")
        rule_path = root / path
        try:
            rule_path.resolve().relative_to(
                rules_root(root).resolve()
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
            if tier == 1:
                raise SdlcError(f"权威 context resource 缺失或不可读: {name}")
            continue
        try:
            digest = sha256_file(path)
            size = path.stat().st_size
        except OSError as exc:
            raise SdlcError(f"context resource 不可读: {name}: {exc}") from exc
        resources.append({
            "path": name,
            "sha256": digest,
            "size": size,
            "tier": tier,
            "reason": reason,
        })
    return resources


def build_context_pack(root: Path, role: str) -> dict[str, Any]:
    from .memory import delivery_memory
    from .feedback import active_feedback

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
            if not _is_test_path(path.rstrip("/") + "/")
        }),
        "tooling_paths": TOOLING_CONFIG_PATHS,
        "first_delivery": first_delivery,
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
    if role == "coder":
        feedback = active_feedback(root)
        if feedback is not None:
            brief["rework"] = {
                key: feedback[key]
                for key in (
                    "feedback_id", "origin", "classification", "summary",
                    "expected", "actual", "reproduction_steps",
                    "affected_ids", "source_refs", "evidence_refs",
                    "target_phase", "stage",
                )
            }
    if role == "tester":
        brief.update({
            "test_ids": [item["id"] for item in tests],
            "allowed_paths": sorted(_tester_writable_paths(root)),
            "preflight_unit_test_paths": sorted(_preflight_unit_test_paths(root)),
            "verification": [
                {
                    "id": item["id"],
                    "command": item["command"],
                    "selector": item.get("selector"),
                    "expected": item["expected"],
                }
                for item in tests
            ],
        })
    pack = {
        "schema_version": "1.0",
        "mode": "progressive",
        "role": role,
        "brief": brief,
        "resources": _context_resources(root, role),
        "instruction": (
            "以 brief 为实现事实；只在修改需要时读取 resources。"
            "禁止读取 .sdlc-pipeline/runtime/scripts/** 来理解 Core。"
            "tier=1 是权威契约，tier=2 是业务实现候选，tier=3 是 active rule。"
        ),
    }
    write_work_record(
        root,
        f"context/{role}",
        pack,
        state="ready",
        title=f"{role} context manifest",
    )
    index = record_index(root, f"context/{role}")
    characters = len(json.dumps(pack, ensure_ascii=False))
    return {
        "paths": [index["content_ref"]],
        "parts": 1,
        "characters": characters,
        "repeated_chars": 0,
        "resource_count": len(pack["resources"]),
        "mode": "progressive",
    }


def before_task(root: Path, role: str) -> dict[str, Any]:
    if role not in {"coder", "tester"}:
        raise SdlcError(f"不允许的 subagent: {role}")
    from .status import status

    current = status(root)
    if role == "coder" and not (
        current["gates"]["init"] and current["gates"]["spec"]
    ):
        raise SdlcError("coder 门禁要求 init 与 spec 均通过")
    if role == "coder" and current["gates"]["code"]:
        raise SdlcError(
            "code gate 已通过；再次派发 coder 必须先记录结构化 Feedback"
        )
    rework = current.get("rework") or {}
    if (
        role == "coder"
        and rework.get("status") == "active"
        and rework.get("target_phase") == "spec"
        and rework.get("stage") != "spec_published"
    ):
        raise SdlcError(
            "Feedback 要求先发布修订后的 Spec baseline，再派发 coder"
        )
    if role == "tester" and not current["gates"]["code"]:
        raise SdlcError("tester 门禁要求 code gate 已通过")
    if role == "coder":
        require_code_ready(load_current_spec(root))
    verify_extension_points(root)
    spec_pointer = read_json(root / "docs" / "sdlc" / "current.json", required=False) or {}
    implementation: dict[str, Any] | None = None
    if role == "tester":
        implementation = implementation_fingerprint(root)
        previous_dispatch = read_work_record(
            root,
            "tester-dispatch",
            required=False,
        )
        if (
            previous_dispatch is not None
            and previous_dispatch.get("implementation_fingerprint")
            == implementation["sha256"]
            and not current["gates"]["test"]
        ):
            raise SdlcError(
                "当前实现已派发过 tester；测试失败后禁止自动重复派发。"
                "请先完成明确的 code 返工，使实现指纹变化后再进入 test 阶段"
            )
        write_work_record(
            root,
            "tester-dispatch",
            {
                "baseline_id": spec_pointer.get("baseline_id"),
                "implementation_fingerprint": implementation["sha256"],
                "created_at": utc_now(),
            },
            state="captured",
            title="Tester dispatch boundary",
        )
    previous = read_work_record(root, f"task/{role}-before", required=False)
    reuse_baseline = (
        previous is not None
        and previous.get("baseline_id") == spec_pointer.get("baseline_id")
        and (
            role != "tester"
            or previous.get("implementation_fingerprint") == implementation["sha256"]
        )
        and not current["gates"]["test" if role == "tester" else "code"]
    )
    if not reuse_baseline:
        before = changed_path_fingerprints(root)
        before_record = {
            "created_at": utc_now(),
            "baseline_id": spec_pointer.get("baseline_id"),
            "changed_paths": [item["path"] for item in before["entries"]],
            "worktree": before,
        }
        if implementation is not None:
            before_record["implementation_fingerprint"] = implementation["sha256"]
        write_work_record(
            root,
            f"task/{role}-before",
            before_record,
            state="captured",
            title=f"{role} task before snapshot",
        )
    context = build_context_pack(root, role)
    requirement_count = len(load_current_spec(root)["requirements"]["items"])
    from .runs import record_tokens

    record_tokens(
        root,
        role,
        repeated_chars=context["repeated_chars"],
        source="context-pack",
    )
    if role == "coder":
        role_instruction = (
            "先以 brief.first_delivery 指定的 R/D 作为第一个纵向交付切片；"
            "读取 manifest 后不得预读全部 resources 或枚举源码目录，"
            "第 4 次工具调用前必须在 allowed_paths 内开始真实实现；"
            "coder 只实现业务代码，禁止读取、创建或修改 tests/、test/ 下的测试脚本；"
            "禁止调用 compile/start/restart/health/stop/test；"
            "handoff 后 Core 统一执行 compile、package、start 与 readiness，并保留预览进程。"
            "TypeScript hard policy 会拒绝 : any、as any、<any>；"
            "只实现已确认 R/D/AC，不为臆造的无效输入使用类型逃逸。"
        )
    else:
        role_instruction = (
            "tester 只读取 Verification/AC、必要业务界面和现有测试约定；"
            "只能创建或修改 brief.allowed_paths 明确列出的测试脚本；"
            "禁止修改业务源码、配置和正式 SDLC 文档；"
            "禁止调用 compile/start/restart/health/stop/test；"
            "handoff 后 Core 停止预览并确认端口释放，再由 Playwright 脚本启动、测试和 cleanup。"
        )
    return {
        "ok": True,
        "role": role,
        "requirement_count": requirement_count,
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
    before = read_work_record(root, "task/coder-before")
    diff = validate_diff(root, before.get("worktree", before.get("changed_paths", [])))
    actual = sorted(set(diff["changed_paths"]))
    if not actual:
        raise SdlcError(
            "coder handoff 未产生允许的业务改动；请完成当前 Feature Slice 后再提交 handoff"
        )
    test_changes = [path for path in actual if _is_test_path(path)]
    if test_changes:
        raise SdlcError(
            f"coder handoff 包含测试脚本改动，测试脚本只属于 test 阶段: {test_changes}"
        )
    value["changed_files"] = actual
    value["validated_at"] = utc_now()
    value["compiled_claim_ignored"] = True
    value["mapping_strategy"] = "post-code-delivery-trace"
    write_work_record(
        root,
        "coder-handoff",
        value,
        state="validated",
        title="Coder handoff",
    )
    return {"ok": True, "handoff": value, "diff": diff}


def validate_tester_handoff(root: Path, text: str) -> dict[str, Any]:
    recovery_reason: str | None = None
    try:
        value = _extract_json(text)
    except SdlcError as error:
        # Some OpenCode task transports can lose the tester's final JSON even
        # after its constrained writes have completed.  Do not manufacture a
        # claim on behalf of the agent: only recover a receipt after the same
        # allowed-path and declared-selector checks below have independently
        # proved that test sources were delivered.  The receipt remains
        # explicitly marked so the release audit can distinguish it.
        recovery_reason = str(error)
        value = {
            "summary": "Core 根据受限测试改动恢复 tester handoff 收据",
            "open_issues": [],
            "full_scan": False,
            "full_scan_reason": "subagent JSON handoff 缺失；Core 将核验声明的测试文件和受限 diff",
        }
    validate_schema_instance(root, "handoff.schema.json", value)
    before = read_work_record(root, "task/tester-before")
    diff = validate_diff(
        root,
        before.get("worktree", before.get("changed_paths", [])),
    )
    actual = sorted(set(diff["changed_paths"]))
    declared = _declared_test_paths(root)
    allowed = _tester_writable_paths(root)
    outside = [path for path in actual if path not in allowed]
    if outside:
        raise SdlcError(
            "tester handoff 只能包含 Spec 声明的测试脚本或"
            f"预检必需的既有单元测试: {outside}"
        )
    missing = sorted(path for path in declared if not (root / path).is_file())
    if missing:
        raise SdlcError(f"Spec 声明的测试脚本不存在: {missing}")
    if recovery_reason is not None and not actual:
        raise SdlcError(recovery_reason)
    value["changed_files"] = actual
    value["validated_at"] = utc_now()
    value["mapping_strategy"] = "post-test-delivery-trace"
    if recovery_reason is not None:
        value["output_recovery"] = {
            "mode": "allowed-test-diff",
            "reason": recovery_reason,
            "observed_paths": actual,
        }
    write_work_record(
        root,
        "tester-handoff",
        value,
        state="validated",
        title=(
            "Tester handoff (Core recovery)"
            if recovery_reason is not None else "Tester handoff"
        ),
    )
    return {"ok": True, "handoff": value, "diff": diff}


def after_task(root: Path, role: str, output: str) -> dict[str, Any]:
    if role == "coder":
        return validate_coder_handoff(root, output)
    if role == "tester":
        return validate_tester_handoff(root, output)
    raise SdlcError(f"不允许的 subagent: {role}")
