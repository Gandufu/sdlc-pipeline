from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .common import (
    SdlcError,
    atomic_write,
    read_json,
    sha256_file,
    sha256_json,
    utc_now,
    write_json,
)


def publish_bundle(
    root: Path,
    *,
    kind: str,
    files: dict[str, str],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish an immutable multi-file bundle and atomically switch its pointer."""
    if not files or any(
        not name or Path(name).is_absolute() or ".." in Path(name).parts
        for name in files
    ):
        raise SdlcError("artifact bundle 文件名必须是项目内相对路径")
    encoded = {
        name: content.encode("utf-8")
        for name, content in sorted(files.items())
    }
    identity = {
        "kind": kind,
        "files": {
            name: sha256_json({"utf8": content.decode("utf-8")})
            for name, content in encoded.items()
        },
        "metadata": metadata or {},
    }
    bundle_id = sha256_json(identity)
    base = root / "docs" / "sdlc" / "bundles"
    final = base / bundle_id
    base.mkdir(parents=True, exist_ok=True)
    if not final.is_dir():
        temporary = Path(tempfile.mkdtemp(prefix=".publishing-", dir=base))
        try:
            for name, content in encoded.items():
                target = temporary / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            manifest = {
                "schema_version": "1.0",
                "bundle_id": bundle_id,
                "kind": kind,
                "created_at": utc_now(),
                "metadata": metadata or {},
                "files": {
                    name: {
                        "sha256": sha256_file(temporary / name),
                        "size": (temporary / name).stat().st_size,
                    }
                    for name in sorted(files)
                },
            }
            write_json(temporary / "bundle.json", manifest)
            os.replace(temporary, final)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)
    manifest = _verify_bundle(final, expected_kind=kind)
    pointer = {
        "schema_version": "1.0",
        "kind": kind,
        "bundle_id": bundle_id,
        "path": f"docs/sdlc/bundles/{bundle_id}",
        "updated_at": utc_now(),
        "files": manifest["files"],
    }
    atomic_write(
        root / "docs" / "sdlc" / f"{kind}-current.json",
        __import__("json").dumps(pointer, ensure_ascii=False, indent=2) + "\n",
    )
    materialize_bundle(root, kind)
    return {"bundle_id": bundle_id, "pointer": pointer}


def current_bundle(root: Path, kind: str) -> tuple[Path, dict[str, Any]] | None:
    pointer_path = root / "docs" / "sdlc" / f"{kind}-current.json"
    pointer = read_json(pointer_path, required=False)
    if not pointer:
        return None
    if pointer.get("kind") != kind or not isinstance(pointer.get("bundle_id"), str):
        raise SdlcError(f"{pointer_path} 不是有效的 {kind} bundle 指针")
    bundle = root / "docs" / "sdlc" / "bundles" / pointer["bundle_id"]
    manifest = _verify_bundle(bundle, expected_kind=kind)
    return bundle, manifest


def current_artifact_path(root: Path, kind: str, name: str) -> Path:
    selected = current_bundle(root, kind)
    if selected:
        bundle, manifest = selected
        if name not in manifest["files"]:
            raise SdlcError(f"当前 {kind} bundle 缺少文件: {name}")
        return bundle / name
    return root / "docs" / "sdlc" / "current" / name


def materialize_bundle(root: Path, kind: str) -> None:
    selected = current_bundle(root, kind)
    if not selected:
        return
    bundle, manifest = selected
    mirror = root / "docs" / "sdlc" / "current"
    for name, evidence in manifest["files"].items():
        source = bundle / name
        target = mirror / name
        if (
            target.is_file()
            and sha256_file(target) == evidence["sha256"]
        ):
            continue
        atomic_write(target, source.read_text(encoding="utf-8"))


def _verify_bundle(bundle: Path, *, expected_kind: str) -> dict[str, Any]:
    manifest = read_json(bundle / "bundle.json")
    if manifest.get("kind") != expected_kind:
        raise SdlcError(f"artifact bundle kind 不匹配: {bundle}")
    if manifest.get("bundle_id") != bundle.name:
        raise SdlcError(f"artifact bundle ID 与目录不匹配: {bundle}")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise SdlcError(f"artifact bundle 没有文件证据: {bundle}")
    for name, evidence in files.items():
        path = bundle / name
        try:
            path.resolve().relative_to(bundle.resolve())
        except ValueError as exc:
            raise SdlcError(f"artifact bundle 路径越界: {name}") from exc
        if not path.is_file() or sha256_file(path) != evidence.get("sha256"):
            raise SdlcError(f"artifact bundle 文件缺失或 hash 漂移: {name}")
    return manifest
