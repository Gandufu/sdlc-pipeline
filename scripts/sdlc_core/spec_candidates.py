from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .artifact_documents import (
    markdown_file_sha256,
    markdown_sha256,
    read_artifact_document,
    read_candidate_title,
    render_candidate_document,
    render_decision_document,
    write_artifact_document,
)
from .common import (
    SdlcError,
    atomic_write,
    read_json,
    sha256_file,
    sha256_json,
    utc_now,
)
from .journal import query_spec_work
from .layout import (
    lifecycle_path,
    relative_to_project,
    scaffold_path,
    state_root,
    work_root,
)
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
    publications = state_root(root) / "publications"
    if publications.is_dir():
        numbers.extend(
            int(match.group(1))
            for path in publications.glob("SC-*.json")
            if (match := _CANDIDATE_PATTERN.fullmatch(path.stem))
        )
    candidate_id = f"SC-{max(numbers, default=0) + 1:06d}"
    candidate_path = _candidate_root(root, candidate_id) / "candidate.md"
    atomic_write(
        candidate_path,
        render_candidate_document(candidate_id, title.strip()),
    )
    revision = _commit_revision(
        root,
        candidate_id,
        previous=None,
        candidate={
            "content_ref": relative_to_project(root, candidate_path),
            "sha256": markdown_file_sha256(candidate_path),
        },
        source_refs=source_refs,
        requirements=[],
        designs=[],
        verification=[],
        decisions=[],
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
    normalized.setdefault("decision_ids", [])
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
        candidate=previous["candidate"],
        source_refs=previous["source_refs"],
        requirements=records,
        designs=previous["designs"],
        verification=previous["verification"],
        decisions=previous["decisions"],
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
    normalized.setdefault("decision_ids", [])
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
        candidate=previous["candidate"],
        source_refs=previous["source_refs"],
        requirements=previous["requirements"],
        designs=_replace_record(previous["designs"], record),
        verification=previous["verification"],
        decisions=previous["decisions"],
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
    path = Path(selector)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.as_posix().startswith("tests/functional/")
        or not path.name.endswith(".functional.ts")
    ):
        raise SdlcError(
            f"{identifier} selector 必须是 tests/functional/ 下的 .functional.ts 项目内路径"
        )
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
        candidate=previous["candidate"],
        source_refs=previous["source_refs"],
        requirements=previous["requirements"],
        designs=previous["designs"],
        verification=_replace_record(previous["verification"], record),
        decisions=previous["decisions"],
    )
    return _put_result(candidate_id, revision, identifier)


