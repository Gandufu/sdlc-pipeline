from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .common import SdlcError, atomic_write, read_json, sha256_file, sha256_json, utc_now
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
    feature_map = {
        "schema_version": "2.0",
        "initiative_id": "I-0001",
        "title": title.strip(),
        "goal": title.strip(),
        "features": [],
    }
    validate_schema_instance(root, "v2/feature-map.schema.json", feature_map)
    revision = _commit_revision(
        root,
        candidate_id,
        previous=None,
        changed={"feature-map.json": feature_map},
        source_refs=source_refs,
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
    identifier = str(requirement.get("id", "")).strip()
    if not identifier:
        identifier = _next_identifier(previous / "requirements", _REQUIREMENT_PATTERN, "R")
    previous_feature_map = read_json(previous / "feature-map.json")
    requested_feature_id = str(requirement.get("feature_id", "")).strip()
    feature_id = (
        requested_feature_id
        if _FEATURE_PATTERN.fullmatch(requested_feature_id)
        else _next_feature_identifier(previous_feature_map)
    )
    normalized = {
        **requirement,
        "schema_version": "2.0",
        "id": identifier,
        # Feature identity is Core-owned just like R and AC IDs.  Agents often
        # provide a semantic slug while explicitly asking Core to allocate IDs.
        "feature_id": feature_id,
    }
    criteria = normalized.get("acceptance_criteria")
    if isinstance(criteria, list):
        normalized["acceptance_criteria"] = [
            {
                **item,
                # AC identity is a Core-owned foreign key for Verification.
                # Never let a stale caller-provided name make the candidate
                # fail schema validation before the deterministic mapping exists.
                "id": f"AC-{identifier}-{index:02d}",
            }
            if isinstance(item, dict) else item
            for index, item in enumerate(criteria, 1)
        ]
    normalized.setdefault("supersedes", None)
    validate_schema_instance(root, "v2/requirement.schema.json", normalized)
    _validate_source_refs(root, normalized["source_refs"])
    for criterion in normalized["acceptance_criteria"]:
        _validate_source_refs(root, criterion["source_refs"])

    feature_map = json.loads(json.dumps(previous_feature_map))
    feature_id = normalized["feature_id"]
    features = feature_map["features"]
    feature = next((item for item in features if item["id"] == feature_id), None)
    if feature is None:
        feature = {
            "id": feature_id,
            "title": normalized["title"],
            "requirement_ids": [],
            "depends_on": [],
            "status": "candidate",
        }
        features.append(feature)
    if identifier not in feature["requirement_ids"]:
        feature["requirement_ids"].append(identifier)
        feature["requirement_ids"].sort()
    validate_schema_instance(root, "v2/feature-map.schema.json", feature_map)
    if (
        read_json(previous / f"requirements/{identifier}.json", required=False)
        == normalized
        and feature_map == previous_feature_map
    ):
        pointer = read_json(_candidate_root(root, candidate_id) / "candidate.json")
        return {
            "ok": True,
            "candidate_id": candidate_id,
            "revision": pointer["current_revision"],
            "state": pointer["state"],
            "artifact_id": identifier,
            "idempotent": True,
        }
    revision = _commit_revision(
        root,
        candidate_id,
        previous=previous,
        changed={
            f"requirements/{identifier}.json": normalized,
            "feature-map.json": feature_map,
        },
        source_refs=_manifest_source_refs(previous),
    )
    return {
        "ok": True,
        "candidate_id": candidate_id,
        "revision": revision["revision"],
        "state": "draft",
        "artifact_id": identifier,
        "idempotent": False,
    }


def put_design(
    root: Path,
    candidate_id: str,
    design: dict[str, Any],
) -> dict[str, Any]:
    _, previous = _load_current_revision(root, candidate_id)
    normalized, identifier = _normalize_artifact(
        previous,
        design,
        folder="designs",
        pattern=_DESIGN_PATTERN,
        prefix="D",
    )
    validate_schema_instance(root, "v2/design.schema.json", normalized)
    return _put_artifact(
        root,
        candidate_id,
        previous,
        f"designs/{identifier}.json",
        normalized,
        identifier,
    )


def put_verification(
    root: Path,
    candidate_id: str,
    verification: dict[str, Any],
) -> dict[str, Any]:
    _, previous = _load_current_revision(root, candidate_id)
    normalized, identifier = _normalize_artifact(
        previous,
        verification,
        folder="verification",
        pattern=_VERIFICATION_PATTERN,
        prefix="T",
    )
    lifecycle = read_json(root / ".sdlc-pipeline" / "lifecycle.json")
    test_key = normalized.get("test_key")
    tests = lifecycle.get("tests", {}) if isinstance(lifecycle, dict) else {}
    test_definition = tests.get(test_key) if isinstance(test_key, str) else None
    if (
        isinstance(test_definition, dict)
        and test_definition.get("allow_selector") is not True
    ):
        # A test-key command owns its unit/integration selection.  Keeping a
        # model-supplied selector here creates an invalid candidate and can
        # even fail the path guard before validation explains the contract.
        normalized["selector"] = None
    validate_schema_instance(root, "v2/verification.schema.json", normalized)
    selector = normalized.get("selector")
    if selector is not None:
        path = Path(selector)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.as_posix().startswith("tests/")
        ):
            raise SdlcError(f"{identifier} selector 必须是 tests/ 下的项目内路径")
    return _put_artifact(
        root,
        candidate_id,
        previous,
        f"verification/{identifier}.json",
        normalized,
        identifier,
    )


