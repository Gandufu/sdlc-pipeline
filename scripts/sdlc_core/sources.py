from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from .common import SdlcError, read_json, utc_now, write_json
from .schema_validation import validate_schema_instance

MAX_EXTERNAL_SOURCE_BYTES = 10 * 1024 * 1024


def ingest_source(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    kind = payload.get("kind", "inline")
    source = str(payload.get("source", "")).strip()
    media_type = str(payload.get("media_type", "text/plain")).strip()
    extractor = payload.get("extractor") or {
        "name": "sdlc-inline",
        "version": "1.0",
    }
    content = payload.get("content")
    uri = payload.get("uri")
    asset = None
    if kind == "file":
        if not isinstance(uri, str) or not uri.strip():
            raise SdlcError("file SourceEnvelope 必须提供项目内 uri")
        candidate = Path(uri).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        try:
            relative = candidate.relative_to(root.resolve())
        except ValueError as exc:
            if payload.get("allow_external_copy") is not True:
                raise SdlcError(
                    f"来源文件越出项目: {uri}；受控复制必须显式设置 allow_external_copy=true"
                ) from exc
            if not candidate.is_file():
                raise SdlcError(f"来源文件不存在: {uri}")
            size = candidate.stat().st_size
            if size > MAX_EXTERNAL_SOURCE_BYTES:
                raise SdlcError(
                    f"外部来源文件超过 {MAX_EXTERNAL_SOURCE_BYTES} bytes: {uri}"
                )
            asset_sha = _sha256_file(candidate)
            relative = Path(
                ".sdlc-pipeline/runs/source-assets"
            ) / f"{asset_sha}{candidate.suffix.lower()}"
            copied = root / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            if not copied.is_file() or _sha256_file(copied) != asset_sha:
                shutil.copy2(candidate, copied)
            asset = {
                "original_uri": str(candidate),
                "uri": relative.as_posix(),
                "sha256": asset_sha,
                "size": size,
                "copied_at": utc_now(),
            }
            candidate = copied
            source = source or str(Path(uri).expanduser().resolve())
            uri = relative.as_posix()
        if not candidate.is_file():
            raise SdlcError(f"来源文件不存在: {uri}")
        if not media_type.startswith("text/") and candidate.suffix.lower() not in {
            ".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".tsv",
        }:
            raise SdlcError(
                "二进制文档必须由受控 extractor 提供 content/segments，"
                "不能由 runner 猜测解析"
            )
        content = candidate.read_text(encoding="utf-8", errors="replace")
    if not isinstance(content, str) or not content.strip():
        raise SdlcError("SourceEnvelope content 必须是非空文本")
    if not source:
        source = uri or "inline"
    raw_segments = payload.get("segments")
    if raw_segments is None:
        raw_segments = [{"anchor": "text:1", "text": content}]
    if not isinstance(raw_segments, list) or not raw_segments:
        raise SdlcError("SourceEnvelope segments 必须是非空数组")
    segments = []
    for index, item in enumerate(raw_segments, 1):
        if not isinstance(item, dict):
            raise SdlcError(f"SourceEnvelope segment[{index}] 必须是对象")
        anchor = str(item.get("anchor", "")).strip()
        text = item.get("text")
        if not anchor or not isinstance(text, str) or not text:
            raise SdlcError(f"SourceEnvelope segment[{index}] 缺少 anchor/text")
        segments.append({
            "anchor": anchor,
            "text": text,
            "sha256": _sha256_text(text),
        })
    content_sha = _sha256_text(content)
    source_id = f"SRC-{content_sha[:12].upper()}"
    envelope = {
        "schema_version": "1.0",
        "source_id": source_id,
        "kind": kind,
        "source": source,
        "uri": uri,
        "media_type": media_type,
        "sha256": content_sha,
        "extractor": extractor,
        "segments": segments,
        "content": content,
        "ingested_at": utc_now(),
    }
    if asset is not None:
        envelope["asset"] = asset
    validate_schema_instance(root, "source-envelope.schema.json", envelope)
    path = (
        root / ".sdlc-pipeline" / "runs" / "sources" / f"{source_id}.json"
    )
    existing = read_json(path, required=False)
    if existing and existing.get("sha256") != content_sha:
        raise SdlcError(f"SourceEnvelope ID 冲突: {source_id}")
    write_json(path, envelope)
    return {"ok": True, "envelope": envelope}


def validate_source_envelopes(root: Path, sources: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for source in sources:
        validate_schema_instance(root, "source-envelope.schema.json", source)
        identifier = source["source_id"]
        if identifier in seen:
            raise SdlcError(f"重复 SourceEnvelope: {identifier}")
        seen.add(identifier)
        if _sha256_text(source["content"]) != source["sha256"]:
            raise SdlcError(f"{identifier} content SHA-256 不匹配")
        for segment in source["segments"]:
            if _sha256_text(segment["text"]) != segment["sha256"]:
                raise SdlcError(
                    f"{identifier} segment {segment['anchor']} SHA-256 不匹配"
                )
        asset = source.get("asset")
        if asset:
            candidate = root / asset["uri"]
            try:
                candidate.resolve().relative_to(
                    (root / ".sdlc-pipeline" / "runs" / "source-assets").resolve()
                )
            except ValueError as exc:
                raise SdlcError(f"{identifier} 外部来源副本越出受控目录") from exc
            if not candidate.is_file() or _sha256_file(candidate) != asset["sha256"]:
                raise SdlcError(f"{identifier} 外部来源副本缺失或 SHA-256 不匹配")


def source_index(sources: list[dict[str, Any]]) -> dict[str, set[str]]:
    return {
        item["source_id"]: {segment["anchor"] for segment in item["segments"]}
        for item in sources
    }


def load_source(root: Path, source_id: str) -> dict[str, Any]:
    path = root / ".sdlc-pipeline" / "runs" / "sources" / f"{source_id}.json"
    source = read_json(path, required=False)
    if source is None:
        raise SdlcError(f"未知 SourceEnvelope: {source_id}")
    validate_source_envelopes(root, [source])
    return source


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
