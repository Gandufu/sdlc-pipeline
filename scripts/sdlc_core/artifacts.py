from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .artifact_store import current_artifact_path, materialize_bundle, publish_bundle
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
from .schema_validation import validate_schema_instance
from .sources import source_index, validate_source_envelopes


CURRENT_FILES = {
    "requirements": "requirements",
    "design": "design",
    "test_plan": "test-plan",
}


def lifecycle_test_commands(root: Path) -> dict[str, dict[str, Any]]:
    contract = read_json(root / ".sdlc-pipeline" / "lifecycle.json")
    tests = contract.get("tests")
    if not isinstance(tests, dict):
        raise SdlcError("lifecycle.json tests 必须是对象")
    return {
        name: command
        for name, command in tests.items()
        if isinstance(name, str) and isinstance(command, dict)
    }


def current_spec_hashes(root: Path) -> dict[str, str]:
    return {
        kind: sha256_file(
            current_artifact_path(root, "spec", f"{base}.json")
        )
        for kind, base in CURRENT_FILES.items()
    }


def validate_lifecycle_test_references(
    root: Path,
    payload: dict[str, Any],
) -> None:
    commands = lifecycle_test_commands(root)
    available = sorted(commands)
    unknown = [
        (item["id"], item["command"])
        for item in payload["test_plan"]["items"]
        if item["command"] not in commands
    ]
    if unknown:
        details = "；".join(
            f"{identifier} 引用未知 lifecycle test command: {command}"
            for identifier, command in unknown
        )
        allowed = ", ".join(available) or "无"
        raise SdlcError(
            f"{details}；command 必须填写 lifecycle tests 逻辑键，"
            f"不能填写 pnpm test 等 shell 命令；允许值: {allowed}"
        )


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


def _require_string_list(value: Any, name: str, *, nonempty: bool = False) -> None:
    if not isinstance(value, list) or (nonempty and not value):
        suffix = "且不能为空" if nonempty else ""
        raise SdlcError(f"{name} 必须是数组{suffix}")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise SdlcError(f"{name} 只能包含非空字符串")


def _require_keys(value: dict[str, Any], fields: tuple[str, ...], context: str) -> None:
    missing = [field for field in fields if field not in value]
    if missing:
        raise SdlcError(f"{context} 缺少必填字段: {', '.join(missing)}")


def _validate_source_refs(
    refs: Any,
    sources: dict[str, set[str]],
    context: str,
) -> None:
    if not isinstance(refs, list) or not refs:
        raise SdlcError(f"{context} source_refs 必须是非空数组")
    for ref in refs:
        if not isinstance(ref, str) or "#" not in ref:
            raise SdlcError(f"{context} 非法 source_ref: {ref!r}")
        source_id, anchor = ref.split("#", 1)
        if source_id not in sources:
            raise SdlcError(f"{context} 引用未知 SourceEnvelope: {source_id}")
        if anchor not in sources[source_id]:
            raise SdlcError(f"{context} 引用未知原文 anchor: {ref}")


def _criterion_text(value: Any) -> str:
    if isinstance(value, dict):
        refs = ", ".join(value.get("source_refs", []))
        return f"`{value.get('id', '')}` {value.get('description', '')}（来源：{refs}）"
    return str(value)


def unresolved_blocking_questions(spec: dict[str, Any]) -> list[dict[str, Any]]:
    analysis = spec.get("requirements", {}).get("analysis", {})
    return [
        question
        for question in analysis.get("open_questions", [])
        if question.get("blocking") is True and question.get("status") != "resolved"
    ]


def require_code_ready(spec: dict[str, Any]) -> None:
    blockers = unresolved_blocking_questions(spec)
    if blockers:
        identifiers = [item["id"] for item in blockers]
        raise SdlcError(f"code 门禁拒绝未解决的 blocking 问题: {identifiers}")