def validate_candidate(root: Path, candidate_id: str) -> dict[str, Any]:
    _, previous = _load_current_revision(root, candidate_id)
    diagnostics = _candidate_diagnostics(root, previous)
    report = {
        "schema_version": "2.0",
        "candidate_id": candidate_id,
        "validated_revision": int(previous.name) + 1,
        "ok": not diagnostics,
        "diagnostics": diagnostics,
    }
    preview = _render_preview(previous, report)
    committed = _commit_revision(
        root,
        candidate_id,
        previous=previous,
        changed={},
        source_refs=_manifest_source_refs(previous),
        derived={
            "validation.json": json.dumps(
                report, ensure_ascii=False, indent=2
            ) + "\n",
            "preview.md": preview,
        },
        state="ready" if not diagnostics else "draft",
    )
    if diagnostics:
        raise SdlcError("；".join(item["message"] for item in diagnostics))
    return {
        "ok": True,
        "candidate_id": candidate_id,
        "revision": committed["revision"],
        "state": "ready",
        "content_hash": committed["manifest"]["content_hash"],
        "preview_path": (
            f".sdlc-pipeline/runs/spec-candidates/{candidate_id}/"
            f"revisions/{committed['revision']:04d}/preview.md"
        ),
    }


def candidate_status(root: Path, candidate_id: str | None = None) -> dict[str, Any] | None:
    base = _candidate_base(root)
    if candidate_id is not None:
        pointer = read_json(_candidate_root(root, candidate_id) / "candidate.json")
        return _candidate_summary(root, pointer)
    if not base.is_dir():
        return None
    pointers = [
        read_json(path / "candidate.json")
        for path in sorted(base.iterdir())
        if path.is_dir() and (path / "candidate.json").is_file()
    ]
    active = [
        item for item in pointers
        if item.get("state") in {"draft", "ready"}
    ]
    selected = active[-1] if active else (pointers[-1] if pointers else None)
    return _candidate_summary(root, selected) if selected else None


def _candidate_summary(root: Path, pointer: dict[str, Any]) -> dict[str, Any]:
    candidate_id = pointer["candidate_id"]
    revision_number = int(pointer["current_revision"])
    revision = (
        _candidate_root(root, candidate_id)
        / "revisions"
        / f"{revision_number:04d}"
    )
    manifest = read_json(revision / "manifest.json")
    preview = revision / "preview.md"
    validation = read_json(revision / "validation.json", required=False)
    return {
        **pointer,
        "preview_path": (
            preview.relative_to(root).as_posix() if preview.is_file() else None
        ),
        "validation_ok": (
            validation.get("ok") if isinstance(validation, dict) else None
        ),
        "counts": {
            "requirements": len(manifest["requirements"]),
            "designs": len(manifest["designs"]),
            "verification": len(manifest["verification"]),
        },
    }


def _normalize_artifact(
    previous: Path,
    value: dict[str, Any],
    *,
    folder: str,
    pattern: re.Pattern[str],
    prefix: str,
) -> tuple[dict[str, Any], str]:
    if not isinstance(value, dict):
        raise SdlcError(f"{prefix} artifact 必须是对象")
    identifier = str(value.get("id", "")).strip()
    if not identifier:
        identifier = _next_identifier(previous / folder, pattern, prefix)
    return {**value, "schema_version": "2.0", "id": identifier}, identifier


def _put_artifact(
    root: Path,
    candidate_id: str,
    previous: Path,
    relative: str,
    value: dict[str, Any],
    identifier: str,
) -> dict[str, Any]:
    existing = read_json(previous / relative, required=False)
    if existing == value:
        pointer = read_json(_candidate_root(root, candidate_id) / "candidate.json")
        return {
            "ok": True,
            "candidate_id": candidate_id,
            "revision": pointer["current_revision"],
            "state": pointer["state"],
            "artifact_id": identifier,
            "idempotent": True,
        }
    revision = _commit_revision(
        root,
        candidate_id,
        previous=previous,
        changed={relative: value},
        source_refs=_manifest_source_refs(previous),
    )
    return {
        "ok": True,
        "candidate_id": candidate_id,
        "revision": revision["revision"],
        "state": "draft",
        "artifact_id": identifier,
        "idempotent": False,
    }


