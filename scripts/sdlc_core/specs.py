from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from .artifact_documents import (
    markdown_file_sha256,
    write_artifact_document,
)
from .common import SdlcError, atomic_write, read_json, sha256_file, sha256_json, utc_now
from .layout import lifecycle_path, scaffold_path, work_root
from .lifecycle_contract import normalize_test_selector
from .records import (
    read_markdown_record,
    write_compact_index,
    write_markdown_record,
)
from .schema_validation import validate_schema_instance
from .task_state import set_pending_spec, task_status, transition


def prepare_spec(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    task = task_status(root)
    stage = (task or {}).get("stage")
    if stage not in {"spec", "awaiting_spec_approval"}:
        raise SdlcError("当前 Task 不允许准备 Spec")
    bundle = _normalize_and_validate(root, payload)
    content_hash = sha256_json(bundle)
    write_markdown_record(
        _pending_spec_path(root),
        {
            "schema_version": "1.0",
            "kind": "pending-spec",
            "content_hash": content_hash,
            "bundle": bundle,
            "created_at": utc_now(),
        },
        title="Pending Spec",
        summary_lines=[
            "- State: `awaiting_spec_approval`",
            f"- Content hash: `{content_hash}`",
        ],
    )
    set_pending_spec(root, content_hash)
    if stage == "spec":
        transition(root, "spec_prepared")
    return {
        "ok": True,
        "state": "awaiting_spec_approval",
        "content_hash": content_hash,
        "preview": _render_preview(bundle),
        "affected_ids": {
            "R": [item["id"] for item in bundle["requirements"]],
            "D": [item["id"] for item in bundle["designs"]],
            "T": [item["id"] for item in bundle["verification"]],
        },
    }


def approve_spec(
    root: Path,
    *,
    content_hash: str,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise SdlcError("发布 Spec 必须显式 confirmed=true")
    task = task_status(root)
    if not task or task.get("stage") != "awaiting_spec_approval":
        raise SdlcError("当前 Task 不在 Awaiting Spec Approval")
    pending = read_markdown_record(_pending_spec_path(root))
    if (
        pending.get("kind") != "pending-spec"
        or pending.get("content_hash") != content_hash
        or task.get("pending_spec_hash") != content_hash
    ):
        raise SdlcError("Spec hash 与待审批正文不一致；请重新预览")
    bundle = pending.get("bundle")
    if not isinstance(bundle, dict):
        raise SdlcError("Pending Spec 缺少结构化正文；请重新预览")
    actual_hash = sha256_json(bundle)
    if actual_hash != content_hash:
        raise SdlcError("Pending Spec 正文校验失败；请重新预览")
    published = _publish(root, bundle, content_hash)
    transition(root, "spec_approved")
    set_pending_spec(root, None)
    _pending_spec_path(root).unlink(missing_ok=True)
    return {"ok": True, **published}


def _pending_spec_path(root: Path) -> Path:
    return work_root(root) / "pending-spec.md"


def _normalize_and_validate(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SdlcError("spec 必须是对象")
    title = str(payload.get("title", "")).strip()
    if not title:
        raise SdlcError("Spec title 不能为空")
    requirements, requirement_aliases = _numbered(
        payload.get("requirements"), "requirements"
    )
    designs, design_aliases = _numbered(payload.get("designs"), "designs")
    verification, _ = _numbered(payload.get("verification"), "verification")
    feature_aliases: dict[str, str] = {}
    for index, requirement in enumerate(requirements, 1):
        alias = str(requirement.get("feature_id", "")).strip() or f"feature-{index}"
        requirement["feature_id"] = feature_aliases.setdefault(
            alias, f"F-{len(feature_aliases) + 1:04d}"
        )
    normalized_requirements = []
    criterion_aliases: dict[str, str] = {}
    for requirement in requirements:
        original_requirement_id = requirement.pop("_input_id", "")
        value = {
            **requirement,
            "schema_version": "3.0",
            "decision_ids": requirement.get("decision_ids", []),
            "supersedes": requirement.get("supersedes"),
        }
        value["acceptance_criteria"] = [
            {
                **criterion,
                "id": _criterion_id(
                    criterion_aliases,
                    criterion,
                    value["id"],
                    original_requirement_id,
                    index,
                ),
            }
            for index, criterion in enumerate(
                requirement.get("acceptance_criteria", []), 1
            )
        ]
        validate_schema_instance(root, "artifacts/requirement.schema.json", value)
        normalized_requirements.append(value)
    normalized_designs = []
    all_requirement_ids = [
        requirement["id"] for requirement in normalized_requirements
    ]
    for design in designs:
        design.pop("_input_id", None)
        value = {
            **design,
            "schema_version": "3.0",
            "decision_ids": design.get("decision_ids", []),
            "requirement_ids": _normalize_requirement_refs(
                design.get("requirement_ids"),
                requirement_aliases,
                all_requirement_ids,
            ),
        }
        value["extension_points"] = _normalize_extension_points(root, value)
        validate_schema_instance(root, "artifacts/design.schema.json", value)
        normalized_designs.append(value)
    lifecycle = read_json(lifecycle_path(root))
    normalized_verification = []
    for item in verification:
        item.pop("_input_id", None)
        requirement_ids = _normalize_requirement_refs(
            item.get("requirement_ids"),
            requirement_aliases,
            all_requirement_ids,
        )
        design_ids = [
            design["id"]
            for design in normalized_designs
            if set(design["requirement_ids"]) & set(requirement_ids)
        ]
        acceptance_criteria_ids = [
            criterion["id"]
            for requirement in normalized_requirements
            if requirement["id"] in requirement_ids
            for criterion in requirement["acceptance_criteria"]
        ]
        level = item.get("level")
        if level not in {"unit", "functional"}:
            raise SdlcError(f"{item['id']} level 必须是 unit 或 functional")
        test_key = level
        selector = (
            f"tests/{item['id']}.test.ts"
            if level == "unit"
            else f"tests/functional/{item['id']}.functional.ts"
        )
        value = {
            **item,
            "schema_version": "3.0",
            "requirement_ids": requirement_ids,
            "design_ids": design_ids,
            "acceptance_criteria_ids": acceptance_criteria_ids,
            "test_key": test_key,
            "selector": selector,
        }
        value["selector"] = normalize_test_selector(
            lifecycle,
            test_key,
            selector,
            test_id=value["id"],
        )
        validate_schema_instance(root, "artifacts/verification.schema.json", value)
        normalized_verification.append(value)
    _validate_relations(root, normalized_requirements, normalized_designs, normalized_verification)
    return {
        "schema_version": "3.0",
        "title": title,
        "requirements": normalized_requirements,
        "designs": normalized_designs,
        "verification": normalized_verification,
    }


def _numbered(
    value: Any, group: str
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise SdlcError(f"Spec {group} 至少包含一项")
    result: list[dict[str, Any]] = []
    aliases: dict[str, str] = {}
    prefix = {"requirements": "R", "designs": "D", "verification": "T"}[group]
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict):
            raise SdlcError(f"Spec {group}[{index}] 必须是对象")
        identifier = f"{prefix}-{index:04d}"
        input_id = str(item.get("id", "")).strip()
        if input_id:
            if input_id in aliases:
                raise SdlcError(f"Spec {group} 输入 ID 重复: {input_id}")
            aliases[input_id] = identifier
        aliases[identifier] = identifier
        result.append({**item, "id": identifier, "_input_id": input_id})
    return result, aliases


def _criterion_id(
    aliases: dict[str, str],
    criterion: dict[str, Any],
    requirement_id: str,
    input_requirement_id: str,
    index: int,
) -> str:
    identifier = f"AC-{requirement_id}-{index:02d}"
    input_id = str(criterion.get("id", "")).strip()
    for alias in (
        input_id,
        f"{input_requirement_id}-AC{index}" if input_requirement_id else "",
        identifier,
    ):
        if alias:
            aliases[alias] = identifier
    return identifier


def _normalize_requirement_refs(
    values: Any,
    aliases: dict[str, str],
    all_requirement_ids: list[str],
) -> list[str]:
    result = []
    for value in values if isinstance(values, list) else []:
        alias = str(value).strip()
        if alias not in aliases:
            continue
        canonical = aliases[alias]
        if canonical not in result:
            result.append(canonical)
    return result or all_requirement_ids


def _normalize_extension_points(
    root: Path,
    design: dict[str, Any],
) -> list[str]:
    allowed = [
        item["id"]
        for item in read_json(scaffold_path(root)).get("extension_points", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    selected = [
        value
        for value in design.get("extension_points", [])
        if value in allowed
    ]
    return list(dict.fromkeys(selected)) or allowed


def _validate_relations(
    root: Path,
    requirements: list[dict[str, Any]],
    designs: list[dict[str, Any]],
    verification: list[dict[str, Any]],
) -> None:
    requirement_ids = {item["id"] for item in requirements}
    design_ids = {item["id"] for item in designs}
    criterion_ids = {
        item["id"]
        for requirement in requirements
        for item in requirement["acceptance_criteria"]
    }
    extension_ids = {
        item["id"] for item in read_json(scaffold_path(root)).get("extension_points", [])
    }
    for design in designs:
        missing = set(design["requirement_ids"]) - requirement_ids
        if missing:
            raise SdlcError(f"{design['id']} 引用了未知 Requirement: {sorted(missing)}")
        unknown = set(design["extension_points"]) - extension_ids
        if unknown:
            raise SdlcError(f"{design['id']} 引用了未知 extension point: {sorted(unknown)}")
    for item in verification:
        if missing := set(item["requirement_ids"]) - requirement_ids:
            raise SdlcError(f"{item['id']} 引用了未知 Requirement: {sorted(missing)}")
        if missing := set(item["design_ids"]) - design_ids:
            raise SdlcError(f"{item['id']} 引用了未知 Design: {sorted(missing)}")
        if missing := set(item["acceptance_criteria_ids"]) - criterion_ids:
            raise SdlcError(f"{item['id']} 引用了未知 AC: {sorted(missing)}")


def _publish(root: Path, bundle: dict[str, Any], content_hash: str) -> dict[str, Any]:
    baseline_id = content_hash
    base = root / "docs" / "sdlc" / "baselines"
    final = base / baseline_id
    base.mkdir(parents=True, exist_ok=True)
    if not final.is_dir():
        temporary = base / f".publishing-{uuid.uuid4().hex}"
        temporary.mkdir()
        try:
            records: dict[str, list[dict[str, Any]]] = {
                "requirements": [],
                "designs": [],
                "verification": [],
            }
            for group in records:
                for item in bundle[group]:
                    path = temporary / group / f"{item['id']}.md"
                    write_artifact_document(path, group, item)
                    records[group].append({
                        "id": item["id"],
                        "content_ref": f"{group}/{item['id']}.md",
                        "sha256": markdown_file_sha256(path),
                        "size": path.stat().st_size,
                    })
            spec_path = temporary / "spec.md"
            atomic_write(spec_path, _render_preview(bundle))
            feature_ids = sorted({item["feature_id"] for item in bundle["requirements"]})
            manifest = {
                "schema_version": "3.0",
                "baseline_id": baseline_id,
                "kind": "spec",
                "state": "published",
                "content_hash": content_hash,
                "feature_index": {
                    "schema_version": "3.0",
                    "initiative_id": "I-0001",
                    "features": [
                        {
                            "id": feature_id,
                            "requirement_ids": [
                                item["id"] for item in bundle["requirements"]
                                if item["feature_id"] == feature_id
                            ],
                            "depends_on": [],
                            "status": "published",
                        }
                        for feature_id in feature_ids
                    ],
                },
                **records,
                "spec_ref": "spec.md",
                "spec_sha256": sha256_file(spec_path),
                "created_at": utc_now(),
            }
            write_compact_index(temporary / "manifest.json", manifest)
            os.replace(temporary, final)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)
    pointer = {
        "schema_version": "3.0",
        "kind": "spec",
        "state": "published",
        "baseline_id": baseline_id,
        "path": f"docs/sdlc/baselines/{baseline_id}",
        "content_hash": content_hash,
        "updated_at": utc_now(),
    }
    write_compact_index(root / "docs" / "sdlc" / "current.json", pointer)
    return {"baseline_id": baseline_id, "content_hash": content_hash}


def _render_preview(bundle: dict[str, Any]) -> str:
    lines = [f"# {bundle['title']}", "", "## Requirements", ""]
    lines.extend(
        f"- `{item['id']}` {item['title']}: {item['goal']}"
        for item in bundle["requirements"]
    )
    lines.extend(["", "## Design", ""])
    lines.extend(f"- `{item['id']}` {item['title']}" for item in bundle["designs"])
    lines.extend(["", "## Verification", ""])
    lines.extend(
        f"- `{item['id']}` {item['level']} / {item['test_key']}: {item['expected']}"
        for item in bundle["verification"]
    )
    return "\n".join(lines).rstrip() + "\n"