def validate_spec(
    payload: dict[str, Any],
    root: Path | None = None,
) -> dict[str, set[str]]:
    require_fields(
        payload,
        (
            "schema_version", "flow", "spec_confirmed",
            "requirements", "design", "test_plan",
        ),
        "spec",
    )
    if payload["spec_confirmed"] is not True:
        raise SdlcError("spec 发布前必须记录用户明确确认")
    if payload["flow"] not in {"standard", "incremental"}:
        raise SdlcError("flow 必须是 standard 或 incremental")
    require_fields(
        payload["requirements"],
        ("source_inputs", "analysis", "items"),
        "requirements",
    )
    source_inputs = payload["requirements"]["source_inputs"]
    if not isinstance(source_inputs, list) or not source_inputs:
        raise SdlcError("requirements.source_inputs 至少包含一项原始输入")
    for index, source in enumerate(source_inputs, 1):
        require_fields(source, ("source", "content"), f"source_inputs[{index}]")
        if not isinstance(source["source"], str) or not source["source"].strip():
            raise SdlcError(f"source_inputs[{index}].source 必须是非空字符串")
        if not isinstance(source["content"], str) or not source["content"].strip():
            raise SdlcError(f"source_inputs[{index}].content 必须是非空字符串")

    sources: dict[str, set[str]] = {}
    if payload.get("schema_version") == "1.1":
        validate_source_envelopes(root or Path(__file__).resolve().parents[2], source_inputs)
        sources = source_index(source_inputs)

    analysis = payload["requirements"]["analysis"]
    _require_keys(
        analysis,
        (
            "confirmed_facts", "impact_scope", "assumptions",
            "open_questions", "risks", "decisions",
        ),
        "requirements.analysis",
    )
    for name in (
        "confirmed_facts", "impact_scope", "assumptions", "risks", "decisions",
    ):
        _require_string_list(
            analysis[name],
            f"requirements.analysis.{name}",
            nonempty=name == "impact_scope",
        )
    questions = analysis["open_questions"]
    if not isinstance(questions, list):
        raise SdlcError("requirements.analysis.open_questions 必须是数组")
    question_ids: set[str] = set()
    for index, question in enumerate(questions, 1):
        _require_keys(
            question,
            ("id", "question", "blocking", "status"),
            f"open_questions[{index}]",
        )
        identifier = question["id"]
        if not re.fullmatch(r"Q-[0-9]{4}", identifier):
            raise SdlcError(f"非法问题 ID: {identifier!r}")
        if identifier in question_ids:
            raise SdlcError(f"重复问题 ID: {identifier}")
        question_ids.add(identifier)
        if not isinstance(question["question"], str) or not question["question"].strip():
            raise SdlcError(f"{identifier} question 必须是非空字符串")
        if not isinstance(question["blocking"], bool):
            raise SdlcError(f"{identifier} blocking 必须是布尔值")
        if question["status"] not in {"open", "resolved"}:
            raise SdlcError(f"{identifier} status 只能是 open/resolved")
        if question["status"] == "resolved" and not str(
            question.get("resolution", "")
        ).strip():
            raise SdlcError(f"{identifier} resolved 时必须提供 resolution")

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
        if payload.get("schema_version") == "1.1":
            _validate_source_refs(
                requirement.get("source_refs"), sources, requirement["id"]
            )
            criteria = requirement["acceptance_criteria"]
            for index, criterion in enumerate(criteria, 1):
                if not isinstance(criterion, dict):
                    raise SdlcError(
                        f"{requirement['id']} 在 spec 1.1 中必须使用结构化 AC-id"
                    )
                expected_id = f"AC-{requirement['id']}-{index:02d}"
                if criterion.get("id") != expected_id:
                    raise SdlcError(
                        f"{requirement['id']} 验收标准 ID 必须连续为 {expected_id}"
                    )
                _validate_source_refs(
                    criterion.get("source_refs"),
                    sources,
                    criterion["id"],
                )
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
    validate_schema_instance(
        root or Path(__file__).resolve().parents[2], "spec.schema.json", payload
    )
    return {"R": r_ids, "D": d_ids, "T": t_ids}


def _render_requirements(data: dict[str, Any]) -> str:
    lines = [
        "# 需求规格",
        "",
        f"- 流程：`{data['flow']}`",
        f"- 用户确认：`{str(data['spec_confirmed']).lower()}`",
        "",
        "## 原始输入",
        "",
    ]
    for source in data["source_inputs"]:
        quoted = [
            f"> {line}" if line else ">"
            for line in source["content"].splitlines()
        ]
        metadata = []
        if source.get("source_id"):
            metadata = [
                f"- Source ID：`{source['source_id']}`",
                f"- SHA-256：`{source['sha256']}`",
            ]
        lines += [f"### {source['source']}", "", *metadata, "", *quoted, ""]
    analysis = data["analysis"]
    lines += ["## 分析与边界", ""]
    sections = (
        ("已确认事实", "confirmed_facts"),
        ("影响范围", "impact_scope"),
        ("假设", "assumptions"),
        ("风险", "risks"),
        ("决策", "decisions"),
    )
    for title, key in sections:
        lines += [f"### {title}", ""]
        values = analysis[key]
        lines += [*[f"- {value}" for value in values], ""] if values else ["- 无", ""]
    lines += ["### 待确认问题", ""]
    if analysis["open_questions"]:
        for question in analysis["open_questions"]:
            state = question["status"]
            blocking = "blocking" if question["blocking"] else "non-blocking"
            lines.append(
                f"- `{question['id']}` [{state}/{blocking}] {question['question']}"
            )
            if question.get("resolution"):
                lines.append(f"  - 结论：{question['resolution']}")
        lines.append("")
    else:
        lines += ["- 无", ""]
    lines += ["## 规范化需求", ""]
    for item in data["items"]:
        lines += [
            f"## {item['id']} {item['title']}",
            "",
            item["description"],
            "",
            "验收标准：",
            "",
            *[f"- {_criterion_text(criterion)}" for criterion in item["acceptance_criteria"]],
            "",
        ]
        if item.get("supersedes"):
            lines += [f"替代：`{item['supersedes']}`", ""]
    return "\n".join(lines).rstrip() + "\n"


