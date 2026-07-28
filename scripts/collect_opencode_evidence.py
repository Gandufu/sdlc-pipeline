#!/usr/bin/env python3
"""Collect bounded deterministic evidence from an installed OpenCode project."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RELEASE_ARTIFACTS = (
    ".vite/build/main.js",
    ".vite/build/preload.js",
    "out/SDLC Electron Scaffold-win32-x64/resources/app.asar",
    "out/SDLC Electron Scaffold-win32-x64/sdlc-electron-scaffold.exe",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def run_command(argv: list[str], cwd: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "error": str(error)}
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout_head": stdout[:2000],
        "stdout_tail": stdout[-4000:],
        "stderr_head": stderr[:2000],
        "stderr_tail": stderr[-4000:],
        "_stdout_full": stdout,
    }


def public_command(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "_stdout_full"}


def file_record(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "modified_at": datetime.fromtimestamp(
            path.stat().st_mtime,
            tz=timezone.utc,
        ).isoformat(),
    }


def latest_attempts(journal_root: Path) -> list[dict[str, Any]]:
    candidates: list[tuple[Path, dict[str, Any]]] = []
    for path in journal_root.glob("*/attempts/*/*.json"):
        document = read_json(path)
        if isinstance(document, dict):
            candidates.append((path, document))
    candidates.sort(
        key=lambda item: (
            str(item[1].get("started_at", "")),
            str(item[1].get("attempt_id", "")),
            item[0].as_posix(),
        ),
        reverse=True,
    )
    records = []
    for path, document in candidates[:12]:
        result = document.get("result")
        records.append({
            "path": path.relative_to(journal_root).as_posix(),
            "attempt_id": document.get("attempt_id"),
            "phase": document.get("phase"),
            "step": document.get("step"),
            "state": document.get("state"),
            "started_at": document.get("started_at"),
            "finished_at": document.get("finished_at"),
            "error": document.get("error"),
            "result_ok": result.get("ok") if isinstance(result, dict) else None,
        })
    return records


def journal_failure_summary(journal_root: Path) -> dict[str, Any]:
    """Preserve every failure pattern even when old attempts age out of the tail."""
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    total = 0
    candidates: list[dict[str, Any]] = []
    for path in journal_root.glob("*/attempts/*/*.json"):
        document = read_json(path)
        if isinstance(document, dict):
            candidates.append(document)
    candidates.sort(key=lambda document: (
        str(document.get("started_at", "")),
        str(document.get("attempt_id", "")),
    ))
    for document in candidates:
        state = str(document.get("state", "unknown"))
        raw_error = document.get("error")
        if state == "succeeded" and not raw_error:
            continue
        phase = str(document.get("phase", "unknown"))
        step = str(document.get("step", "unknown"))
        error = str(raw_error) if raw_error else f"state={state}"
        key = (phase, step, state, error)
        attempt_id = document.get("attempt_id")
        group = groups.setdefault(key, {
            "phase": phase,
            "step": step,
            "state": state,
            "error": error,
            "count": 0,
            "first_attempt_id": attempt_id,
            "last_attempt_id": attempt_id,
        })
        group["count"] += 1
        group["last_attempt_id"] = attempt_id
        total += 1
    return {"total": total, "groups": list(groups.values())}


def collect(root: Path) -> dict[str, Any]:
    core = root / ".sdlc-pipeline" / "scripts" / "sdlc.py"
    status: Any = None
    status_command: dict[str, Any] | None = None
    if core.is_file():
        raw_status = run_command(
            [sys.executable, str(core), "status", "--root", str(root)],
            root,
        )
        if raw_status.get("ok"):
            try:
                status = json.loads(str(raw_status.get("_stdout_full", "")))
            except json.JSONDecodeError:
                pass
        status_command = public_command(raw_status)

    current = root / "docs" / "sdlc" / "current"
    journal = root / ".sdlc-pipeline" / "runs" / "journal"
    source_dir = root / ".sdlc-pipeline" / "runs" / "sources"
    return {
        "schema_version": "1.0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "core_status": status,
        "core_status_command": status_command,
        "spec_artifacts": [
            file_record(root, path)
            for path in sorted(current.glob("*"))
            if path.is_file()
        ],
        "source_envelopes": [
            file_record(root, path)
            for path in sorted(source_dir.rglob("*.json"))
        ] if source_dir.is_dir() else [],
        "latest_journal_attempts": (
            latest_attempts(journal) if journal.is_dir() else []
        ),
        "journal_failure_summary": (
            journal_failure_summary(journal) if journal.is_dir()
            else {"total": 0, "groups": []}
        ),
        "release_artifacts": [
            file_record(root, root / relative)
            for relative in RELEASE_ARTIFACTS
            if (root / relative).is_file()
        ],
        "git_status": public_command(
            run_command(["git", "status", "--short"], root)
        ),
        "git_diff_check": public_command(
            run_command(["git", "diff", "--check"], root)
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.project_root.resolve()
    if not root.is_dir():
        parser.error(f"project root does not exist: {root}")
    rendered = json.dumps(collect(root), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
