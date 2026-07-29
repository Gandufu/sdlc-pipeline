from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .artifact_documents import markdown_sha256, render_decision_document
from .artifact_store import publish_baseline
from .common import SdlcError, utc_now
from .journal import discard_spec_work, query_spec_work
from .layout import state_root, work_root
from .records import (
    read_compact_index,
    read_markdown_record,
    write_compact_index,
)
from .schema_validation import validate_schema_instance
from .spec_candidates import load_candidate_revision


def approve_and_promote(
    root: Path,
    *,
    candidate_id: str,
    content_hash: str,
    confirmed: bool,
) -> dict[str, Any]:
    receipt_path = _publication_receipt_path(root, candidate_id)
    receipt = read_compact_index(receipt_path, required=False)
    if receipt:
        validate_schema_instance(
            root, "publication-receipt.schema.json", receipt
        )
        if receipt.get("content_hash") != content_hash:
            raise SdlcError("已发布 candidate 的 receipt hash 不匹配")
        candidate_cleanup = {
            "deleted": receipt.get("cleanup_state") == "deleted",
            "cleanup_pending": receipt.get("cleanup_state") == "cleanup_pending",
        }
        spec_work_cleanup = {
            "deleted": receipt.get("spec_work_cleanup_state") == "deleted",
            "cleanup_pending": (
                receipt.get("spec_work_cleanup_state") == "cleanup_pending"
            ),
        }
        changed = False
        if candidate_cleanup["cleanup_pending"]:
            candidate_cleanup = _discard_candidate(
                work_root(root) / "candidates" / candidate_id
            )
            receipt["cleanup_state"] = (
                "deleted" if candidate_cleanup["deleted"] else "cleanup_pending"
            )
            changed = True
        if spec_work_cleanup["cleanup_pending"]:
            spec_work_cleanup = discard_spec_work(
                root, run_id=receipt.get("spec_run_id")
            )
            receipt["spec_work_cleanup_state"] = (
                "deleted"
                if spec_work_cleanup.get("deleted")
                else (
                    "cleanup_pending"
                    if spec_work_cleanup.get("cleanup_pending")
                    else "not_present"
                )
            )
            changed = True
        if changed:
            receipt["updated_at"] = utc_now()
            validate_schema_instance(
                root, "publication-receipt.schema.json", receipt
            )
            write_compact_index(receipt_path, receipt)
        return {
            "ok": True,
            "candidate_id": candidate_id,
            "content_hash": content_hash,
            "baseline_id": receipt["baseline_id"],
            "idempotent": True,
            "candidate_cleanup": candidate_cleanup,
            "spec_work_cleanup": spec_work_cleanup,
        }
    candidate_root = work_root(root) / "candidates" / candidate_id
    pointer_path = candidate_root / "index.json"
    pointer = read_compact_index(pointer_path)
    if (
        pointer.get("candidate_id") != candidate_id
        or pointer.get("current_hash") != content_hash
    ):
        raise SdlcError("candidate hash 不匹配；请重新 validate 并确认最新 preview")
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
    work_result = query_spec_work(root)
    spec_work = work_result.get("work") if work_result.get("available") else None
    current_decisions = {
        item["id"]: markdown_sha256(
            render_decision_document(
                item,
                list(spec_work.get("source_refs", [])),
            )
        )
        for item in (spec_work.get("decisions", []) if spec_work else [])
    }
    frozen_decisions = {
        item["id"]: item["sha256"] for item in revision["decisions"]
    }
    if current_decisions != frozen_decisions:
        raise SdlcError("Spec Work 决策已变化；请重新 validate 并确认新 hash")
    published = publish_baseline(root, candidate=revision)
    receipt = {
        "schema_version": "3.0",
        "candidate_id": candidate_id,
        "revision": revision["revision"],
        "state": "published",
        "content_hash": content_hash,
        "confirmed": True,
        "baseline_id": published["baseline_id"],
        "approved_at": utc_now(),
        "cleanup_state": "pending",
        "spec_work_cleanup_state": "pending",
    }
    if spec_work:
        receipt["spec_run_id"] = spec_work["run_id"]
    validate_schema_instance(root, "publication-receipt.schema.json", receipt)
    write_compact_index(receipt_path, receipt)
    cleanup = _discard_candidate(candidate_root)
    spec_work_cleanup = (
        discard_spec_work(root, run_id=receipt["spec_run_id"])
        if receipt.get("spec_run_id")
        else {"deleted": False, "reason": "no_spec_work"}
    )
    receipt["cleanup_state"] = (
        "deleted" if cleanup["deleted"] else "cleanup_pending"
    )
    receipt["spec_work_cleanup_state"] = (
        "deleted"
        if spec_work_cleanup.get("deleted")
        else (
            "cleanup_pending"
            if spec_work_cleanup.get("cleanup_pending")
            else "not_present"
        )
    )
    receipt["updated_at"] = utc_now()
    validate_schema_instance(root, "publication-receipt.schema.json", receipt)
    write_compact_index(receipt_path, receipt)
    return {
        "ok": True,
        "candidate_id": candidate_id,
        "content_hash": content_hash,
        "baseline_id": published["baseline_id"],
        "idempotent": False,
        "candidate_cleanup": cleanup,
        "spec_work_cleanup": spec_work_cleanup,
    }


def _publication_receipt_path(root: Path, candidate_id: str) -> Path:
    return state_root(root) / "publications" / f"{candidate_id}.json"


def retry_publication_cleanup(root: Path) -> dict[str, int]:
    publications = state_root(root) / "publications"
    result = {"retried": 0, "pending": 0}
    if not publications.is_dir():
        return result
    for receipt_path in sorted(publications.glob("SC-*.json")):
        receipt = read_compact_index(receipt_path)
        validate_schema_instance(
            root, "publication-receipt.schema.json", receipt
        )
        changed = False
        if receipt.get("cleanup_state") == "cleanup_pending":
            cleanup = _discard_candidate(
                work_root(root) / "candidates" / receipt["candidate_id"]
            )
            receipt["cleanup_state"] = (
                "deleted" if cleanup["deleted"] else "cleanup_pending"
            )
            changed = True
        if receipt.get("spec_work_cleanup_state") == "cleanup_pending":
            cleanup = discard_spec_work(
                root, run_id=receipt.get("spec_run_id")
            )
            receipt["spec_work_cleanup_state"] = (
                "deleted"
                if cleanup.get("deleted")
                else (
                    "cleanup_pending"
                    if cleanup.get("cleanup_pending")
                    else "not_present"
                )
            )
            changed = True
        if changed:
            result["retried"] += 1
            receipt["updated_at"] = utc_now()
            validate_schema_instance(
                root, "publication-receipt.schema.json", receipt
            )
            write_compact_index(receipt_path, receipt)
        if (
            receipt.get("cleanup_state") == "cleanup_pending"
            or receipt.get("spec_work_cleanup_state") == "cleanup_pending"
        ):
            result["pending"] += 1
    return result


def _discard_candidate(candidate_root: Path) -> dict[str, Any]:
    if not candidate_root.exists():
        return {"deleted": True, "cleanup_pending": False}
    try:
        shutil.rmtree(candidate_root)
    except OSError:
        return {"deleted": False, "cleanup_pending": True}
    return {"deleted": True, "cleanup_pending": False}
