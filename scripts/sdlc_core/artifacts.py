from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import (
    ID_PATTERNS,
    SdlcError,
    read_json,
    require_fields,
    sha256_file,
    sha256_json,
    utc_now,
    write_json,
    atomic_write,
)


CURRENT_FILES = {
    "requirements": "requirements",
    "design": "design",
    "test_plan": "test-plan",
}


def _unique(items: list[dict[str, Any]], kind: str) -> set[str]:
    pattern = ID_PATTERNS[kind]
    ids: set[str] = set()
    for item in items:
        identifier = item.get("id", "")
        if not pattern.fullmatch(identifier):
            raise SdlcError(f"非法 {kind} ID: {identifier!r}")
        if identifier in ids:
            raise SdlcError(f"重复 {kind} ID: {identifier}")
        ids.add(identifier)
    return ids


def validate_spec(payload: dict[str, Any]) -> dict[str, set[str]]:
    require_fields(
        payload,
        ("schema_version", "flow", "requirements", "design", "test_plan"),
        "spec",
    )
    if payload["flow"] not in {"standard", "incremental"}:
        raise SdlcError("flow 必须是 standard 或 incremental")
    requirements = payload["requirements"].get("items", [])
    decisions = payload["design"].get("items", [])
    tests = payload["test_plan"].get("items", [])
    if not requirements or not decisions or not tests:
        raise SdlcError("requirements、design、test_plan 均至少包含一项")
    r_ids = _unique(requirements, "requirement")
    d_ids = _unique(decisions, "design")
    t_ids = _unique(tests, "test")

    for requirement in requirements:
        require_fields(
            requirement, ("id", "title", "description", "acceptance_criteria"),
            requirement.get("id", "requirement"),
        )
        if not isinstance(requirement["acceptance_criteria"], list):
            raise SdlcError(f"{requirement['id']} acceptance_criteria 必须是数组")
        supersedes = requirement.get("supersedes")
        if supersedes and not ID_PATTERNS["requirement"].fullmatch(supersedes):
            raise SdlcError(f"{requirement['id']} supersedes 非法: {supersedes}")

    covered_r: set[str] = set()
    for decision in decisions:
        require_fields(
            decision,
            (
                "id", "title", "description", "requirement_ids", "module",
                "extension_point", "allowed_paths",
            ),
            decision.get("id", "design"),
        )
        refs = set(decision["requirement_ids"])
        if not refs or not refs <= r_ids:
            raise SdlcError(f"{decision['id']} 引用了未知 R-id: {sorted(refs - r_ids)}")
        if not decision["allowed_paths"]:
            raise SdlcError(f"{decision['id']} allowed_paths 不能为空")
        covered_r |= refs

    tested_r: set[str] = set()
    tested_d: set[str] = set()
    for test in tests:
        require_fields(
            test,
            (
                "id", "title", "requirement_ids", "design_ids", "level",
                "preconditions", "input", "expected", "mandatory", "command",
            ),
            test.get("id", "test"),
        )
        r_refs = set(test["requirement_ids"])
        d_refs = set(test["design_ids"])
        if not r_refs <= r_ids or not d_refs <= d_ids:
            raise SdlcError(f"{test['id']} 存在未知 R/D 引用")
        if not isinstance(test["mandatory"], bool):
            raise SdlcError(f"{test['id']} mandatory 必须是布尔值")
        if not isinstance(test["command"], str) or not test["command"]:
            raise SdlcError(f"{test['id']} command 必须引用 lifecycle tests 中的命令")
        tested_r |= r_refs
        tested_d |= d_refs

    if covered_r != r_ids:
        raise SdlcError(f"存在未设计的需求: {sorted(r_ids - covered_r)}")
    if tested_r != r_ids:
        raise SdlcError(f"存在无测试的需求: {sorted(r_ids - tested_r)}")
    if not d_ids <= tested_d:
        raise SdlcError(f"存在无测试覆盖的设计: {sorted(d_ids - tested_d)}")
    if not any(item["mandatory"] for item in tests):
        raise SdlcError("测试计划至少包含一个 mandatory 用例")
    return {"R": r_ids, "D": d_ids, "T": t_ids}


def _render_requirements(data: dict[str, Any]) -> str:
    lines = ["# 需求规格", "", f"- 流程：`{data['flow']}`", ""]
    for item in data["items"]:
        lines += [
            f"## {item['id']} {item['title']}",
            "",
            item["description"],
            "",
            "验收标准：",
            "",
            *[f"- {criterion}" for criterion in item["acceptance_criteria"]],
            "",
        ]
        if item.get("supersedes"):
            lines += [f"替代：`{item['supersedes']}`", ""]
    return "\n".join(lines).rstrip() + "\n"


def _render_design(data: dict[str, Any]) -> str:
    lines = ["# 设计说明", ""]
    for item in data["items"]:
        lines += [
            f"## {item['id']} {item['title']}",
            "",
            item["description"],
            "",
            f"- 需求：{', '.join(f'`{x}`' for x in item['requirement_ids'])}",
            f"- Module：`{item['module']}`",
            f"- Extension point：`{item['extension_point']}`",
            f"- 允许路径：{', '.join(f'`{x}`' for x in item['allowed_paths'])}",
            "",
        ]
        if item.get("interfaces"):
            lines += ["接口：", "", *[f"- {x}" for x in item["interfaces"]], ""]
        if item.get("data_model"):
            lines += ["数据模型：", "", *[f"- {x}" for x in item["data_model"]], ""]
    return "\n".join(lines).rstrip() + "\n"


