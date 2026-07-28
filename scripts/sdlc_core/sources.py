from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from .common import SdlcError, atomic_write, sha256_file, utc_now
from .layout import evidence_root, relative_to_project, work_root
from .records import read_compact_index, write_compact_index


MAX_EXTERNAL_SOURCE_BYTES = 10 * 1024 * 1024
MAX_SOURCE_SEGMENT_CHARS = 8_000
_SOURCE_BEGIN = "<!-- sdlc-source:begin -->"
_SOURCE_END = "<!-- sdlc-source:end -->"


def ingest_source(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist source prose once in Markdown and return only a bounded receipt."""
    kind = payload.get("kind", "inline")
    source = str(payload.get("source", "")).strip()
    media_type = str(payload.get("media_type", "text/plain")).strip()
    extractor = payload.get("extractor") or {
        "name": "sdlc-inline",
        "version": "1.0",
    }
    content = payload.get("content")
    uri = payload.get("uri")
    asset: dict[str, Any] | None = None
    if kind == "file" and (not isinstance(uri, str) or not uri.strip()) and source:
        uri = source
        source = ""
    if kind == "file":
        if not isinstance(uri, str) or not uri.strip():
            raise SdlcError(
                "file source 必须提供 uri（项目内路径，或显式允许的外部路径）"
            )
        candidate = Path(uri).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        if not candidate.is_file():
            raise SdlcError(f"来源文件不存在: {uri}")
        try:
            project_relative = candidate.relative_to(root.resolve())
            source = source or project_relative.as_posix()
        except ValueError as exc:
            if payload.get("allow_external_copy") is not True:
                raise SdlcError(
                    f"来源文件越出项目: {uri}；受控摄取必须显式设置 "
                    "allow_external_copy=true"
                ) from exc
            source = source or str(candidate)
        size = candidate.stat().st_size
        if size > MAX_EXTERNAL_SOURCE_BYTES:
            raise SdlcError(
                f"外部来源文件超过 {MAX_EXTERNAL_SOURCE_BYTES} bytes: {uri}"
            )
        binary = (
            not media_type.startswith("text/")
            and candidate.suffix.lower()
            not in {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".tsv", ".html", ".css"}
        )
        if binary:
            if not isinstance(content, str) or not content.strip():
                raise SdlcError(
                    "二进制文档必须由受控 extractor 提供 content/segments"
                )
            blob_sha = sha256_file(candidate)
            blob = evidence_root(root) / "blobs" / f"{blob_sha}{candidate.suffix.lower()}"
            blob.parent.mkdir(parents=True, exist_ok=True)
            if not blob.is_file() or sha256_file(blob) != blob_sha:
                shutil.copy2(candidate, blob)
            asset = {
                "original_uri": str(candidate),
                "blob_ref": relative_to_project(root, blob),
                "sha256": blob_sha,
                "size": size,
            }
        else:
            content = candidate.read_text(encoding="utf-8", errors="replace")
            asset = {
                "original_uri": str(candidate),
                "size": size,
            }
    if not isinstance(content, str) or not content.strip():
        raise SdlcError("source content 必须是非空文本")
    if not source:
        source = str(uri or "inline")

    raw_segments = payload.get("segments")
    segments = (
        _default_segment_spans(content)
        if raw_segments is None
        else _locate_segment_spans(content, raw_segments)
    )
    content_sha = _sha256_text(content)
    source_id = f"SRC-{content_sha[:12].upper()}"
    directory = work_root(root) / "sources" / source_id
    content_path = directory / "content.md"
    index_path = directory / "index.json"
    rendered = (
        f"# Source {source_id}\n\n"
        f"- Kind: `{kind}`\n"
        f"- Media type: `{media_type}`\n"
        f"- SHA-256: `{content_sha}`\n\n"
        f"{_SOURCE_BEGIN}\n{content}\n{_SOURCE_END}\n"
    )
    if content_path.is_file():
        existing_content = _read_source_content(content_path)
        if _sha256_text(existing_content) != content_sha:
            raise SdlcError(f"Source ID 冲突: {source_id}")
    else:
        atomic_write(content_path, rendered)
    index = {
        "schema_version": "3.0",
        "source_id": source_id,
        "state": "available",
        "kind": kind,
        "source_ref": source,
        "media_type": media_type,
        "content_ref": relative_to_project(root, content_path),
        "sha256": content_sha,
        "extractor": extractor,
        "anchors": segments,
        "ingested_at": utc_now(),
    }
    if asset is not None:
        index["asset"] = asset
    write_compact_index(index_path, index)
    return _source_receipt(root, index, content)


def validate_source_envelopes(root: Path, sources: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for source in sources:
        identifier = source.get("source_id")
        if not isinstance(identifier, str) or identifier in seen:
            raise SdlcError(f"重复或非法 source: {identifier}")
        seen.add(identifier)
        content = source.get("content")
        if not isinstance(content, str) or _sha256_text(content) != source.get("sha256"):
            raise SdlcError(f"{identifier} content SHA-256 不匹配")
        for segment in source.get("segments", []):
            if _sha256_text(segment["text"]) != segment["sha256"]:
                raise SdlcError(
                    f"{identifier} segment {segment['anchor']} SHA-256 不匹配"
                )


def source_index(sources: list[dict[str, Any]]) -> dict[str, set[str]]:
    return {
        item["source_id"]: {segment["anchor"] for segment in item["segments"]}
        for item in sources
    }


def load_source(root: Path, source_id: str) -> dict[str, Any]:
    directory = work_root(root) / "sources" / source_id
    index_path = directory / "index.json"
    index = read_compact_index(index_path, required=False)
    if index is None:
        raise SdlcError(f"未知 source: {source_id}")
    return load_indexed_source(root, index_path)


def load_indexed_source(root: Path, index_path: Path) -> dict[str, Any]:
    """Load a source through its compact index, from work or a formal baseline."""
    index = read_compact_index(index_path)
    source_id = index["source_id"]
    content_path = root / index["content_ref"]
    content = _read_source_content(content_path)
    if _sha256_text(content) != index["sha256"]:
        raise SdlcError(f"{source_id} content SHA-256 不匹配")
    segments = []
    for item in index["anchors"]:
        text = content[item["start"]:item["end"]]
        if _sha256_text(text) != item["sha256"]:
            raise SdlcError(f"{source_id} anchor {item['anchor']} SHA-256 不匹配")
        segments.append({
            "anchor": item["anchor"],
            "text": text,
            "sha256": item["sha256"],
        })
    source = {
        **index,
        "source": index["source_ref"],
        "uri": index["content_ref"],
        "segments": segments,
        "content": content,
    }
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
    text = segment["text"]
    return {
        "ok": True,
        "source_id": source_id,
        "anchor": anchor,
        "sha256": segment["sha256"],
        "text": text[:max_chars],
        "truncated": len(text) > max_chars,
        "canonical_path": source["content_ref"],
    }


def _source_receipt(
    root: Path, index: dict[str, Any], content: str
) -> dict[str, Any]:
    anchors = []
    for item in index["anchors"]:
        text = content[item["start"]:item["end"]]
        anchors.append({
            "anchor": item["anchor"],
            "characters": len(text),
            "sha256": item["sha256"],
            "preview": text[:160],
        })
    return {
        "ok": True,
        "source_id": index["source_id"],
        "kind": index["kind"],
        "source": index["source_ref"],
        "media_type": index["media_type"],
        "sha256": index["sha256"],
        "anchors": anchors,
        "canonical_path": relative_to_project(
            root, work_root(root) / "sources" / index["source_id"] / "index.json"
        ),
        "content_ref": index["content_ref"],
        "asset": index.get("asset"),
        "next_action": (
            "Use only source_id/anchor. Query sdlc_query_source for bounded text; "
            "do not read the original external path."
        ),
    }


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
                f"source segment[{index}] 不是 content 的原文片段，不能建立无复制 anchor"
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


def _read_source_content(path: Path) -> str:
    if not path.is_file():
        raise SdlcError(f"来源正文缺失: {path}")
    rendered = path.read_text(encoding="utf-8")
    start = rendered.find(_SOURCE_BEGIN)
    end = rendered.rfind(_SOURCE_END)
    if start < 0 or end < 0 or end <= start:
        raise SdlcError(f"来源 Markdown 标记缺失: {path}")
    content = rendered[start + len(_SOURCE_BEGIN):end]
    if content.startswith("\n"):
        content = content[1:]
    if content.endswith("\n"):
        content = content[:-1]
    return content


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
