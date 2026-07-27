from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .common import SdlcError, atomic_write


TOOLING_IGNORE_PATTERNS = (".opencode/**", ".sdlc-pipeline/**")


def _merge_ignore_array(path: Path, key: str) -> bool:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        rf"(?P<prefix>\b{re.escape(key)}\s*:\s*\[)(?P<body>.*?)(?P<suffix>\])",
        text,
        re.DOTALL,
    )
    if not match:
        return False
    body = match.group("body")
    missing = [pattern for pattern in TOOLING_IGNORE_PATTERNS if pattern not in body]
    if not missing:
        return True
    separator = "" if not body.strip() else ("" if body.rstrip().endswith(",") else ",")
    addition = separator + "".join(f" {pattern!r}," for pattern in missing)
    updated = text[:match.end("body")] + addition + text[match.end("body"):]
    atomic_write(path, updated)
    return True


def ensure_tooling_ignores(root: Path, *, strict: bool = False) -> dict[str, Any]:
    updated: list[str] = []
    unresolved: list[str] = []
    groups = (
        (
            "exclude",
            ("vitest.config.ts", "vitest.config.js", "vitest.config.mts", "vitest.config.mjs"),
        ),
        (
            "ignores",
            ("eslint.config.mjs", "eslint.config.js", "eslint.config.cjs", "eslint.config.ts"),
        ),
    )
    for key, names in groups:
        for name in names:
            path = root / name
            if not path.is_file():
                continue
            if _merge_ignore_array(path, key):
                updated.append(name)
            else:
                unresolved.append(name)
    result = {
        "ok": not unresolved,
        "patterns": list(TOOLING_IGNORE_PATTERNS),
        "updated": sorted(updated),
        "unresolved": sorted(unresolved),
    }
    if strict and unresolved:
        raise SdlcError(
            "无法安全写入 tooling ignore，拒绝继续 init: "
            + ", ".join(sorted(unresolved))
        )
    return result