def _render_test_plan(data: dict[str, Any]) -> str:
    lines = ["# 测试计划", ""]
    for item in data["items"]:
        lines += [
            f"## {item['id']} {item['title']}",
            "",
            f"- 需求：{', '.join(f'`{x}`' for x in item['requirement_ids'])}",
            f"- 设计：{', '.join(f'`{x}`' for x in item['design_ids'])}",
            f"- 级别：`{item['level']}`",
            f"- Mandatory：`{str(item['mandatory']).lower()}`",
            f"- Lifecycle command：`{item['command']}`",
            f"- 前置条件：{item['preconditions']}",
            f"- 输入：{item['input']}",
            f"- 预期：{item['expected']}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def publish_spec(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    ids = validate_spec(payload)
    historical: dict[str, str] = {}
    versions = root / "docs" / "sdlc" / "versions"
    if versions.exists():
        for manifest_path in sorted(versions.glob("V????/manifest.json")):
            manifest = read_json(manifest_path)
            for identifier, record in manifest.get("requirement_records", {}).items():
                historical[identifier] = record["sha256"]
    for requirement in payload["requirements"]["items"]:
        identifier = requirement["id"]
        fingerprint = sha256_json(requirement)
        if identifier in historical and historical[identifier] != fingerprint:
            raise SdlcError(
                f"{identifier} 已在历史版本中使用且内容变化；请创建新 R-id 并设置 supersedes"
            )
        supersedes = requirement.get("supersedes")
        if supersedes and (supersedes == identifier or supersedes not in historical):
            raise SdlcError(
                f"{identifier} supersedes 必须指向已固化且不同的历史 R-id"
            )
    if payload["flow"] == "incremental":
        if payload.get("incremental_confirmed") is not True:
            raise SdlcError("增量流程必须记录用户明确确认")
        from .trace import verify_scaffold
        from .versions import parent_manifest

        drift = verify_scaffold(root)
        parent = parent_manifest(root)
        reasons = []
        if not drift["ok"]:
            reasons.append("scaffold_or_lifecycle_drift")
        if not parent or parent.get("status") != "closed":
            reasons.append("missing_parent_manifest")
        flags = payload["requirements"].get("change_flags", {})
        reasons += [
            key
            for key in (
                "public_interface", "dependency", "data_model", "security",
                "lifecycle", "protected_path",
            )
            if flags.get(key)
        ]
        if reasons:
            raise SdlcError(f"不满足增量流程机器条件: {sorted(set(reasons))}")
    current = root / "docs" / "sdlc" / "current"
    generated = utc_now()
    artifacts = {
        "requirements": {
            **payload["requirements"],
            "schema_version": payload["schema_version"],
            "flow": payload["flow"],
            "generated_at": generated,
        },
        "design": {
            **payload["design"],
            "schema_version": payload["schema_version"],
            "generated_at": generated,
        },
        "test_plan": {
            **payload["test_plan"],
            "schema_version": payload["schema_version"],
            "generated_at": generated,
        },
    }
    renderers = {
        "requirements": _render_requirements,
        "design": _render_design,
        "test_plan": _render_test_plan,
    }
    staged: list[tuple[Path, str]] = []
    for kind, data in artifacts.items():
        base = CURRENT_FILES[kind]
        staged.append((current / f"{base}.json", __import__("json").dumps(
            data, ensure_ascii=False, indent=2
        ) + "\n"))
        staged.append((current / f"{base}.md", renderers[kind](data)))
    # All validation happens before any target is replaced.
    for path, content in staged:
        atomic_write(path, content)
    hashes = {
        kind: sha256_file(current / f"{base}.json")
        for kind, base in CURRENT_FILES.items()
    }
    return {"ok": True, "ids": {k: sorted(v) for k, v in ids.items()}, "hashes": hashes}


def load_current_spec(root: Path) -> dict[str, Any]:
    current = root / "docs" / "sdlc" / "current"
    requirements = read_json(current / "requirements.json")
    design = read_json(current / "design.json")
    test_plan = read_json(current / "test-plan.json")
    combined = {
        "schema_version": requirements["schema_version"],
        "flow": requirements["flow"],
        "requirements": requirements,
        "design": design,
        "test_plan": test_plan,
    }
    validate_spec(combined)
    return combined


def render_test_results(data: dict[str, Any]) -> str:
    lines = [
        f"# 测试结果 {data['version']}",
        "",
        f"- 状态：`{data['status']}`",
        f"- 开始：`{data['started_at']}`",
        f"- 结束：`{data['finished_at']}`",
        "",
        "| T-id | 结果 | 耗时(ms) | 日志 |",
        "|---|---:|---:|---|",
    ]
    for item in data["results"]:
        lines.append(
            f"| {item['id']} | {item['status']} | {item.get('duration_ms', 0)} | "
            f"`{item.get('log', '')}` |"
        )
    if data.get("open_issues"):
        lines += ["", "## Open issues", "", *[f"- {x}" for x in data["open_issues"]]]
    return "\n".join(lines).rstrip() + "\n"