def _candidate_base(root: Path) -> Path:
    return root / ".sdlc-pipeline" / "runs" / "spec-candidates"


def _candidate_root(root: Path, candidate_id: str) -> Path:
    if _CANDIDATE_PATTERN.fullmatch(candidate_id) is None:
        raise SdlcError(f"非法 candidate ID: {candidate_id!r}")
    return _candidate_base(root) / candidate_id


def _load_current_revision(
    root: Path, candidate_id: str
) -> tuple[dict[str, Any], Path]:
    candidate_root = _candidate_root(root, candidate_id)
    pointer = read_json(candidate_root / "candidate.json")
    revision = int(pointer["current_revision"])
    path = candidate_root / "revisions" / f"{revision:04d}"
    if not path.is_dir():
        raise SdlcError(f"candidate revision 缺失: {candidate_id}@{revision}")
    return pointer, path


def _next_identifier(directory: Path, pattern: re.Pattern[str], prefix: str) -> str:
    numbers: list[int] = []
    if directory.is_dir():
        for path in directory.glob("*.json"):
            match = pattern.fullmatch(path.stem)
            if match:
                numbers.append(int(match.group(1)))
    return f"{prefix}-{max(numbers, default=0) + 1:04d}"


def _next_feature_identifier(feature_map: dict[str, Any]) -> str:
    features = feature_map.get("features", [])
    numbers = [
        int(match.group(1))
        for feature in features
        if isinstance(feature, dict)
        and (match := _FEATURE_PATTERN.fullmatch(str(feature.get("id", ""))))
    ]
    return f"F-{max(numbers, default=0) + 1:04d}"


def _commit_revision(
    root: Path,
    candidate_id: str,
    *,
    previous: Path | None,
    changed: dict[str, dict[str, Any]],
    source_refs: list[dict[str, str]],
    derived: dict[str, str] | None = None,
    state: str = "draft",
) -> dict[str, Any]:
    candidate_root = _candidate_root(root, candidate_id)
    revisions = candidate_root / "revisions"
    revisions.mkdir(parents=True, exist_ok=True)
    current_revision = 0
    pointer_path = candidate_root / "candidate.json"
    if pointer_path.is_file():
        current_revision = int(read_json(pointer_path)["current_revision"])
    revision = current_revision + 1
    final = revisions / f"{revision:04d}"
    if final.exists():
        raise SdlcError(f"candidate revision 已存在: {candidate_id}@{revision}")
    temporary = Path(tempfile.mkdtemp(prefix=".writing-", dir=revisions))
    try:
        if previous is not None:
            for item in previous.iterdir():
                if item.name in {"manifest.json", "preview.md", "validation.json"}:
                    continue
                target = temporary / item.name
                if item.is_dir():
                    shutil.copytree(item, target)
                else:
                    shutil.copy2(item, target)
        for relative, value in changed.items():
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        for relative, content in (derived or {}).items():
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        manifest = _build_manifest(candidate_id, revision, temporary, source_refs)
        validate_schema_instance(root, "v2/candidate-manifest.schema.json", manifest)
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, final)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
    pointer = {
        "schema_version": "2.0",
        "candidate_id": candidate_id,
        "current_revision": revision,
        "state": state,
        "current_hash": manifest["content_hash"],
        "updated_at": utc_now(),
    }
    validate_schema_instance(root, "v2/candidate-pointer.schema.json", pointer)
    atomic_write(
        pointer_path,
        json.dumps(pointer, ensure_ascii=False, indent=2) + "\n",
    )
    return {"revision": revision, "manifest": manifest, "pointer": pointer}


def _build_manifest(
    candidate_id: str,
    revision: int,
    directory: Path,
    source_refs: list[dict[str, str]],
) -> dict[str, Any]:
    def records(folder: str) -> list[dict[str, str]]:
        base = directory / folder
        if not base.is_dir():
            return []
        return [
            {
                "id": path.stem,
                "path": path.relative_to(directory).as_posix(),
                "sha256": sha256_file(path),
            }
            for path in sorted(base.glob("*.json"))
        ]

    artifacts = {
        "feature_map": {
            "path": "feature-map.json",
            "sha256": sha256_file(directory / "feature-map.json"),
        },
        "requirements": records("requirements"),
        "designs": records("designs"),
        "verification": records("verification"),
        "source_refs": source_refs,
    }
    return {
        "schema_version": "2.0",
        "candidate_id": candidate_id,
        "revision": revision,
        **artifacts,
        "content_hash": f"sha256:{sha256_json(artifacts)}",
    }


def _manifest_source_refs(revision: Path) -> list[dict[str, str]]:
    value = read_json(revision / "manifest.json").get("source_refs", [])
    return value if isinstance(value, list) else []


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


