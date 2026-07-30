from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from .artifact_documents import (
    markdown_file_sha256,
    write_artifact_document,
)
from .common import SdlcError, atomic_write, read_json, sha256_file, sha256_json, utc_now
from .layout import lifecycle_path, scaffold_path
from .lifecycle_contract import normalize_test_selector
from .records import write_compact_index
from .schema_validation import validate_schema_instance
from .task_state import set_pending_spec, task_status, transition


_ID_PATTERNS = {
    "requirements": re.compile(r"^R-[0-9]{4}$"),
    "designs": re.compile(r"^D-[0-9]{4}$"),
    "verification": re.compile(r"^T-[0-9]{4}$"),
}


def prepare_spec(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    bundle = _normalize_and_validate(root, payload)
    content_hash = sha256_json(bundle)
    set_pending_spec(root, content_hash)
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
    payload: dict[str, Any],
    *,
    content_hash: str,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise SdlcError("发布 Spec 必须显式 confirmed=true")
    task = task_status(root)
    if not task or task.get("stage") != "awaiting_spec_approval":
        raise SdlcError("当前 Task 不在 Awaiting Spec Approval")
    bundle = _normalize_and_validate(root, payload)
    actual_hash = sha256_json(bundle)
    if actual_hash != content_hash or task.get("pending_spec_hash") != content_hash:
        raise SdlcError("Spec 内容已变化；请重新预览并确认最新 hash")
    published = _publish(root, bundle, content_hash)
    set_pending_spec(root, None)
    transition(root, "spec_approved")
    return {"ok": True, **published}


def _normalize_and_validate(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SdlcError("spec 必须是对象")
    title = str(payload.get("title", "")).strip()
    if not title:
        raise SdlcError("Spec title 不能为空")
    requirements = _numbered(payload.get("requirements"), "requirements")
    designs = _numbered(payload.get("designs"), "designs")
    verification = _numbered(payload.get("verification"), "verification")
    normalized_requirements = []
    for requirement in requirements:
        value = {
            **requirement,
            "schema_version": "3.0",
            "decision_ids": requirement.get("decision_ids", []),
            "supersedes": requirement.get("supersedes"),
        }
        value["acceptance_criteria"] = [
            {**criterion, "id": f"AC-{value['id']}-{index:02d}"}
            for index, criterion in enumerate(
                requirement.get("acceptance_criteria", []), 1
            )
        ]
        validate_schema_instance(root, "artifacts/requirement.schema.json", value)
        normalized_requirements.append(value)
    normalized_designs = []
    for design in designs:
        value = {
            **design,
            "schema_version": "3.0",
            "decision_ids": design.get("decision_ids", []),
        }
        validate_schema_instance(root, "artifacts/design.schema.json", value)
        normalized_designs.append(value)
    lifecycle = read_json(lifecycle_path(root))
    normalized_verification = []
    for item in verification:
        value = {**item, "schema_version": "3.0"}
        value["selector"] = normalize_test_selector(
            lifecycle,
            value["test_key"],
            value.get("selector"),
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


def _numbered(value: Any, group: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise SdlcError(f"Spec {group} 至少包含一项")
    result = []
    pattern = _ID_PATTERNS[group]
    prefix = {"requirements": "R", "designs": "D", "verification": "T"}[group]
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict):
            raise SdlcError(f"Spec {group}[{index}] 必须是对象")
        identifier = str(item.get("id", "")).strip() or f"{prefix}-{index:04d}"
        if not pattern.fullmatch(identifier):
            raise SdlcError(f"非法 {group} ID: {identifier}")
        result.append({**item, "id": identifier})
    if len({item["id"] for item in result}) != len(result):
        raise SdlcError(f"Spec {group} ID 重复")
    return result


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
