from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .common import SdlcError, atomic_write, read_json, sha256_file, sha256_json, utc_now
from .layout import lifecycle_path, relative_to_project, scaffold_path, work_root
from .records import (
    read_compact_index,
    read_markdown_record,
    write_compact_index,
    write_markdown_record,
)
from .schema_validation import validate_schema_instance
from .sources import load_source


_CANDIDATE_PATTERN = re.compile(r"^SC-([0-9]{6})$")
_FEATURE_PATTERN = re.compile(r"^F-([0-9]{4})$")
_REQUIREMENT_PATTERN = re.compile(r"^R-([0-9]{4})$")
_DESIGN_PATTERN = re.compile(r"^D-([0-9]{4})$")
_VERIFICATION_PATTERN = re.compile(r"^T-([0-9]{4})$")


def begin_candidate(
    root: Path,
    *,
    title: str,
    source_refs: list[dict[str, str]],
) -> dict[str, Any]:
    if not isinstance(title, str) or not title.strip():
        raise SdlcError("candidate title 必须是非空字符串")
    _validate_source_refs(root, source_refs)
    base = _candidate_base(root)
    base.mkdir(parents=True, exist_ok=True)
    numbers = [
        int(match.group(1))
        for child in base.iterdir()
        if child.is_dir() and (match := _CANDIDATE_PATTERN.fullmatch(child.name))
    ]
    candidate_id = f"SC-{max(numbers, default=0) + 1:06d}"
    revision = _commit_revision(
        root,
        candidate_id,
        previous=None,
        title=title.strip(),
        source_refs=source_refs,
        requirements=[],
        designs=[],
        verification=[],
    )
    return {
        "ok": True,
        "candidate_id": candidate_id,
        "revision": revision["revision"],
        "state": "draft",
    }


def put_requirement(
    root: Path,
    candidate_id: str,
    requirement: dict[str, Any],
) -> dict[str, Any]:
    pointer, previous = _load_current_revision(root, candidate_id)
    if not isinstance(requirement, dict):
        raise SdlcError("requirement 必须是对象")
    documents = _load_artifacts(root, previous, "requirements")
    requested_id = str(requirement.get("id", "")).strip()
    identifier = (
        requested_id
        if _REQUIREMENT_PATTERN.fullmatch(requested_id)
        else _next_identifier(documents, _REQUIREMENT_PATTERN, "R")
    )
    existing = documents.get(identifier)
    requested_feature = str(requirement.get("feature_id", "")).strip()
    feature_id = (
        str(existing["feature_id"])
        if existing is not None
        else (
            requested_feature
            if _FEATURE_PATTERN.fullmatch(requested_feature)
            else _next_feature_identifier(previous["feature_map"])
        )
    )
    normalized = {
        **requirement,
        "schema_version": "3.0",
        "id": identifier,
        "feature_id": feature_id,
    }
    criteria = normalized.get("acceptance_criteria")
    if isinstance(criteria, list):
        normalized["acceptance_criteria"] = [
            {
                **item,
                "id": f"AC-{identifier}-{index:02d}",
            }
            if isinstance(item, dict) else item
            for index, item in enumerate(criteria, 1)
        ]
    normalized.setdefault("supersedes", None)
    validate_schema_instance(root, "artifacts/requirement.schema.json", normalized)
    _validate_source_refs(root, normalized["source_refs"])
    for criterion in normalized["acceptance_criteria"]:
        _validate_source_refs(root, criterion["source_refs"])
    if existing == normalized:
        return _idempotent_result(pointer, identifier)
    record = _write_artifact(
        root, candidate_id, "requirements", identifier, normalized
    )
    records = _replace_record(previous["requirements"], record)
    revision = _commit_revision(
        root,
        candidate_id,
        previous=previous,
        title=previous["title"],
        source_refs=previous["source_refs"],
        requirements=records,
        designs=previous["designs"],
        verification=previous["verification"],
    )
    return _put_result(candidate_id, revision, identifier)


