from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from .artifact_documents import (
    markdown_file_sha256,
)
from .common import SdlcError, read_json, sha256_file, sha256_json, utc_now
from .layout import work_root
from .records import read_compact_index, write_compact_index


def publish_baseline(
    root: Path,
    *,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Publish one immutable Markdown baseline and one compact current pointer."""
    identity = {
        "candidate_id": candidate["candidate_id"],
        "revision": candidate["revision"],
        "content_hash": candidate["content_hash"],
    }
    baseline_id = sha256_json(identity)
    base = root / "docs" / "sdlc" / "baselines"
    final = base / baseline_id
    base.mkdir(parents=True, exist_ok=True)
    if not final.is_dir():
        temporary = base / f".publishing-{uuid.uuid4().hex}"
        temporary.mkdir()
        try:
            candidate_record = candidate["candidate"]
            candidate_source = root / candidate_record["content_ref"]
            if (
                not candidate_source.is_file()
                or markdown_file_sha256(candidate_source)
                != candidate_record["sha256"]
            ):
                raise SdlcError("candidate Markdown 缺失或 hash 漂移")
            candidate_target = temporary / "candidate.md"
            shutil.copy2(candidate_source, candidate_target)
            files: list[dict[str, Any]] = []
            for group in ("requirements", "designs", "verification"):
                for record in candidate[group]:
                    source = root / record["content_ref"]
                    if (
                        not source.is_file()
                        or markdown_file_sha256(source) != record["sha256"]
                    ):
                        raise SdlcError(
                            f"candidate artifact 缺失或 hash 漂移: {record['content_ref']}"
                        )
                    target = temporary / group / f"{record['id']}.md"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    files.append({
                        **record,
                        "content_ref": f"{group}/{record['id']}.md",
                        "sha256": markdown_file_sha256(target),
                        "size": target.stat().st_size,
                    })
            decisions: list[dict[str, Any]] = []
            available_decisions = {
                item["id"]: item for item in candidate["decisions"]
            }
            referenced_decisions = {
                decision_id
                for group in ("requirements", "designs")
                for record in candidate[group]
                for decision_id in record.get("decision_ids", [])
            }
            missing_decisions = sorted(
                referenced_decisions - set(available_decisions)
            )
            if missing_decisions:
                raise SdlcError(
                    f"发布缺少被 R/D 引用的 Spec Work 决策: {missing_decisions}"
                )
            for decision in available_decisions.values():
                source = root / decision["content_ref"]
                if (
                    not source.is_file()
                    or markdown_file_sha256(source) != decision["sha256"]
                ):
                    raise SdlcError(
                        f"candidate decision 缺失或 hash 漂移: {decision['id']}"
                    )
                target = temporary / "decisions" / f"{decision['id']}.md"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                decisions.append({
                    **decision,
                    "content_ref": f"decisions/{decision['id']}.md",
                    "sha256": markdown_file_sha256(target),
                    "size": target.stat().st_size,
                })
            source_ids = sorted({
                ref["source_id"] for ref in candidate["source_refs"]
            } | {
                ref["source_id"]
                for record in candidate["requirements"]
                for ref in (
                    record.get("source_refs", [])
                    + [
                        ref
                        for criterion in record.get("acceptance_criteria", [])
                        for ref in criterion.get("source_refs", [])
                    ]
                )
            })
            sources: list[dict[str, Any]] = []
            for source_id in source_ids:
                source_directory = work_root(root) / "sources" / source_id
                source_index = read_compact_index(
                    source_directory / "index.json"
                )
                target_directory = temporary / "sources" / source_id
                shutil.copytree(source_directory, target_directory)
                formal_index = dict(source_index)
                formal_index["state"] = "published"
                target_index = target_directory / "index.json"
                write_compact_index(target_index, formal_index)
                target_manifest = _verify_source_bundle(
                    target_directory,
                    formal_index,
                    source_id,
                )
                sources.append({
                    "source_id": source_id,
                    "index_ref": f"sources/{source_id}/index.json",
                    "index_sha256": sha256_file(target_index),
                    "manifest_ref": (
                        f"sources/{source_id}/"
                        f"{formal_index['manifest_ref']}"
                    ),
                    "manifest_sha256": sha256_file(target_manifest),
                })
            preview = candidate.get("preview")
            if not isinstance(preview, dict):
                raise SdlcError("ready candidate 缺少 preview")
            preview_source = root / preview["content_ref"]
            if (
                not preview_source.is_file()
                or sha256_file(preview_source) != preview["sha256"]
            ):
                raise SdlcError("candidate preview 缺失或 hash 漂移")
            shutil.copy2(preview_source, temporary / "spec.md")
            manifest = {
                "schema_version": "3.0",
                "baseline_id": baseline_id,
                "kind": "spec",
                "state": "published",
                "candidate_id": candidate["candidate_id"],
                "candidate_revision": candidate["revision"],
                "candidate_content_hash": candidate["content_hash"],
                "candidate": {
                    "content_ref": "candidate.md",
                    "sha256": markdown_file_sha256(candidate_target),
                },
                "feature_index": candidate["feature_map"],
                "source_refs": candidate["source_refs"],
                "sources": sources,
                "requirements": [
                    item for item in files
                    if item["id"].startswith("R-")
                ],
                "designs": [
                    item for item in files
                    if item["id"].startswith("D-")
                ],
                "verification": [
                    item for item in files
                    if item["id"].startswith("T-")
                ],
                "decisions": decisions,
                "spec_ref": "spec.md",
                "spec_sha256": sha256_file(temporary / "spec.md"),
                "created_at": utc_now(),
            }
            write_compact_index(temporary / "manifest.json", manifest)
            os.replace(temporary, final)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)
    manifest = _verify_baseline(final)
    pointer = {
        "schema_version": "3.0",
        "kind": "spec",
        "state": "published",
        "baseline_id": baseline_id,
        "path": f"docs/sdlc/baselines/{baseline_id}",
        "content_hash": manifest["candidate_content_hash"],
        "updated_at": utc_now(),
    }
    write_compact_index(root / "docs" / "sdlc" / "current.json", pointer)
    return {"baseline_id": baseline_id, "pointer": pointer}


def current_baseline(root: Path) -> tuple[Path, dict[str, Any]] | None:
    pointer = read_compact_index(
        root / "docs" / "sdlc" / "current.json", required=False
    )
    if not pointer:
        return None
    if pointer.get("kind") != "spec" or not isinstance(
        pointer.get("baseline_id"), str
    ):
        raise SdlcError("docs/sdlc/current.json 不是有效 spec baseline 指针")
    baseline = root / pointer["path"]
    manifest = _verify_baseline(baseline)
    if manifest["baseline_id"] != pointer["baseline_id"]:
        raise SdlcError("current baseline ID 不匹配")
    return baseline, manifest


def _verify_baseline(path: Path) -> dict[str, Any]:
    manifest = read_compact_index(path / "manifest.json")
    if manifest.get("baseline_id") != path.name:
        raise SdlcError(f"baseline ID 与目录不匹配: {path}")
    for group in ("requirements", "designs", "verification"):
        for record in manifest.get(group, []):
            artifact = path / record["content_ref"]
            try:
                artifact.resolve().relative_to(path.resolve())
            except ValueError as exc:
                raise SdlcError(
                    f"baseline artifact 路径越界: {record['content_ref']}"
                ) from exc
            if (
                not artifact.is_file()
                or markdown_file_sha256(artifact) != record["sha256"]
            ):
                raise SdlcError(
                    f"baseline artifact 缺失或 hash 漂移: {record['content_ref']}"
                )
    candidate = path / manifest["candidate"]["content_ref"]
    if (
        not candidate.is_file()
        or markdown_file_sha256(candidate) != manifest["candidate"]["sha256"]
    ):
        raise SdlcError("baseline candidate Markdown 缺失或 hash 漂移")
    for record in manifest.get("decisions", []):
        decision = path / record["content_ref"]
        if (
            not decision.is_file()
            or markdown_file_sha256(decision) != record["sha256"]
        ):
            raise SdlcError(
                f"baseline decision 缺失或 hash 漂移: {record['content_ref']}"
            )
    for source in manifest.get("sources", []):
        for field, hash_field in (
            ("index_ref", "index_sha256"),
            ("manifest_ref", "manifest_sha256"),
        ):
            artifact = path / source[field]
            if (
                not artifact.is_file()
                or sha256_file(artifact) != source[hash_field]
            ):
                raise SdlcError(
                    f"baseline source 缺失或 hash 漂移: {source[field]}"
                )
        source_index_path = path / source["index_ref"]
        source_index = read_compact_index(source_index_path)
        _verify_source_bundle(
            source_index_path.parent,
            source_index,
            source["source_id"],
        )
    spec = path / manifest["spec_ref"]
    if not spec.is_file() or sha256_file(spec) != manifest["spec_sha256"]:
        raise SdlcError("baseline spec.md 缺失或 hash 漂移")
    return manifest


def _verify_source_bundle(
    source_directory: Path,
    source_index: dict[str, Any],
    source_id: str,
) -> Path:
    manifest_path = source_directory / source_index["manifest_ref"]
    if (
        not manifest_path.is_file()
        or sha256_file(manifest_path) != source_index["manifest_sha256"]
    ):
        raise SdlcError(f"source manifest 缺失或漂移: {source_id}")
    manifest = read_json(manifest_path)
    entries = list(manifest.get("files", []))
    projection = manifest.get("projection")
    if isinstance(projection, dict):
        entries.append(projection)
    for entry in entries:
        artifact = source_directory / entry["file_ref"]
        if (
            not artifact.is_file()
            or sha256_file(artifact) != entry["sha256"]
        ):
            raise SdlcError(
                f"source 原文件缺失或漂移: "
                f"{source_id}#{entry['file_ref']}"
            )
    return manifest_path