def _render_design(data: dict[str, Any]) -> str:
    covered = sorted({
        requirement_id
        for item in data["items"]
        for requirement_id in item["requirement_ids"]
    })
    lines = [
        "# 设计说明",
        "",
        "## 设计概述",
        "",
        f"- 设计决策：`{len(data['items'])}` 项",
        f"- 覆盖需求：{', '.join(f'`{x}`' for x in covered)}",
        "",
        "## 模块、接口与取舍",
        "",
    ]
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
    mandatory = sum(1 for item in data["items"] if item["mandatory"])
    levels = sorted({item["level"] for item in data["items"]})
    commands = sorted({item["command"] for item in data["items"]})
    lines = [
        "# 测试计划",
        "",
        "## 测试策略与门禁",
        "",
        f"- 用例总数：`{len(data['items'])}`",
        f"- Mandatory：`{mandatory}`",
        f"- 测试层级：{', '.join(f'`{x}`' for x in levels)}",
        f"- Lifecycle commands：{', '.join(f'`{x}`' for x in commands)}",
        "",
        "## 测试用例",
        "",
    ]
    for item in data["items"]:
        lines += [
            f"## {item['id']} {item['title']}",
            "",
            f"- 需求：{', '.join(f'`{x}`' for x in item['requirement_ids'])}",
            f"- 设计：{', '.join(f'`{x}`' for x in item['design_ids'])}",
            f"- 级别：`{item['level']}`",
            f"- Mandatory：`{str(item['mandatory']).lower()}`",
            f"- Lifecycle command：`{item['command']}`",
            f"- Selector：`{item['selector']}`",
            f"- 前置条件：{item['preconditions']}",
            f"- 输入：{item['input']}",
            f"- 预期：{item['expected']}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def publish_spec(
    root: Path,
    payload: dict[str, Any],
    *,
    feature_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ids = validate_spec(payload, root)
    validate_lifecycle_test_references(root, payload)
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
    generated = utc_now()
    artifacts = {
        "requirements": {
            **payload["requirements"],
            "schema_version": payload["schema_version"],
            "flow": payload["flow"],
            "spec_confirmed": payload["spec_confirmed"],
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
    staged: dict[str, str] = {}
    for kind, data in artifacts.items():
        base = CURRENT_FILES[kind]
        staged[f"{base}.json"] = __import__("json").dumps(
            data, ensure_ascii=False, indent=2
        ) + "\n"
        staged[f"{base}.md"] = renderers[kind](data)
    if feature_contract is not None:
        staged["feature-contract.json"] = __import__("json").dumps(
            feature_contract, ensure_ascii=False, indent=2
        ) + "\n"
    bundle = publish_bundle(
        root,
        kind="spec",
        files=staged,
        metadata={
            "schema_version": payload["schema_version"],
            "flow": payload["flow"],
            "generated_at": generated,
        },
    )
    hashes = current_spec_hashes(root)
    return {
        "ok": True,
        "ids": {k: sorted(v) for k, v in ids.items()},
        "hashes": hashes,
        "bundle_id": bundle["bundle_id"],
    }


def load_current_spec(root: Path) -> dict[str, Any]:
    materialize_bundle(root, "spec")
    requirements = read_json(current_artifact_path(root, "spec", "requirements.json"))
    design = read_json(current_artifact_path(root, "spec", "design.json"))
    test_plan = read_json(
        current_artifact_path(root, "spec", "test-plan.json")
    )
    combined = {
        "schema_version": requirements["schema_version"],
        "flow": requirements["flow"],
        "spec_confirmed": requirements["spec_confirmed"],
        "requirements": requirements,
        "design": design,
        "test_plan": test_plan,
    }
    validate_spec(combined, root)
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
