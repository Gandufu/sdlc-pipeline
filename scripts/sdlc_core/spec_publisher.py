from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifact_store import publish_bundle
from .common import SdlcError, atomic_write, read_json, sha256_file, utc_now
from .schema_validation import validate_schema_instance


def approve_and_promote(
    root: Path,
    *,
    candidate_id: str,
    content_hash: str,
    confirmed: bool,
) -> dict[str, Any]:
    candidate_root = (
        root / ".sdlc-pipeline" / "runs" / "spec-candidates" / candidate_id
    )
    pointer_path = candidate_root / "candidate.json"
    pointer = read_json(pointer_path)
    if (
        pointer.get("candidate_id") != candidate_id
        or pointer.get("current_hash") != content_hash
    ):
        raise SdlcError("candidate hash 不匹配；请重新 validate 并确认最新 preview")
    if confirmed is not True:
        raise SdlcError("approve 必须携带用户明确 confirmed=true")
    approval_path = candidate_root / "approval.json"
    if pointer.get("state") == "published":
        approval = read_json(approval_path)
        if approval.get("content_hash") != content_hash:
            raise SdlcError("已发布 candidate 的 approval hash 不匹配")
        return {
            "ok": True,
            "candidate_id": candidate_id,
            "revision": pointer["current_revision"],
            "bundle_id": approval["published_bundle_id"],
            "idempotent": True,
        }
    if pointer.get("state") != "ready":
        raise SdlcError("candidate 不是 ready 状态，不能批准")

    revision_number = int(pointer["current_revision"])
    revision = candidate_root / "revisions" / f"{revision_number:04d}"
    manifest = read_json(revision / "manifest.json")
    if manifest.get("content_hash") != content_hash:
        raise SdlcError("candidate manifest hash 与 ready pointer 不匹配")
    validation = read_json(revision / "validation.json")
    if validation.get("ok") is not True:
        raise SdlcError("candidate validation 未通过")
    if not (revision / "preview.md").is_file():
        raise SdlcError("candidate preview 缺失")
    _verify_revision(revision, manifest)

    files = _published_files(revision)
    bundle = publish_bundle(
        root,
        kind="spec",
        files=files,
        metadata={
            "schema_version": "2.0",
            "candidate_id": candidate_id,
            "candidate_revision": revision_number,
            "candidate_content_hash": content_hash,
        },
    )
    approval = {
        "schema_version": "2.0",
        "candidate_id": candidate_id,
        "revision": revision_number,
        "content_hash": content_hash,
        "decision": "approved",
        "confirmed": True,
        "confirmed_at": utc_now(),
        "published_bundle_id": bundle["bundle_id"],
    }
    validate_schema_instance(root, "v2/approval.schema.json", approval)
    atomic_write(
        approval_path,
        json.dumps(approval, ensure_ascii=False, indent=2) + "\n",
    )
    published_pointer = {
        **pointer,
        "state": "published",
        "published_bundle_id": bundle["bundle_id"],
        "updated_at": utc_now(),
    }
    validate_schema_instance(
        root, "v2/candidate-pointer.schema.json", published_pointer
    )
    atomic_write(
        pointer_path,
        json.dumps(published_pointer, ensure_ascii=False, indent=2) + "\n",
    )
    _remove_obsolete_spec_views(root)
    return {
        "ok": True,
        "candidate_id": candidate_id,
        "revision": revision_number,
        "content_hash": content_hash,
        "bundle_id": bundle["bundle_id"],
        "idempotent": False,
    }


def _verify_revision(revision: Path, manifest: dict[str, Any]) -> None:
    records = [manifest["feature_map"]]
    records += manifest["requirements"]
    records += manifest["designs"]
    records += manifest["verification"]
    for record in records:
        path = revision / record["path"]
        try:
            path.resolve().relative_to(revision.resolve())
        except ValueError as exc:
            raise SdlcError(f"candidate artifact 路径越界: {record['path']}") from exc
        if not path.is_file() or sha256_file(path) != record["sha256"]:
            raise SdlcError(f"candidate artifact 缺失或 hash 漂移: {record['path']}")


def _published_files(
    revision: Path,
) -> dict[str, str]:
    feature_map = read_json(revision / "feature-map.json")
    requirements = _documents(revision, "requirements")
    designs = _documents(revision, "designs")
    verification = _documents(revision, "verification")
    files = {
        "feature-map.json": _json(feature_map),
        "spec.md": (revision / "preview.md").read_text(encoding="utf-8"),
        "index.md": _render_index(feature_map, requirements, designs, verification),
    }
    for folder in ("requirements", "designs", "verification"):
        for path in sorted((revision / folder).glob("*.json")):
            files[f"{folder}/{path.name}"] = path.read_text(encoding="utf-8")
    return files


def _remove_obsolete_spec_views(root: Path) -> None:
    current = root / "docs" / "sdlc" / "current"
    for name in (
        "feature-contract.json",
        "requirements.json",
        "requirements.md",
        "design.json",
        "design.md",
        "test-plan.json",
        "test-plan.md",
    ):
        path = current / name
        if path.is_file():
            path.unlink()


def _documents(revision: Path, folder: str) -> list[dict[str, Any]]:
    return [
        read_json(path)
        for path in sorted((revision / folder).glob("*.json"))
    ]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _render_index(
    feature_map: dict[str, Any],
    requirements: list[dict[str, Any]],
    designs: list[dict[str, Any]],
    verification: list[dict[str, Any]],
) -> str:
    requirement_titles = {item["id"]: item["title"] for item in requirements}
    lines = [
        "# SDLC Spec Index",
        "",
        f"- Initiative：{feature_map['initiative_id']} {feature_map['title']}",
        f"- Requirements：{len(requirements)}",
        f"- Designs：{len(designs)}",
        f"- Verifications：{len(verification)}",
        "",
    ]
    for feature in feature_map["features"]:
        lines += [f"## {feature['id']} {feature['title']}", ""]
        lines += [
            f"- [{identifier} {requirement_titles[identifier]}](requirements/{identifier}.json)"
            for identifier in feature["requirement_ids"]
        ]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
