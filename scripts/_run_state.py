"""编码/走查运行登记。

阶段状态仍由文档和追溯矩阵派生；本模块只保存一次 /code 运行的现场事实，
用于绑定 execution root、区分编码前已有改动，以及在会话中断后发现半成品。
Git 项目写入共享 git common dir，不污染业务分支；非 Git 项目写入系统临时目录。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any


TERMINAL_PHASES = {"complete", "abandoned"}


def canonical(path: str) -> str:
    return os.path.realpath(os.path.abspath(path))


def _git(candidate: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", "-C", candidate, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def git_common_dir(candidate: str) -> str | None:
    candidate = canonical(candidate)
    result = _git(candidate, "rev-parse", "--git-common-dir")
    if result.returncode != 0 or not result.stdout.strip():
        return None
    common = result.stdout.strip()
    if not os.path.isabs(common):
        common = os.path.join(candidate, common)
    return canonical(common)


def state_file(candidate: str) -> str:
    candidate = canonical(candidate)
    common = git_common_dir(candidate)
    if common:
        return os.path.join(common, "sdlc-pipeline", "active-run.json")
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:20]
    return os.path.join(tempfile.gettempdir(), "sdlc-pipeline-runtime", digest, "active-run.json")


def load(candidate: str) -> dict[str, Any] | None:
    try:
        with open(state_file(candidate), encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _atomic_write(path: str, value: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".active-run-", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _file_fingerprint(root: str, relative_path: str) -> str:
    path = os.path.join(root, relative_path)
    if not os.path.isfile(path):
        return "<deleted>"
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return "<unreadable>"


def changed_snapshot(root: str) -> dict[str, str] | None:
    """返回相对 HEAD 的 tracked/untracked 文件及内容指纹。非 Git 项目返回 None。"""
    root = canonical(root)
    probe = _git(root, "rev-parse", "--is-inside-work-tree")
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return None
    changed: set[str] = set()
    for args in (
        ("diff", "--name-only", "--relative", "HEAD"),
        ("ls-files", "--others", "--exclude-standard"),
    ):
        result = _git(root, *args)
        if result.returncode != 0:
            return None
        changed.update(
            line.strip().replace("\\", "/")
            for line in result.stdout.splitlines()
            if line.strip()
        )
    return {path: _file_fingerprint(root, path) for path in sorted(changed)}


def start(project_root: str, execution_root: str, mode: str) -> tuple[dict[str, Any], bool]:
    project_root = canonical(project_root)
    execution_root = canonical(execution_root)
    if mode == "current" and execution_root != project_root:
        raise ValueError("current 模式的 execution root 必须等于 project root")
    if mode == "worktree":
        project_common = git_common_dir(project_root)
        execution_common = git_common_dir(execution_root)
        if not project_common or project_common != execution_common:
            raise ValueError("worktree execution root 必须属于同一个 Git common dir")
        if execution_root not in worktrees(project_root):
            raise ValueError("execution root 不是已登记的 Git worktree")
    existing = load(project_root)
    if existing and existing.get("phase") not in TERMINAL_PHASES:
        return existing, True
    now = datetime.now(timezone.utc).isoformat()
    record: dict[str, Any] = {
        "schema": 1,
        "run_id": uuid.uuid4().hex,
        "project_root": project_root,
        "execution_root": execution_root,
        "mode": mode,
        "requires_merge": mode == "worktree",
        "phase": "coding",
        "created_at": now,
        "updated_at": now,
        "baseline_changes": changed_snapshot(execution_root),
        "evidence_files": {},
    }
    _atomic_write(state_file(project_root), record)
    return record, False


def update(candidate: str, **changes: Any) -> dict[str, Any] | None:
    record = load(candidate)
    if not record:
        return None
    record.update(changes)
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(state_file(candidate), record)
    return record


def find_for_hook(hook: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [
        str(hook.get("cwd") or ""),
        str(os.environ.get("CLAUDE_PROJECT_DIR") or ""),
    ]
    for candidate in candidates:
        if candidate:
            record = load(candidate)
            if record and record.get("phase") not in TERMINAL_PHASES:
                return record
    return None


def execution_root_for_hook(hook: dict[str, Any]) -> str | None:
    record = find_for_hook(hook)
    root = str((record or {}).get("execution_root") or "")
    return canonical(root) if root and os.path.isdir(root) else None


def changed_since_start(hook: dict[str, Any]) -> set[str] | None:
    record = find_for_hook(hook)
    if not record:
        return None
    root = str(record.get("execution_root") or "")
    current = changed_snapshot(root)
    baseline = record.get("baseline_changes")
    if current is None or not isinstance(baseline, dict):
        return None
    paths = set(current) | set(baseline)
    return {path for path in paths if current.get(path) != baseline.get(path)}


def fingerprints(root: str, paths: set[str]) -> dict[str, str]:
    root = canonical(root)
    return {path: _file_fingerprint(root, path) for path in sorted(paths)}


def verify_target(candidate: str, target_root: str) -> tuple[bool, list[str]]:
    record = load(candidate)
    if not record:
        return False, ["运行登记不存在"]
    evidence = record.get("evidence_files")
    if not isinstance(evidence, dict) or not evidence:
        return False, ["已走查文件指纹不存在"]
    target_root = canonical(target_root)
    mismatches = [
        path for path, expected in evidence.items()
        if _file_fingerprint(target_root, path) != expected
    ]
    return not mismatches, mismatches


def worktrees(candidate: str) -> list[str]:
    result = _git(canonical(candidate), "worktree", "list", "--porcelain")
    if result.returncode != 0:
        return []
    return [
        canonical(line.removeprefix("worktree ").strip())
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    ]


def render(record: dict[str, Any] | None) -> str:
    if not record:
        return "运行现场:无。"
    root = str(record.get("execution_root") or "")
    exists = os.path.isdir(root)
    return (
        f"运行现场:{record.get('phase', 'unknown')}。"
        f"run-id:{record.get('run_id', 'unknown')}。"
        f"执行根:{root or '未知'}({'存在' if exists else '缺失'})。"
        f"模式:{record.get('mode', 'unknown')}。"
    )
