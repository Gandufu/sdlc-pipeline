from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .common import SdlcError, atomic_write, read_json, sha256_file, write_json


_PAYLOAD_PATTERN = re.compile(
    r"<!-- sdlc-record:begin -->\s*```json\s*(\{.*\})\s*```\s*"
    r"<!-- sdlc-record:end -->",
    re.DOTALL,
)
_FORBIDDEN_INDEX_KEYS = {
    "answer",
    "content",
    "description",
    "error",
    "goal",
    "prompt",
    "rationale",
    "result",
    "summary",
    "tail",
    "text",
}
MAX_INDEX_BYTES = 32 * 1024
MAX_INDEX_STRING_CHARS = 512


def write_markdown_record(
    path: Path,
    value: dict[str, Any],
    *,
    title: str,
    summary_lines: list[str] | None = None,
) -> dict[str, Any]:
    """Persist a recoverable record as Markdown, never as state JSON."""
    if not isinstance(value, dict):
        raise SdlcError("Markdown record payload 必须是对象")
    lines = [f"# {title}", ""]
    if summary_lines:
        lines.extend([*summary_lines, ""])
    lines.extend([
        "## Structured record",
        "",
        "<!-- sdlc-record:begin -->",
        "```json",
        json.dumps(value, ensure_ascii=False, indent=2),
        "```",
        "<!-- sdlc-record:end -->",
        "",
    ])
    atomic_write(path, "\n".join(lines))
    return {
        "path": path.as_posix(),
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
    }


def read_markdown_record(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    if not path.is_file():
        if required:
            raise SdlcError(f"缺少 Markdown record: {path}")
        return None
    match = _PAYLOAD_PATTERN.search(path.read_text(encoding="utf-8"))
    if not match:
        raise SdlcError(f"Markdown record 缺少 structured record: {path}")
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SdlcError(f"Markdown record payload 无法解析: {path}") from exc
    if not isinstance(value, dict):
        raise SdlcError(f"Markdown record payload 必须是对象: {path}")
    return value


def write_compact_index(path: Path, value: dict[str, Any]) -> None:
    assert_compact_index(value)
    write_json(path, value)
    if path.stat().st_size > MAX_INDEX_BYTES:
        raise SdlcError(
            f"状态索引超过 {MAX_INDEX_BYTES} bytes: {path}"
        )


def read_compact_index(
    path: Path, *, required: bool = True
) -> dict[str, Any] | None:
    value = read_json(path, required=required)
    if value is not None:
        assert_compact_index(value)
    return value


def assert_compact_index(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _FORBIDDEN_INDEX_KEYS:
                raise SdlcError(f"状态索引禁止保存正文字段: {path}.{key}")
            assert_compact_index(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_compact_index(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and len(value) > MAX_INDEX_STRING_CHARS:
        raise SdlcError(
            f"状态索引字符串超过 {MAX_INDEX_STRING_CHARS} chars: {path}"
        )
