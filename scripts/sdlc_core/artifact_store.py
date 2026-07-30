from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_documents import markdown_file_sha256
from .common import SdlcError, sha256_file
from .records import read_compact_index


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
    spec = path / manifest["spec_ref"]
    if not spec.is_file() or sha256_file(spec) != manifest["spec_sha256"]:
        raise SdlcError("baseline spec.md 缺失或 hash 漂移")
    return manifest