def validate_candidate(root: Path, candidate_id: str) -> dict[str, Any]:
    _, previous = _load_current_revision(root, candidate_id)
    requirements = _load_artifacts(root, previous, "requirements")
    designs = _load_artifacts(root, previous, "designs")
    verification = _load_artifacts(root, previous, "verification")
    work_result = query_spec_work(root)
    decision_ids = {
        item["id"]
        for item in (
            work_result.get("work", {}).get("decisions", [])
            if work_result.get("available")
            else []
        )
    }
    decision_records = _snapshot_decisions(
        root,
        candidate_id,
        work_result.get("work") if work_result.get("available") else None,
        previous["decisions"],
    )
    diagnostics = _candidate_diagnostics(
        root,
        previous["feature_map"],
        requirements,
        designs,
        verification,
        decision_ids,
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
            _candidate_title(root, previous),
            previous["feature_map"],
            requirements,
            designs,
            verification,
            (
                work_result.get("work", {}).get("decisions", [])
                if work_result.get("available")
                else []
            ),
            report,
        ),
    )
    revision = _commit_revision(
        root,
        candidate_id,
        previous=previous,
        candidate=previous["candidate"],
        source_refs=previous["source_refs"],
        requirements=previous["requirements"],
        designs=previous["designs"],
        verification=previous["verification"],
        decisions=decision_records,
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
        candidate_root = _candidate_root(root, candidate_id)
        if not candidate_root.is_dir():
            return _publication_summary(root, candidate_id)
        pointer = read_compact_index(
            candidate_root / "index.json"
        )
        return _candidate_summary(root, pointer)
    pointers = (
        [
            read_compact_index(path / "index.json")
            for path in sorted(base.iterdir())
            if path.is_dir() and (path / "index.json").is_file()
        ]
        if base.is_dir()
        else []
    )
    active = [item for item in pointers if item.get("state") in {"draft", "ready"}]
    selected = active[-1] if active else (pointers[-1] if pointers else None)
    if selected:
        return _candidate_summary(root, selected)
    publications = state_root(root) / "publications"
    receipts = (
        sorted(publications.glob("SC-*.json"))
        if publications.is_dir()
        else []
    )
    if not receipts:
        return None
    return _publication_summary(root, receipts[-1].stem)


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


def _publication_summary(root: Path, candidate_id: str) -> dict[str, Any] | None:
    receipt = read_compact_index(
        state_root(root) / "publications" / f"{candidate_id}.json",
        required=False,
    )
    if not receipt:
        return None
    return {
        "schema_version": receipt["schema_version"],
        "candidate_id": receipt["candidate_id"],
        "state": "published",
        "current_revision": receipt["revision"],
        "current_hash": receipt["content_hash"],
        "published_baseline_id": receipt["baseline_id"],
        "cleanup_state": receipt["cleanup_state"],
        "updated_at": receipt.get("updated_at", receipt["approved_at"]),
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
    write_artifact_document(
        path,
        group,
        value,
    )
    return {
        "id": identifier,
        "artifact_revision": artifact_revision,
        "content_ref": relative_to_project(root, path),
        "sha256": markdown_file_sha256(path),
        **_artifact_relations(group, value),
    }


def _artifact_relations(group: str, value: dict[str, Any]) -> dict[str, Any]:
    if group == "requirements":
        return {
            "feature_id": value["feature_id"],
            "decision_ids": value.get("decision_ids", []),
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
            "requirement_ids": value["requirement_ids"],
            "decision_ids": value.get("decision_ids", []),
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
    candidate: dict[str, str],
    source_refs: list[dict[str, str]],
    requirements: list[dict[str, Any]],
    designs: list[dict[str, Any]],
    verification: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    state: str = "draft",
    validation: dict[str, Any] | None = None,
    preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    revision = 1 if previous is None else int(previous["revision"]) + 1
    feature_map = _rebuild_feature_map(requirements)
    validate_schema_instance(
        root, "artifacts/feature-map.schema.json", feature_map
    )
    content_identity = {
        "candidate": candidate,
        "feature_map": feature_map,
        "requirements": requirements,
        "designs": designs,
        "verification": verification,
        "decisions": decisions,
        "source_refs": source_refs,
    }
    value = {
        "schema_version": "3.0",
        "candidate_id": candidate_id,
        "revision": revision,
        "state": state,
        "candidate": candidate,
        "feature_map": feature_map,
        "requirements": sorted(requirements, key=lambda item: item["id"]),
        "designs": sorted(designs, key=lambda item: item["id"]),
        "verification": sorted(verification, key=lambda item: item["id"]),
        "decisions": sorted(decisions, key=lambda item: item["id"]),
        "source_refs": source_refs,
        "content_hash": f"sha256:{sha256_json(content_identity)}",
        "validation": validation,
        "preview": preview,
        "created_at": utc_now(),
    }
    validate_schema_instance(root, "candidate-revision.schema.json", value)
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
    requirements: list[dict[str, Any]]
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for requirement in requirements:
        grouped.setdefault(requirement["feature_id"], []).append(requirement)
    return {
        "schema_version": "3.0",
        "initiative_id": "I-0001",
        "features": [
            {
                "id": feature_id,
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


def _candidate_title(root: Path, revision: dict[str, Any]) -> str:
    record = revision.get("candidate")
    if not isinstance(record, dict):
        raise SdlcError("candidate revision 缺少 candidate Markdown 引用")
    path = root / record["content_ref"]
    if not path.is_file() or markdown_file_sha256(path) != record.get("sha256"):
        raise SdlcError("candidate Markdown 缺失或 hash 漂移")
    return read_candidate_title(path)


def _snapshot_decisions(
    root: Path,
    candidate_id: str,
    spec_work: dict[str, Any] | None,
    previous: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not spec_work:
        return []
    prior = {item["id"]: item for item in previous}
    records = []
    source_refs = list(spec_work.get("source_refs", []))
    for decision in spec_work.get("decisions", []):
        rendered = render_decision_document(decision, source_refs)
        digest = markdown_sha256(rendered)
        existing = prior.get(decision["id"])
        if existing and existing.get("sha256") == digest:
            records.append(existing)
            continue
        directory = (
            _candidate_root(root, candidate_id)
            / "artifacts"
            / "decisions"
            / decision["id"]
        )
        versions = (
            [
                int(path.stem)
                for path in directory.glob("*.md")
                if path.stem.isdigit()
            ]
            if directory.is_dir()
            else []
        )
        artifact_revision = max(versions, default=0) + 1
        path = directory / f"{artifact_revision:04d}.md"
        atomic_write(path, rendered)
        records.append({
            "id": decision["id"],
            "artifact_revision": artifact_revision,
            "content_ref": relative_to_project(root, path),
            "sha256": markdown_file_sha256(path),
        })
    return sorted(records, key=lambda item: item["id"])


def _load_artifacts(
    root: Path, revision: dict[str, Any], group: str
) -> dict[str, dict[str, Any]]:
    documents = {}
    for record in revision[group]:
        path = root / record["content_ref"]
        if not path.is_file() or markdown_file_sha256(path) != record["sha256"]:
            raise SdlcError(f"artifact 缺失或 hash 漂移: {record['content_ref']}")
        value = read_artifact_document(path, group)
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
    decision_ids: set[str],
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
    referenced_decisions = {
        decision_id
        for document in [*requirements.values(), *designs.values()]
        for decision_id in document.get("decision_ids", [])
    }
    unknown_decisions = sorted(referenced_decisions - decision_ids)
    if unknown_decisions:
        add("unknown_decision", f"R/D 引用未知 Spec Work 决策: {unknown_decisions}")

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
    candidate_title: str,
    feature_map: dict[str, Any],
    requirements: dict[str, dict[str, Any]],
    designs: dict[str, dict[str, Any]],
    verification: dict[str, dict[str, Any]],
    decisions: list[dict[str, Any]],
    report: dict[str, Any],
) -> str:
    lines = [
        f"# Spec Candidate {candidate_id}",
        "",
        f"- Initiative: {candidate_title}",
        f"- Revision: `{revision}`",
        f"- Validation: `{'pass' if report['ok'] else 'fail'}`",
        f"- Requirements: `{len(requirements)}`",
        f"- Designs: `{len(designs)}`",
        f"- Verifications: `{len(verification)}`",
        "",
    ]
    for feature in feature_map["features"]:
        feature_title = requirements[feature["requirement_ids"][0]]["title"]
        lines += [
            f"## {feature['id']} {feature_title}",
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
    if decisions:
        lines += ["## Decisions", ""]
        for decision in decisions:
            lines.append(
                f"- `{decision['id']}` {decision['prompt']} → {decision['answer']}"
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