def _load_documents(directory: Path, folder: str) -> dict[str, dict[str, Any]]:
    base = directory / folder
    if not base.is_dir():
        return {}
    return {path.stem: read_json(path) for path in sorted(base.glob("*.json"))}


def _candidate_diagnostics(root: Path, revision: Path) -> list[dict[str, str]]:
    feature_map = read_json(revision / "feature-map.json")
    requirements = _load_documents(revision, "requirements")
    designs = _load_documents(revision, "designs")
    verification = _load_documents(revision, "verification")
    diagnostics: list[dict[str, str]] = []

    def add(code: str, message: str) -> None:
        diagnostics.append({"code": code, "message": message})

    feature_ids = {item["id"] for item in feature_map["features"]}
    for feature in feature_map["features"]:
        if not feature["requirement_ids"]:
            add("feature_without_requirement", f"{feature['id']} 未关联 Requirement")
        unknown = set(feature["requirement_ids"]) - set(requirements)
        if unknown:
            add(
                "unknown_feature_requirement",
                f"{feature['id']} 引用未知 Requirement: {sorted(unknown)}",
            )
        unknown_dependencies = set(feature["depends_on"]) - feature_ids
        if unknown_dependencies:
            add(
                "unknown_feature_dependency",
                f"{feature['id']} 引用未知依赖: {sorted(unknown_dependencies)}",
            )
    _detect_feature_cycles(feature_map["features"], add)

    mapped_requirements: list[str] = [
        identifier
        for feature in feature_map["features"]
        for identifier in feature["requirement_ids"]
    ]
    duplicates = sorted({
        identifier
        for identifier in mapped_requirements
        if mapped_requirements.count(identifier) > 1
    })
    if duplicates:
        add("requirement_multiple_features", f"Requirement 属于多个 Feature: {duplicates}")
    if set(mapped_requirements) != set(requirements):
        add(
            "requirement_feature_mismatch",
            "Feature Map 与 Requirement 集合不一致",
        )

    scaffold = read_json(root / ".sdlc-pipeline" / "scaffold.json")
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

    lifecycle = read_json(root / ".sdlc-pipeline" / "lifecycle.json")
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
        unknown_r = set(test["requirement_ids"]) - set(requirements)
        unknown_d = set(test["design_ids"]) - set(designs)
        unknown_ac = set(test["acceptance_criteria_ids"]) - acceptance_ids
        if unknown_r or unknown_d or unknown_ac:
            add(
                "unknown_verification_reference",
                f"{identifier} 引用未知 R/D/AC: "
                f"{sorted(unknown_r | unknown_d | unknown_ac)}",
            )
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

    for requirement in requirements.values():
        _validate_source_refs(root, requirement["source_refs"])
        for criterion in requirement["acceptance_criteria"]:
            _validate_source_refs(root, criterion["source_refs"])
    return diagnostics


def _detect_feature_cycles(
    features: list[dict[str, Any]],
    add: Any,
) -> None:
    graph = {item["id"]: item["depends_on"] for item in features}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> bool:
        if identifier in visiting:
            return True
        if identifier in visited:
            return False
        visiting.add(identifier)
        if any(dependency in graph and visit(dependency) for dependency in graph[identifier]):
            return True
        visiting.remove(identifier)
        visited.add(identifier)
        return False

    if any(visit(identifier) for identifier in graph if identifier not in visited):
        add("feature_dependency_cycle", "Feature dependency 存在环")


def _render_preview(revision: Path, report: dict[str, Any]) -> str:
    feature_map = read_json(revision / "feature-map.json")
    requirements = _load_documents(revision, "requirements")
    designs = _load_documents(revision, "designs")
    verification = _load_documents(revision, "verification")
    lines = [
        f"# Spec Candidate {report['candidate_id']}",
        "",
        f"- Initiative：{feature_map['title']}",
        f"- Revision：`{int(revision.name) + 1}`",
        f"- Validation：`{'pass' if report['ok'] else 'fail'}`",
        f"- Requirements：`{len(requirements)}`",
        f"- Designs：`{len(designs)}`",
        f"- Verifications：`{len(verification)}`",
        "",
    ]
    for feature in feature_map["features"]:
        lines += [
            f"## {feature['id']} {feature['title']}",
            "",
            f"- Requirements：{', '.join(feature['requirement_ids'])}",
            "",
        ]
        for identifier in feature["requirement_ids"]:
            requirement = requirements.get(identifier)
            if requirement:
                lines += [
                    f"### {identifier} {requirement['title']}",
                    "",
                    requirement["goal"],
                    "",
                ]
    if report["diagnostics"]:
        lines += ["## Diagnostics", ""]
        lines += [f"- `{item['code']}` {item['message']}" for item in report["diagnostics"]]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
