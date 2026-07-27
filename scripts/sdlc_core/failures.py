from __future__ import annotations

import re

from .common import sha256_json


def classify_failure(error: str) -> str:
    lowered = error.lower()
    if any(token in lowered for token in (
        "schema", "不允许的字段", "idempotency", "未知 source",
        "未知来源 anchor", "越出项目", "允许范围",
    )):
        return "contract"
    if any(token in lowered for token in (
        "不可达", "timeout", "timed out", "connection refused",
        "凭据", "password", "环境", "missing tool",
    )):
        return "environment"
    if any(token in lowered for token in (
        "test", "assert", "compile", "typescript", "ts2", "lint",
    )):
        return "code"
    return "unknown"


def failure_fingerprint(error: str) -> dict[str, str]:
    normalized = re.sub(r"\s+", " ", error.strip())
    normalized = re.sub(r"\b\d{4,}\b", "<n>", normalized)
    failure_class = classify_failure(normalized)
    return {
        "class": failure_class,
        "fingerprint": sha256_json({
            "class": failure_class,
            "message": normalized,
        })[:16],
    }
