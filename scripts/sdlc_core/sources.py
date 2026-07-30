from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
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
from .layout import relative_to_project, work_root
from .records import read_compact_index, write_compact_index


MAX_EXTERNAL_SOURCE_BYTES = 10 * 1024 * 1024
MAX_DIRECTORY_SOURCE_BYTES = 32 * 1024 * 1024
MAX_DIRECTORY_SOURCE_FILES = 64
MAX_DIRECTORY_SOURCE_ANCHORS = 128
MAX_SOURCE_SEGMENT_CHARS = 8_000
DIRECTORY_SOURCE_MEDIA_TYPE = "application/vnd.sdlc.source-directory"
TEXT_SOURCE_SUFFIXES = {
    ".conf", ".css", ".csv", ".go", ".graphql", ".html", ".ini", ".java",
    ".js", ".json", ".jsx", ".kt", ".md", ".mjs", ".ps1", ".py", ".rs",
    ".sh", ".sql", ".svelte", ".svg", ".toml", ".ts", ".tsv", ".tsx",
    ".txt", ".vue", ".xml", ".yaml", ".yml",
}


def ingest_source(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Copy a source without changing its format and return a bounded receipt."""
    requested_kind = str(payload.get("kind", "inline")).strip() or "inline"
    source = str(payload.get("source", "")).strip()
    uri = payload.get("uri")
    if requested_kind in {"file", "directory"}:
        if (not isinstance(uri, str) or not uri.strip()) and source:
            uri = source
            source = ""
        return _ingest_path_source(
            root,
            requested_kind=requested_kind,
            uri=uri,
            source=source,
            payload=payload,
        )
    return _ingest_text_source(
        root,
        kind=requested_kind,
        source=source,
        uri=uri,
        payload=payload,
    )


def validate_source_envelopes(root: Path, sources: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for source in sources:
        identifier = source.get("source_id")
        if not isinstance(identifier, str) or identifier in seen:
            raise SdlcError(f"重复或非法 source: {identifier}")
        seen.add(identifier)
        for segment in source.get("segments", []):
            if segment.get("kind") == "text":
                text = segment.get("text")
                if (
                    not isinstance(text, str)
                    or _sha256_text(text) != segment.get("sha256")
                ):
                    raise SdlcError(
                        f"{identifier} segment {segment.get('anchor')} "
                        "SHA-256 不匹配"
                    )
            elif segment.get("kind") != "asset":
                raise SdlcError(
                    f"{identifier} segment {segment.get('anchor')} 类型非法"
                )


def source_index(sources: list[dict[str, Any]]) -> dict[str, set[str]]:
    return {
        item["source_id"]: {segment["anchor"] for segment in item["segments"]}
        for item in sources
    }


def load_source(root: Path, source_id: str) -> dict[str, Any]:
    index_path = work_root(root) / "sources" / source_id / "index.json"
    if not index_path.is_file():
        raise SdlcError(f"未知 source: {source_id}")
    return load_indexed_source(root, index_path)


def load_indexed_source(root: Path, index_path: Path) -> dict[str, Any]:
    """Load and verify a source from work storage or a formal baseline."""
    index = read_compact_index(index_path)
    source_id = index["source_id"]
    source_root = index_path.parent
    manifest_path = source_root / index["manifest_ref"]
    if (
        not manifest_path.is_file()
        or sha256_file(manifest_path) != index["manifest_sha256"]
    ):
        raise SdlcError(f"{source_id} manifest 缺失或 SHA-256 不匹配")
    manifest = read_json(manifest_path)
    entries = {
        item["path"]: item
        for item in manifest.get("files", [])
    }
    for entry in entries.values():
        controlled = source_root / entry["file_ref"]
        if (
            not controlled.is_file()
            or sha256_file(controlled) != entry["sha256"]
        ):
            raise SdlcError(
                f"{source_id} 原始来源缺失或 SHA-256 不匹配: "
                f"{entry['path']}"
            )

    segments: list[dict[str, Any]] = []
    for item in index["anchors"]:
        controlled = source_root / item["file_ref"]
        if item["kind"] == "asset":
            segments.append({
                "anchor": item["anchor"],
                "kind": "asset",
                "media_type": item["media_type"],
                "sha256": item["sha256"],
                "size": item["size"],
                "asset_ref": relative_to_project(root, controlled),
            })
            continue
        text = controlled.read_text(encoding="utf-8", errors="replace")
        selected = text[item["start"]:item["end"]]
        if _sha256_text(selected) != item["sha256"]:
            raise SdlcError(
                f"{source_id} anchor {item['anchor']} SHA-256 不匹配"
            )
        segments.append({
            "anchor": item["anchor"],
            "kind": "text",
            "text": selected,
            "sha256": item["sha256"],
            "content_ref": relative_to_project(root, controlled),
        })
    source: dict[str, Any] = {
        **index,
        "source": index["source_ref"],
        "uri": relative_to_project(root, source_root),
        "segments": segments,
        "manifest": manifest,
    }
    content_ref = index.get("content_ref")
    if isinstance(content_ref, str):
        source["content"] = (
            source_root / content_ref
        ).read_text(encoding="utf-8", errors="replace")
    projection_ref = index.get("projection_ref")
    if isinstance(projection_ref, str):
        source["content"] = (
            source_root / projection_ref
        ).read_text(encoding="utf-8", errors="replace")
    validate_source_envelopes(root, [source])
    return source


def query_source(
    root: Path,
    source_id: str,
    anchor: str,
    *,
    max_chars: int = 12_000,
) -> dict[str, Any]:
    source = load_source(root, source_id)
    segment = next(
        (item for item in source["segments"] if item["anchor"] == anchor),
        None,
    )
    if segment is None:
        raise SdlcError(f"未知来源 anchor: {source_id}#{anchor}")
    if segment["kind"] == "asset":
        return {
            "ok": True,
            "source_id": source_id,
            "anchor": anchor,
            "kind": "asset",
            "media_type": segment["media_type"],
            "sha256": segment["sha256"],
            "size": segment["size"],
            "asset_ref": segment["asset_ref"],
            "canonical_path": segment["asset_ref"],
            "next_action": (
                "这是保持原格式的受控二进制资产；使用支持该媒体类型的"
                "视觉或文档工具读取 asset_ref，不得把二进制解码为文本。"
            ),
        }
    text = segment["text"]
    return {
        "ok": True,
        "source_id": source_id,
        "anchor": anchor,
        "kind": "text",
        "sha256": segment["sha256"],
        "text": text[:max_chars],
        "truncated": len(text) > max_chars,
        "canonical_path": segment["content_ref"],
    }


def _ingest_path_source(
    root: Path,
    *,
    requested_kind: str,
    uri: Any,
    source: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(uri, str) or not uri.strip():
        raise SdlcError(
            "file/directory source 必须提供 uri"
            "（项目内路径，或显式允许的外部路径）"
        )
    candidate = Path(uri).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if not candidate.exists():
        raise SdlcError(f"来源路径不存在: {uri}")
    if not candidate.is_file() and not candidate.is_dir():
        raise SdlcError(f"来源路径既不是文件也不是目录: {uri}")
    if requested_kind == "directory" and candidate.is_file():
        raise SdlcError(f"directory source 要求目录路径，实际为文件: {uri}")
    source = _authorize_source_path(
        root,
        candidate,
        source=source,
        original_uri=uri,
        allow_external_copy=payload.get("allow_external_copy") is True,
    )
    if candidate.is_dir():
        descriptors = _scan_directory(candidate)
        kind = "directory"
        media_type = DIRECTORY_SOURCE_MEDIA_TYPE
    else:
        descriptors = [
            _file_descriptor(
                candidate,
                candidate.name,
                declared_media_type=payload.get("media_type"),
            )
        ]
        kind = "file"
        media_type = descriptors[0]["media_type"]
    projection = _projection(payload, descriptors, kind=kind)
    identity = [
        {
            "path": item["path"],
            "sha256": item["sha256"],
            "size": item["size"],
        }
        for item in descriptors
    ]
    if projection is not None:
        identity.append({
            "path": "projection.md",
            "sha256": _sha256_text(projection["content"]),
            "size": len(projection["content"].encode("utf-8")),
        })
    source_sha = sha256_json(identity)
    source_id = f"SRC-{source_sha[:12].upper()}"
    source_root = work_root(root) / "sources" / source_id
    manifest, anchors = _copy_source_files(
        source_root,
        descriptors,
        directory_kind=kind == "directory",
    )
    projection_ref = None
    if projection is not None:
        projection_ref = "projection.md"
        projection_path = source_root / projection_ref
        atomic_write(projection_path, projection["content"])
        projection_spans = _text_spans(
            projection["content"],
            raw_segments=projection["segments"],
            anchor_prefix="projection",
        )
        anchors.extend([
            {
                **item,
                "kind": "text",
                "file_ref": projection_ref,
            }
            for item in projection_spans
        ])
        manifest["projection"] = {
            "file_ref": projection_ref,
            "media_type": "text/markdown",
            "sha256": sha256_file(projection_path),
            "size": projection_path.stat().st_size,
        }
    return _persist_source(
        root,
        source_root,
        source_id=source_id,
        kind=kind,
        source=source,
        media_type=media_type,
        source_sha=source_sha,
        manifest=manifest,
        anchors=anchors,
        extractor=(
            projection["extractor"]
            if projection is not None
            else {
                "name": (
                    "sdlc-directory-copy"
                    if kind == "directory"
                    else "sdlc-file-copy"
                ),
                "version": "1.0",
            }
        ),
        content_ref=(
            descriptors[0]["controlled_ref"]
            if kind == "file" and descriptors[0]["kind"] == "text"
            else None
        ),
        asset_ref=(
            descriptors[0]["controlled_ref"]
            if kind == "file" and descriptors[0]["kind"] == "asset"
            else None
        ),
        projection_ref=projection_ref,
        bundle=(
            {
                "root_name": candidate.name,
                "file_count": len(descriptors),
                "total_bytes": sum(item["size"] for item in descriptors),
                "tree_sha256": source_sha,
            }
            if kind == "directory"
            else None
        ),
    )


def _ingest_text_source(
    root: Path,
    *,
    kind: str,
    source: str,
    uri: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        raise SdlcError("source content 必须是非空文本")
    media_type = str(payload.get("media_type") or "text/markdown").strip()
    suffix = _text_suffix(media_type)
    file_name = f"content{suffix}"
    source_sha = sha256_json([{
        "path": file_name,
        "sha256": _sha256_text(content),
        "size": len(content.encode("utf-8")),
    }])
    source_id = f"SRC-{source_sha[:12].upper()}"
    source_root = work_root(root) / "sources" / source_id
    controlled_ref = file_name
    controlled = source_root / controlled_ref
    atomic_write(controlled, content)
    spans = _text_spans(
        content,
        raw_segments=payload.get("segments"),
        anchor_prefix="text",
    )
    anchors = [
        {
            **item,
            "kind": "text",
            "file_ref": controlled_ref,
        }
        for item in spans
    ]
    manifest = {
        "schema_version": "1.0",
        "files": [{
            "path": file_name,
            "file_ref": controlled_ref,
            "kind": "text",
            "media_type": media_type,
            "sha256": sha256_file(controlled),
            "size": controlled.stat().st_size,
        }],
    }
    return _persist_source(
        root,
        source_root,
        source_id=source_id,
        kind=kind,
        source=source or str(uri or "inline"),
        media_type=media_type,
        source_sha=source_sha,
        manifest=manifest,
        anchors=anchors,
        extractor=payload.get("extractor") or {
            "name": "sdlc-inline",
            "version": "1.0",
        },
        content_ref=controlled_ref,
    )


def _persist_source(
    root: Path,
    source_root: Path,
    *,
    source_id: str,
    kind: str,
    source: str,
    media_type: str,
    source_sha: str,
    manifest: dict[str, Any],
    anchors: list[dict[str, Any]],
    extractor: dict[str, Any],
    content_ref: str | None = None,
    asset_ref: str | None = None,
    projection_ref: str | None = None,
    bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if len(anchors) > MAX_DIRECTORY_SOURCE_ANCHORS:
        raise SdlcError(
            f"来源 anchor 数超过 {MAX_DIRECTORY_SOURCE_ANCHORS}"
        )
    manifest_path = source_root / "manifest.json"
    write_json(manifest_path, manifest)
    index: dict[str, Any] = {
        "schema_version": "3.0",
        "source_id": source_id,
        "state": "available",
        "kind": kind,
        "source_ref": source,
        "media_type": media_type,
        "sha256": source_sha,
        "manifest_ref": "manifest.json",
        "manifest_sha256": sha256_file(manifest_path),
        "extractor": extractor,
        "anchors": anchors,
        "ingested_at": utc_now(),
    }
    if content_ref is not None:
        index["content_ref"] = content_ref
    if asset_ref is not None:
        index["asset_ref"] = asset_ref
    if projection_ref is not None:
        index["projection_ref"] = projection_ref
    if bundle is not None:
        index["bundle"] = bundle
    index_path = source_root / "index.json"
    write_compact_index(index_path, index)
    return _source_receipt(root, index_path)


def _copy_source_files(
    source_root: Path,
    descriptors: list[dict[str, Any]],
    *,
    directory_kind: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest_files: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    for descriptor in descriptors:
        controlled_ref = (
            f"files/{descriptor['path']}"
            if directory_kind
            else f"files/{Path(descriptor['path']).name}"
        )
        descriptor["controlled_ref"] = controlled_ref
        controlled = source_root / controlled_ref
        controlled.parent.mkdir(parents=True, exist_ok=True)
        if controlled.is_file():
            if sha256_file(controlled) != descriptor["sha256"]:
                raise SdlcError(
                    f"Source ID 冲突，受控原文件 hash 不匹配: "
                    f"{descriptor['path']}"
                )
        else:
            shutil.copy2(descriptor["original_path"], controlled)
        entry = {
            "path": descriptor["path"],
            "file_ref": controlled_ref,
            "kind": descriptor["kind"],
            "media_type": descriptor["media_type"],
            "sha256": descriptor["sha256"],
            "size": descriptor["size"],
        }
        manifest_files.append(entry)
        if descriptor["kind"] == "asset":
            anchors.append({
                "anchor": f"asset:{_anchor_path(descriptor['path'])}",
                "kind": "asset",
                "file_ref": controlled_ref,
                "media_type": descriptor["media_type"],
                "sha256": descriptor["sha256"],
                "size": descriptor["size"],
            })
            continue
        text = controlled.read_text(encoding="utf-8", errors="replace")
        prefix = (
            f"file:{_anchor_path(descriptor['path'])}"
            if directory_kind
            else "text"
        )
        anchors.extend([
            {
                **item,
                "kind": "text",
                "file_ref": controlled_ref,
            }
            for item in _text_spans(
                text,
                raw_segments=None,
                anchor_prefix=prefix,
            )
        ])
    return {
        "schema_version": "1.0",
        "files": manifest_files,
    }, anchors


def _scan_directory(directory: Path) -> list[dict[str, Any]]:
    files: list[Path] = []

    def visit(current: Path) -> None:
        with os.scandir(current) as entries:
            children = sorted(entries, key=lambda item: item.name)
        for entry in children:
            path = Path(entry.path)
            relative = path.relative_to(directory).as_posix()
            if entry.is_symlink() or _is_link(path):
                raise SdlcError(
                    f"目录来源禁止符号链接或 junction: {relative}"
                )
            if entry.is_dir(follow_symlinks=False):
                visit(path)
                continue
            if entry.is_file(follow_symlinks=False):
                files.append(path)
                continue
            raise SdlcError(f"目录来源包含不支持的文件类型: {relative}")

    visit(directory)
    files.sort(key=lambda item: item.relative_to(directory).as_posix())
    if not files:
        raise SdlcError(f"目录来源不包含文件: {directory}")
    if len(files) > MAX_DIRECTORY_SOURCE_FILES:
        raise SdlcError(
            f"目录来源文件数超过 {MAX_DIRECTORY_SOURCE_FILES}: {directory}"
        )
    total_bytes = sum(path.stat().st_size for path in files)
    if total_bytes > MAX_DIRECTORY_SOURCE_BYTES:
        raise SdlcError(
            f"目录来源总大小超过 {MAX_DIRECTORY_SOURCE_BYTES} bytes: "
            f"{directory}"
        )
    return [
        _file_descriptor(
            path,
            path.relative_to(directory).as_posix(),
            declared_media_type=None,
        )
        for path in files
    ]


def _file_descriptor(
    path: Path,
    relative_path: str,
    *,
    declared_media_type: Any,
) -> dict[str, Any]:
    size = path.stat().st_size
    if size > MAX_EXTERNAL_SOURCE_BYTES:
        raise SdlcError(
            f"来源单文件超过 {MAX_EXTERNAL_SOURCE_BYTES} bytes: "
            f"{relative_path}"
        )
    if len(relative_path) > 240:
        raise SdlcError(f"来源相对路径超过 240 chars: {relative_path}")
    media_type = _media_type(path, declared_media_type)
    return {
        "path": relative_path,
        "original_path": path,
        "kind": "text" if _is_text_source(path, media_type) else "asset",
        "media_type": media_type,
        "sha256": sha256_file(path),
        "size": size,
    }


def _projection(
    payload: dict[str, Any],
    descriptors: list[dict[str, Any]],
    *,
    kind: str,
) -> dict[str, Any] | None:
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    if kind == "directory":
        raise SdlcError("directory source 不接受单一 content projection")
    if descriptors[0]["kind"] != "asset":
        raise SdlcError("文本文件必须使用原文件正文，不能用 content 覆盖")
    return {
        "content": content,
        "segments": payload.get("segments"),
        "extractor": payload.get("extractor") or {
            "name": "sdlc-controlled-projection",
            "version": "1.0",
        },
    }


def _authorize_source_path(
    root: Path,
    candidate: Path,
    *,
    source: str,
    original_uri: str,
    allow_external_copy: bool,
) -> str:
    try:
        project_relative = candidate.relative_to(root.resolve())
        return source or project_relative.as_posix()
    except ValueError as exc:
        if not allow_external_copy:
            raise SdlcError(
                f"来源路径越出项目: {original_uri}；受控摄取必须显式设置 "
                "allow_external_copy=true"
            ) from exc
        return source or str(candidate)


def _source_receipt(root: Path, index_path: Path) -> dict[str, Any]:
    source = load_indexed_source(root, index_path)
    anchors = []
    for item in source["segments"]:
        if item["kind"] == "asset":
            anchors.append({
                "anchor": item["anchor"],
                "kind": "asset",
                "media_type": item["media_type"],
                "sha256": item["sha256"],
                "size": item["size"],
                "asset_ref": item["asset_ref"],
            })
        else:
            anchors.append({
                "anchor": item["anchor"],
                "kind": "text",
                "characters": len(item["text"]),
                "sha256": item["sha256"],
                "preview": item["text"][:160],
                "content_ref": item["content_ref"],
            })
    result: dict[str, Any] = {
        "ok": True,
        "source_id": source["source_id"],
        "kind": source["kind"],
        "source": source["source_ref"],
        "media_type": source["media_type"],
        "sha256": source["sha256"],
        "anchors": anchors,
        "canonical_path": relative_to_project(root, index_path),
        "manifest_ref": source["manifest_ref"],
        "extractor": source["extractor"],
        "next_action": (
            "文本 anchor 使用 sdlc_query_source 查询；asset anchor 返回保持"
            "原格式的受控 asset_ref，必须用支持对应媒体类型的工具读取。"
        ),
    }
    source_root = index_path.parent
    if source.get("content_ref"):
        result["content_ref"] = relative_to_project(
            root, source_root / source["content_ref"]
        )
    if source.get("asset_ref"):
        result["asset_ref"] = relative_to_project(
            root, source_root / source["asset_ref"]
        )
    if source.get("projection_ref"):
        result["projection_ref"] = relative_to_project(
            root, source_root / source["projection_ref"]
        )
    if source.get("bundle"):
        result["bundle"] = source["bundle"]
    return result


def _text_spans(
    content: str,
    *,
    raw_segments: Any,
    anchor_prefix: str,
) -> list[dict[str, Any]]:
    if raw_segments is not None:
        return _locate_segment_spans(content, raw_segments)
    spans = _default_segment_spans(content)
    for number, item in enumerate(spans, 1):
        item["anchor"] = f"{anchor_prefix}:{number}"
    return spans


def _default_segment_spans(content: str) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    start = 0
    while start < len(content):
        end = min(start + MAX_SOURCE_SEGMENT_CHARS, len(content))
        if end < len(content):
            boundary = content.rfind("\n", start + 1, end + 1)
            if boundary > start:
                end = boundary + 1
        if end <= start:
            end = min(start + MAX_SOURCE_SEGMENT_CHARS, len(content))
        text = content[start:end]
        spans.append({
            "anchor": f"text:{len(spans) + 1}",
            "start": start,
            "end": end,
            "sha256": _sha256_text(text),
        })
        start = end
    return spans


def _locate_segment_spans(
    content: str, raw_segments: Any
) -> list[dict[str, Any]]:
    if not isinstance(raw_segments, list) or not raw_segments:
        raise SdlcError("source segments 必须是非空数组")
    spans = []
    cursor = 0
    for index, item in enumerate(raw_segments, 1):
        if not isinstance(item, dict):
            raise SdlcError(f"source segment[{index}] 必须是对象")
        anchor = str(item.get("anchor", "")).strip()
        text = item.get("text")
        if not anchor or not isinstance(text, str) or not text:
            raise SdlcError(f"source segment[{index}] 缺少 anchor/text")
        start = content.find(text, cursor)
        if start < 0:
            start = content.find(text)
        if start < 0:
            raise SdlcError(
                f"source segment[{index}] 不是 content 的原文片段，"
                "不能建立无复制 anchor"
            )
        end = start + len(text)
        spans.append({
            "anchor": anchor,
            "start": start,
            "end": end,
            "sha256": _sha256_text(text),
        })
        cursor = end
    return spans


def _media_type(path: Path, declared: Any) -> str:
    guessed = mimetypes.guess_type(path.name)[0]
    if path.suffix.lower() in TEXT_SOURCE_SUFFIXES:
        return guessed or (
            str(declared).strip()
            if isinstance(declared, str) and declared.strip()
            else "text/plain"
        )
    if guessed:
        return guessed
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    return "application/octet-stream"


def _is_text_source(path: Path, media_type: str) -> bool:
    return (
        path.suffix.lower() in TEXT_SOURCE_SUFFIXES
        or media_type.startswith("text/")
    )


def _text_suffix(media_type: str) -> str:
    return {
        "text/html": ".html",
        "application/json": ".json",
        "text/css": ".css",
        "text/csv": ".csv",
    }.get(media_type, ".md")


def _is_link(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


def _anchor_path(relative_path: str) -> str:
    return relative_path.replace("%", "%25").replace("#", "%23")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