def put_design(
    root: Path,
    candidate_id: str,
    design: dict[str, Any],
) -> dict[str, Any]:
    pointer, previous = _load_current_revision(root, candidate_id)
    normalized, identifier = _normalize_artifact(
        root,
        previous,
        design,
        group="designs",
        pattern=_DESIGN_PATTERN,
        prefix="D",
    )
    validate_schema_instance(root, "artifacts/design.schema.json", normalized)
    existing = _load_artifacts(root, previous, "designs").get(identifier)
    if existing == normalized:
        return _idempotent_result(pointer, identifier)
    record = _write_artifact(
        root, candidate_id, "designs", identifier, normalized
    )
    revision = _commit_revision(
        root,
        candidate_id,
        previous=previous,
        title=previous["title"],
        source_refs=previous["source_refs"],
        requirements=previous["requirements"],
        designs=_replace_record(previous["designs"], record),
        verification=previous["verification"],
    )
    return _put_result(candidate_id, revision, identifier)


def put_verification(
    root: Path,
    candidate_id: str,
    verification: dict[str, Any],
) -> dict[str, Any]:
    pointer, previous = _load_current_revision(root, candidate_id)
    normalized, identifier = _normalize_artifact(
        root,
        previous,
        verification,
        group="verification",
        pattern=_VERIFICATION_PATTERN,
        prefix="T",
    )
    lifecycle = read_json(lifecycle_path(root))
    test_key = normalized.get("test_key")
    tests = lifecycle.get("tests", {}) if isinstance(lifecycle, dict) else {}
    test_definition = tests.get(test_key) if isinstance(test_key, str) else None
    if (
        isinstance(test_definition, dict)
        and test_definition.get("allow_selector") is not True
    ):
        normalized["selector"] = None
    validate_schema_instance(root, "artifacts/verification.schema.json", normalized)
    selector = normalized.get("selector")
    if selector is not None:
        path = Path(selector)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.as_posix().startswith("tests/")
        ):
            raise SdlcError(f"{identifier} selector 必须是 tests/ 下的项目内路径")
    existing = _load_artifacts(root, previous, "verification").get(identifier)
    if existing == normalized:
        return _idempotent_result(pointer, identifier)
    record = _write_artifact(
        root, candidate_id, "verification", identifier, normalized
    )
    revision = _commit_revision(
        root,
        candidate_id,
        previous=previous,
        title=previous["title"],
        source_refs=previous["source_refs"],
        requirements=previous["requirements"],
        designs=previous["designs"],
        verification=_replace_record(previous["verification"], record),
    )
    return _put_result(candidate_id, revision, identifier)


def validate_candidate(root: Path, candidate_id: str) -> dict[str, Any]:
    _, previous = _load_current_revision(root, candidate_id)
    requirements = _load_artifacts(root, previous, "requirements")
    designs = _load_artifacts(root, previous, "designs")
    verification = _load_artifacts(root, previous, "verification")
    diagnostics = _candidate_diagnostics(
        root,
        previous["feature_map"],
        requirements,
        designs,
        verification,
    )
    next_revision = int(previous["revision"]) + 1
    report = {
        "schema_version": "3.0",
        "candidate_id": candidate_id,
        "validated_revision": next_revision,
        "ok": not diagnostics,
        "diagnostics": diagnostics,
    }
    validation_path = (
        _candidate_root(root, candidate_id)
        / "validation"
        / f"{next_revision:04d}.md"
    )
    write_markdown_record(
        validation_path,
        report,
        title=f"Candidate validation {candidate_id}@{next_revision:04d}",
        summary_lines=[
            f"- Result: `{'pass' if report['ok'] else 'fail'}`",
            f"- Diagnostics: `{len(diagnostics)}`",
        ],
    )
    preview_path = (
        _candidate_root(root, candidate_id)
        / "previews"
        / f"{next_revision:04d}.md"
    )
    atomic_write(
        preview_path,
        _render_preview(
            candidate_id,
            next_revision,
            previous["feature_map"],
            requirements,
            designs,
            verification,
            report,
        ),
    )
    revision = _commit_revision(
        root,
        candidate_id,
        previous=previous,
        title=previous["title"],
        source_refs=previous["source_refs"],
        requirements=previous["requirements"],
        designs=previous["designs"],
        verification=previous["verification"],
        state="ready" if not diagnostics else "draft",
        validation={
            "ok": report["ok"],
            "content_ref": relative_to_project(root, validation_path),
            "sha256": sha256_file(validation_path),
        },
        preview={
            "content_ref": relative_to_project(root, preview_path),
            "sha256": sha256_file(preview_path),
        },
    )
    if diagnostics:
        raise SdlcError("；".join(item["message"] for item in diagnostics))
    return {
        "ok": True,
        "candidate_id": candidate_id,
        "revision": revision["revision"],
        "state": "ready",
        "content_hash": revision["content_hash"],
        "preview_path": revision["preview"]["content_ref"],
    }


