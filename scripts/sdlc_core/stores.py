from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .common import SdlcError, sha256_json, utc_now
from .layout import evidence_root, relative_to_project, state_root, work_root
from .records import (
    read_compact_index,
    read_markdown_record,
    write_compact_index,
    write_markdown_record,
)


_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def write_work_record(
    root: Path,
    record_id: str,
    value: dict[str, Any],
    *,
    state: str = "available",
    title: str | None = None,
) -> dict[str, Any]:
    return _write_record(
        root,
        record_id,
        value,
        state=state,
        title=title,
        content_base=work_root(root) / "records",
        index_base=state_root(root) / "records",
    )


def read_work_record(
    root: Path, record_id: str, *, required: bool = True
) -> dict[str, Any] | None:
    return _read_record(
        root,
        record_id,
        required=required,
        index_base=state_root(root) / "records",
    )


def write_evidence_record(
    root: Path,
    record_id: str,
    value: dict[str, Any],
    *,
    state: str,
    title: str | None = None,
) -> dict[str, Any]:
    return _write_record(
        root,
        record_id,
        value,
        state=state,
        title=title,
        content_base=evidence_root(root) / "records",
        index_base=state_root(root) / "evidence",
    )


def read_evidence_record(
    root: Path, record_id: str, *, required: bool = True
) -> dict[str, Any] | None:
    return _read_record(
        root,
        record_id,
        required=required,
        index_base=state_root(root) / "evidence",
    )


def record_index(
    root: Path,
    record_id: str,
    *,
    evidence: bool = False,
    required: bool = True,
) -> dict[str, Any] | None:
    _validate_id(record_id)
    base = state_root(root) / ("evidence" if evidence else "records")
    return read_compact_index(base / f"{record_id}.json", required=required)


def _write_record(
    root: Path,
    record_id: str,
    value: dict[str, Any],
    *,
    state: str,
    title: str | None,
    content_base: Path,
    index_base: Path,
) -> dict[str, Any]:
    _validate_id(record_id)
    content_path = content_base / f"{record_id}.md"
    write_markdown_record(
        content_path,
        value,
        title=title or record_id.replace("/", " · "),
        summary_lines=[f"- State: `{state}`"],
    )
    index = {
        "schema_version": "3.0",
        "record_id": record_id,
        "state": state,
        "content_ref": relative_to_project(root, content_path),
        "content_hash": sha256_json(value),
        "updated_at": utc_now(),
    }
    write_compact_index(index_base / f"{record_id}.json", index)
    return index


def _read_record(
    root: Path,
    record_id: str,
    *,
    required: bool,
    index_base: Path,
) -> dict[str, Any] | None:
    _validate_id(record_id)
    index = read_compact_index(
        index_base / f"{record_id}.json", required=required
    )
    if not index:
        return None
    value = read_markdown_record(root / index["content_ref"])
    if sha256_json(value) != index["content_hash"]:
        raise SdlcError(f"record Markdown 与索引 hash 不匹配: {record_id}")
    return value


def _validate_id(record_id: str) -> None:
    if not isinstance(record_id, str) or not _RECORD_ID.fullmatch(record_id):
        raise SdlcError(f"非法 record id: {record_id!r}")
    if ".." in Path(record_id).parts:
        raise SdlcError(f"record id 路径越界: {record_id!r}")
