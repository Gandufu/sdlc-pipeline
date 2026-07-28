from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_store import publish_baseline
from .common import SdlcError, sha256_json, utc_now
from .layout import relative_to_project, work_root
from .records import (
    read_compact_index,
    read_markdown_record,
    write_compact_index,
    write_markdown_record,
)
from .spec_candidates import load_candidate_revision


def approve_and_promote(
    root: Path,
    *,
    candidate_id: str,
    content_hash: str,
    confirmed: bool,
) -> dict[str, Any]:
    candidate_root = work_root(root) / "candidates" / candidate_id
    pointer_path = candidate_root / "index.json"
    pointer = read_compact_index(pointer_path)
    if (
        pointer.get("candidate_id") != candidate_id
        or pointer.get("current_hash") != content_hash
    ):
        raise SdlcError("candidate hash 不匹配；请重新 validate 并确认最新 preview")
    approval_index_path = candidate_root / "approval.json"
    existing_index = read_compact_index(approval_index_path, required=False)
    if pointer.get("state") == "published":
        if not existing_index or existing_index.get("content_hash") != content_hash:
            raise SdlcError("已发布 candidate 的 approval hash 不匹配")
        return {
            "ok": True,
            "candidate_id": candidate_id,
            "content_hash": content_hash,
            "baseline_id": existing_index["baseline_id"],
            "idempotent": True,
        }
    if not confirmed:
        raise SdlcError("发布 Spec 必须显式 confirmed=true")
    if pointer.get("state") != "ready":
        raise SdlcError("candidate 不是 ready 状态，不能批准")
    revision = load_candidate_revision(
        root, candidate_id, int(pointer["current_revision"])
    )
    validation = revision.get("validation")
    if not isinstance(validation, dict) or validation.get("ok") is not True:
        raise SdlcError("candidate validation 未通过")
    validation_record = read_markdown_record(root / validation["content_ref"])
    if validation_record.get("ok") is not True:
        raise SdlcError("candidate validation Markdown 未通过")
    published = publish_baseline(root, candidate=revision)
    approval = {
        "schema_version": "3.0",
        "candidate_id": candidate_id,
        "candidate_revision": revision["revision"],
        "content_hash": content_hash,
        "confirmed": True,
        "baseline_id": published["baseline_id"],
        "approved_at": utc_now(),
    }
    approval_path = candidate_root / "approval.md"
    write_markdown_record(
        approval_path,
        approval,
        title=f"Spec approval {candidate_id}",
        summary_lines=[
            f"- Revision: `{revision['revision']}`",
            f"- Content hash: `{content_hash}`",
            f"- Baseline: `{published['baseline_id']}`",
        ],
    )
    approval_index = {
        "schema_version": "3.0",
        "candidate_id": candidate_id,
        "state": "published",
        "revision": revision["revision"],
        "content_hash": content_hash,
        "baseline_id": published["baseline_id"],
        "approval_ref": relative_to_project(root, approval_path),
        "approval_hash": sha256_json(approval),
        "approved_at": approval["approved_at"],
    }
    write_compact_index(approval_index_path, approval_index)
    published_pointer = {
        **pointer,
        "state": "published",
        "published_baseline_id": published["baseline_id"],
        "approval_ref": approval_index["approval_ref"],
        "updated_at": utc_now(),
    }
    write_compact_index(pointer_path, published_pointer)
    return {
        "ok": True,
        "candidate_id": candidate_id,
        "content_hash": content_hash,
        "baseline_id": published["baseline_id"],
        "idempotent": False,
    }