def candidate_status(
    root: Path, candidate_id: str | None = None
) -> dict[str, Any] | None:
    base = _candidate_base(root)
    if candidate_id is not None:
        pointer = read_compact_index(
            _candidate_root(root, candidate_id) / "index.json"
        )
        return _candidate_summary(root, pointer)
    if not base.is_dir():
        return None
    pointers = [
        read_compact_index(path / "index.json")
        for path in sorted(base.iterdir())
        if path.is_dir() and (path / "index.json").is_file()
    ]
    active = [item for item in pointers if item.get("state") in {"draft", "ready"}]
    selected = active[-1] if active else (pointers[-1] if pointers else None)
    return _candidate_summary(root, selected) if selected else None


def load_candidate_revision(
    root: Path, candidate_id: str, revision: int | None = None
) -> dict[str, Any]:
    pointer = read_compact_index(_candidate_root(root, candidate_id) / "index.json")
    number = int(pointer["current_revision"] if revision is None else revision)
    return read_compact_index(
        _candidate_root(root, candidate_id)
        / "revisions"
        / f"{number:04d}.json"
    )


def load_revision_artifacts(
    root: Path, revision: dict[str, Any], group: str
) -> dict[str, dict[str, Any]]:
    return _load_artifacts(root, revision, group)


def _candidate_summary(root: Path, pointer: dict[str, Any]) -> dict[str, Any]:
    revision = load_candidate_revision(
        root, pointer["candidate_id"], int(pointer["current_revision"])
    )
    return {
        **pointer,
        "preview_path": (
            revision.get("preview", {}).get("content_ref")
            if isinstance(revision.get("preview"), dict)
            else None
        ),
        "validation_ok": (
            revision.get("validation", {}).get("ok")
            if isinstance(revision.get("validation"), dict)
            else None
        ),
        "counts": {
            "requirements": len(revision["requirements"]),
            "designs": len(revision["designs"]),
            "verification": len(revision["verification"]),
        },
    }


def _normalize_artifact(
    root: Path,
    previous: dict[str, Any],
    value: dict[str, Any],
    *,
    group: str,
    pattern: re.Pattern[str],
    prefix: str,
) -> tuple[dict[str, Any], str]:
    if not isinstance(value, dict):
        raise SdlcError(f"{prefix} artifact 必须是对象")
    documents = _load_artifacts(root, previous, group)
    identifier = str(value.get("id", "")).strip()
    if pattern.fullmatch(identifier) is None:
        identifier = _next_identifier(documents, pattern, prefix)
    return {**value, "schema_version": "3.0", "id": identifier}, identifier


def _write_artifact(
    root: Path,
    candidate_id: str,
    group: str,
    identifier: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    directory = _candidate_root(root, candidate_id) / "artifacts" / group / identifier
    versions = [
        int(path.stem)
        for path in directory.glob("*.md")
        if path.stem.isdigit()
    ] if directory.is_dir() else []
    artifact_revision = max(versions, default=0) + 1
    path = directory / f"{artifact_revision:04d}.md"
    write_markdown_record(
        path,
        value,
        title=f"{identifier} {value.get('title', '')}".strip(),
        summary_lines=[
            f"- Candidate: `{candidate_id}`",
            f"- Artifact revision: `{artifact_revision}`",
        ],
    )
    return {
        "id": identifier,
        "artifact_revision": artifact_revision,
        "content_ref": relative_to_project(root, path),
        "sha256": sha256_file(path),
        **_artifact_relations(group, value),
    }


def _artifact_relations(group: str, value: dict[str, Any]) -> dict[str, Any]:
    common = {"title": str(value.get("title", ""))[:256]}
    if group == "requirements":
        return {
            **common,
            "feature_id": value["feature_id"],
            "source_refs": value["source_refs"],
            "acceptance_criteria": [
                {
                    "id": item["id"],
                    "source_refs": item["source_refs"],
                }
                for item in value["acceptance_criteria"]
            ],
            "supersedes": value.get("supersedes"),
        }
    if group == "designs":
        return {
            **common,
            "requirement_ids": value["requirement_ids"],
            "extension_points": value["extension_points"],
        }
    if group == "verification":
        return {
            "requirement_ids": value["requirement_ids"],
            "design_ids": value["design_ids"],
            "acceptance_criteria_ids": value["acceptance_criteria_ids"],
            "level": value["level"],
            "test_key": value["test_key"],
            "selector": value.get("selector"),
            "mandatory": value["mandatory"],
        }
    raise SdlcError(f"未知 artifact group: {group}")


def _commit_revision(
    root: Path,
    candidate_id: str,
    *,
    previous: dict[str, Any] | None,
    title: str,
    source_refs: list[dict[str, str]],
    requirements: list[dict[str, Any]],
    designs: list[dict[str, Any]],
    verification: list[dict[str, Any]],
    state: str = "draft",
    validation: dict[str, Any] | None = None,
    preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    revision = 1 if previous is None else int(previous["revision"]) + 1
    full_feature_map = _rebuild_feature_map(title, requirements)
    validate_schema_instance(
        root, "artifacts/feature-map.schema.json", full_feature_map
    )
    feature_map = {
        key: value
        for key, value in full_feature_map.items()
        if key != "goal"
    }
    content_identity = {
        "feature_map": full_feature_map,
        "requirements": requirements,
        "designs": designs,
        "verification": verification,
        "source_refs": source_refs,
    }
    value = {
        "schema_version": "3.0",
        "candidate_id": candidate_id,
        "revision": revision,
        "state": state,
        "title": title[:256],
        "feature_map": feature_map,
        "requirements": sorted(requirements, key=lambda item: item["id"]),
        "designs": sorted(designs, key=lambda item: item["id"]),
        "verification": sorted(verification, key=lambda item: item["id"]),
        "source_refs": source_refs,
        "content_hash": f"sha256:{sha256_json(content_identity)}",
        "validation": validation,
        "preview": preview,
        "created_at": utc_now(),
    }
    path = (
        _candidate_root(root, candidate_id)
        / "revisions"
        / f"{revision:04d}.json"
    )
    if path.exists():
        raise SdlcError(f"candidate revision 已存在: {candidate_id}@{revision}")
    write_compact_index(path, value)
    pointer = {
        "schema_version": "3.0",
        "candidate_id": candidate_id,
        "current_revision": revision,
        "state": state,
        "current_hash": value["content_hash"],
        "updated_at": utc_now(),
    }
    write_compact_index(_candidate_root(root, candidate_id) / "index.json", pointer)
    return value


def _rebuild_feature_map(
    title: str, requirements: list[dict[str, Any]]
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for requirement in requirements:
        grouped.setdefault(requirement["feature_id"], []).append(requirement)
    return {
        "schema_version": "3.0",
        "initiative_id": "I-0001",
        "title": title,
        "goal": title,
        "features": [
            {
                "id": feature_id,
                "title": sorted(records, key=lambda item: item["id"])[0]["title"],
                "requirement_ids": sorted(item["id"] for item in records),
                "depends_on": [],
                "status": "candidate",
            }
            for feature_id, records in sorted(grouped.items())
        ],
    }


def _load_current_revision(
    root: Path, candidate_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate_root = _candidate_root(root, candidate_id)
    pointer = read_compact_index(candidate_root / "index.json")
    revision = read_compact_index(
        candidate_root
        / "revisions"
        / f"{int(pointer['current_revision']):04d}.json"
    )
    return pointer, revision


def _load_artifacts(
    root: Path, revision: dict[str, Any], group: str
) -> dict[str, dict[str, Any]]:
    documents = {}
    for record in revision[group]:
        path = root / record["content_ref"]
        if not path.is_file() or sha256_file(path) != record["sha256"]:
            raise SdlcError(f"artifact 缺失或 hash 漂移: {record['content_ref']}")
        value = read_markdown_record(path)
        documents[record["id"]] = value
    return documents


def _replace_record(
    records: list[dict[str, Any]], replacement: dict[str, Any]
) -> list[dict[str, Any]]:
    return sorted(
        [
            item for item in records
            if item["id"] != replacement["id"]
        ] + [replacement],
        key=lambda item: item["id"],
    )


def _next_identifier(
    documents: dict[str, Any], pattern: re.Pattern[str], prefix: str
) -> str:
    numbers = [
        int(match.group(1))
        for identifier in documents
        if (match := pattern.fullmatch(identifier))
    ]
    return f"{prefix}-{max(numbers, default=0) + 1:04d}"


def _next_feature_identifier(feature_map: dict[str, Any]) -> str:
    numbers = [
        int(match.group(1))
        for feature in feature_map.get("features", [])
        if (match := _FEATURE_PATTERN.fullmatch(str(feature.get("id", ""))))
    ]
    return f"F-{max(numbers, default=0) + 1:04d}"


def _candidate_base(root: Path) -> Path:
    return work_root(root) / "candidates"


def _candidate_root(root: Path, candidate_id: str) -> Path:
    if _CANDIDATE_PATTERN.fullmatch(candidate_id) is None:
        raise SdlcError(f"非法 candidate ID: {candidate_id!r}")
    return _candidate_base(root) / candidate_id


def _validate_source_refs(root: Path, refs: Any) -> None:
    if not isinstance(refs, list) or not refs:
        raise SdlcError("source_refs 至少包含一项")
    for ref in refs:
        if not isinstance(ref, dict):
            raise SdlcError("source_ref 必须是对象")
        source_id = str(ref.get("source_id", ""))
        anchor = str(ref.get("anchor", ""))
        source = load_source(root, source_id)
        if anchor not in {item["anchor"] for item in source["segments"]}:
            raise SdlcError(f"未知来源 anchor: {source_id}#{anchor}")


def _candidate_diagnostics(
    root: Path,
    feature_map: dict[str, Any],
    requirements: dict[str, dict[str, Any]],
    designs: dict[str, dict[str, Any]],
    verification: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []

    def add(code: str, message: str) -> None:
        diagnostics.append({"code": code, "message": message})

    mapped = [
        identifier
        for feature in feature_map["features"]
        for identifier in feature["requirement_ids"]
    ]
    if len(mapped) != len(set(mapped)):
        duplicates = sorted(
            identifier for identifier in set(mapped) if mapped.count(identifier) > 1
        )
        add("requirement_multiple_features", f"Requirement 属于多个 Feature: {duplicates}")
    if set(mapped) != set(requirements):
        add("requirement_feature_mismatch", "Feature Map 与 Requirement 集合不一致")

    scaffold = read_json(scaffold_path(root))
    extension_points = {
        item["id"] for item in scaffold.get("extension_points", [])
    }
    designed_requirements: set[str] = set()
    for identifier, design in designs.items():
        unknown = set(design["requirement_ids"]) - set(requirements)
        if unknown:
            add("unknown_design_requirement", f"{identifier} 引用未知 Requirement: {sorted(unknown)}")
        designed_requirements.update(design["requirement_ids"])
        unknown_extensions = set(design["extension_points"]) - extension_points
        if unknown_extensions:
            add("unknown_extension_point", f"{identifier} 引用未知 extension point: {sorted(unknown_extensions)}")
    missing_design = sorted(set(requirements) - designed_requirements)
    if missing_design:
        add("requirement_without_design", f"Requirement 未关联 Design: {missing_design}")

    lifecycle = read_json(lifecycle_path(root))
    test_commands = lifecycle.get("tests", {})
    acceptance_ids = {
        criterion["id"]
        for requirement in requirements.values()
        for criterion in requirement["acceptance_criteria"]
    }
    tested_requirements: set[str] = set()
    tested_designs: set[str] = set()
    covered_acceptance: set[str] = set()
    for identifier, test in verification.items():
        unknown = (
            set(test["requirement_ids"]) - set(requirements)
            | set(test["design_ids"]) - set(designs)
            | set(test["acceptance_criteria_ids"]) - acceptance_ids
        )
        if unknown:
            add("unknown_verification_reference", f"{identifier} 引用未知 R/D/AC: {sorted(unknown)}")
        if test["test_key"] not in test_commands:
            add("unknown_test_key", f"{identifier} 引用未知 lifecycle test_key: {test['test_key']}")
        elif test.get("selector") and test_commands[test["test_key"]].get("allow_selector") is not True:
            add("selector_not_allowed", f"{identifier} 的 test_key 不允许 selector")
        if test["mandatory"]:
            tested_requirements.update(test["requirement_ids"])
            tested_designs.update(test["design_ids"])
            covered_acceptance.update(test["acceptance_criteria_ids"])
    missing_test_r = sorted(set(requirements) - tested_requirements)
    missing_test_d = sorted(set(designs) - tested_designs)
    missing_ac = sorted(acceptance_ids - covered_acceptance)
    if missing_test_r:
        add("requirement_without_verification", f"Requirement 缺少 mandatory Verification: {missing_test_r}")
    if missing_test_d:
        add("design_without_verification", f"Design 缺少 mandatory Verification: {missing_test_d}")
    if missing_ac:
        add("acceptance_without_verification", f"Acceptance Criteria 缺少 mandatory Verification: {missing_ac}")
    return diagnostics


def _render_preview(
    candidate_id: str,
    revision: int,
    feature_map: dict[str, Any],
    requirements: dict[str, dict[str, Any]],
    designs: dict[str, dict[str, Any]],
    verification: dict[str, dict[str, Any]],
    report: dict[str, Any],
) -> str:
    lines = [
        f"# Spec Candidate {candidate_id}",
        "",
        f"- Initiative: {feature_map['title']}",
        f"- Revision: `{revision}`",
        f"- Validation: `{'pass' if report['ok'] else 'fail'}`",
        f"- Requirements: `{len(requirements)}`",
        f"- Designs: `{len(designs)}`",
        f"- Verifications: `{len(verification)}`",
        "",
    ]
    for feature in feature_map["features"]:
        lines += [
            f"## {feature['id']} {feature['title']}",
            "",
            f"- Requirements: {', '.join(feature['requirement_ids'])}",
            "",
        ]
        for identifier in feature["requirement_ids"]:
            requirement = requirements[identifier]
            lines += [
                f"### {identifier} {requirement['title']}",
                "",
                requirement["goal"],
                "",
                "Acceptance criteria:",
                *[
                    f"- `{item['id']}` Given {item['given']}; "
                    f"When {item['when']}; Then {item['then']}"
                    for item in requirement["acceptance_criteria"]
                ],
                "",
            ]
    if designs:
        lines += ["## Designs", ""]
        for identifier, design in designs.items():
            lines.append(
                f"- `{identifier}` {design['title']} → "
                f"{', '.join(design['requirement_ids'])}"
            )
        lines.append("")
    if verification:
        lines += ["## Verification", ""]
        for identifier, test in verification.items():
            lines.append(
                f"- `{identifier}` `{test['test_key']}` "
                f"mandatory=`{str(test['mandatory']).lower()}`"
            )
        lines.append("")
    if report["diagnostics"]:
        lines += [
            "## Diagnostics",
            "",
            *[
                f"- `{item['code']}` {item['message']}"
                for item in report["diagnostics"]
            ],
            "",
        ]
    return "\n".join(lines)


def _idempotent_result(
    pointer: dict[str, Any], identifier: str
) -> dict[str, Any]:
    return {
        "ok": True,
        "candidate_id": pointer["candidate_id"],
        "revision": pointer["current_revision"],
        "state": pointer["state"],
        "artifact_id": identifier,
        "idempotent": True,
    }


def _put_result(
    candidate_id: str, revision: dict[str, Any], identifier: str
) -> dict[str, Any]:
    return {
        "ok": True,
        "candidate_id": candidate_id,
        "revision": revision["revision"],
        "state": "draft",
        "artifact_id": identifier,
        "idempotent": False,
    }
