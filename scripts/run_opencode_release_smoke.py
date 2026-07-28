#!/usr/bin/env python3
"""Run and retain a real OpenCode release smoke for an installed project.

This is intentionally separate from the deterministic unit suite: it requires a
real ``opencode`` executable and a configured model.  A successful exit means
that no journal attempt failed during ``init -> spec -> approve -> code``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SmokeError(RuntimeError):
    """A release-smoke assertion failed after its raw evidence was persisted."""


def default_opencode_executable(platform_name: str = os.name) -> str:
    """Return a directly spawnable global Node CLI name for this platform."""
    return "opencode.cmd" if platform_name == "nt" else "opencode"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SmokeError(f"无法读取 JSON 证据 {path}: {error}") from error
    if not isinstance(value, dict):
        raise SmokeError(f"JSON 证据必须是对象: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_opencode(
    target: Path,
    logs: Path,
    label: str,
    prompt: str,
    executable: str,
    timeout_seconds: int,
) -> None:
    """Run one command and always retain both stdout and stderr."""
    log_path = logs / f"{label}.jsonl"
    argv = [executable, "run", "--format", "json", prompt]
    try:
        result = subprocess.run(
            argv,
            cwd=target,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        log_path.write_text(
            f"[runner-error] {type(error).__name__}: {error}\n",
            encoding="utf-8",
        )
        raise SmokeError(f"{label} 无法执行: {error}") from error

    rendered = result.stdout
    if result.stderr:
        rendered += "\n[stderr]\n" + result.stderr
    log_path.write_text(rendered, encoding="utf-8")
    if result.returncode != 0:
        raise SmokeError(
            f"{label} 返回 {result.returncode}；完整输出已保存到 {log_path}"
        )


def core_status(root: Path) -> dict[str, Any]:
    core = root / ".sdlc-pipeline" / "scripts" / "sdlc.py"
    if not core.is_file():
        raise SmokeError(f"未找到已安装 Core: {core}")
    try:
        result = subprocess.run(
            [sys.executable, str(core), "status", "--root", str(root)],
            cwd=root,
            input="{}\n",
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SmokeError(f"读取 smoke status 失败: {error}") from error
    if result.returncode != 0:
        raise SmokeError(f"读取 smoke status 失败: {result.stderr.strip()}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SmokeError(f"status 未输出 JSON: {result.stdout[-1000:]}") from error
    if not isinstance(value, dict):
        raise SmokeError("status JSON 必须是对象")
    return value


def attempt_documents(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    journal = root / ".sdlc-pipeline" / "runs" / "journal"
    documents: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(journal.glob("*/attempts/*/*.json")):
        documents.append((path, read_json(path)))
    return documents


def find_successful_coder_attempt(root: Path) -> tuple[Path, dict[str, Any]]:
    candidates = [
        (path, document)
        for path, document in attempt_documents(root)
        if document.get("operation") == "task-before"
        and document.get("step") == "task-before:coder"
        and document.get("state") == "succeeded"
    ]
    if not candidates:
        raise SmokeError("journal 中没有 succeeded 的 task-before:coder；无法证明 task-after 闭环")
    return candidates[-1]


def handoff_from_attempt(root: Path, attempt: dict[str, Any]) -> dict[str, Any]:
    handoff_path = root / ".sdlc-pipeline" / "runs" / "coder-handoff.json"
    if handoff_path.is_file():
        return read_json(handoff_path)
    result = attempt.get("result")
    if isinstance(result, dict) and isinstance(result.get("handoff"), dict):
        return result["handoff"]
    raise SmokeError("找不到 coder-handoff.json，也没有 journal handoff")


def assert_code_stage(root: Path, logs: Path) -> dict[str, Any]:
    """Assert native task dispatch, task completion, handoff and code gate."""
    raw_log = logs / "04-sdlc-code.jsonl"
    if not raw_log.is_file():
        raise SmokeError(f"缺少 code 原始日志: {raw_log}")
    raw_text = raw_log.read_text(encoding="utf-8", errors="replace")
    if not re.search(r'"subagent_type"\s*:\s*"sdlc-coder"', raw_text):
        raise SmokeError("code 原始日志未出现 task subagent_type=sdlc-coder")

    attempt_path, attempt = find_successful_coder_attempt(root)
    # before_task creates a running attempt; only the plugin's task-after hook
    # finishes it.  Its succeeded state is therefore evidence of both hooks.
    handoff = handoff_from_attempt(root, attempt)
    summary = handoff.get("summary")
    changed_files = handoff.get("changed_files")
    if not isinstance(summary, str) or not summary.strip():
        raise SmokeError("coder handoff 缺少非空 summary")
    if (
        not isinstance(changed_files, list)
        or not changed_files
        or not all(isinstance(path, str) and path.strip() for path in changed_files)
    ):
        raise SmokeError("coder handoff 缺少非空业务 changed_files")

    evidence_path = root / ".sdlc-pipeline" / "runs" / "code-evidence.json"
    evidence = read_json(evidence_path)
    for key in ("compile", "artifact_evidence", "policy"):
        value = evidence.get(key)
        if not isinstance(value, dict) or value.get("ok") is not True:
            raise SmokeError(f"code gate {key} 未通过")
    verifiers = evidence["policy"].get("verifiers")
    if (
        not isinstance(verifiers, list)
        or not verifiers
        or any(not isinstance(item, dict) or item.get("ok") is not True for item in verifiers)
    ):
        raise SmokeError("code gate policy verifiers 未全部通过")
    if evidence.get("ok") is not True:
        raise SmokeError("code-evidence 未标记 ok=true")

    return {
        "ok": True,
        "task_target": "sdlc-coder",
        "task_before_after": "succeeded",
        "task_attempt": attempt_path.as_posix(),
        "handoff_changed_files": len(changed_files),
        "code_gate": "passed",
    }


def assert_no_intermediate_failures(root: Path) -> None:
    failures = []
    for path, attempt in attempt_documents(root):
        state = attempt.get("state")
        error = attempt.get("error")
        if state != "succeeded" or error:
            failures.append({
                "path": path.as_posix(),
                "step": attempt.get("step"),
                "state": state,
                "error": error,
            })
    if failures:
        rendered = json.dumps(failures, ensure_ascii=False)
        raise SmokeError(f"release smoke 存在中间失败 attempt: {rendered}")


def assert_no_raw_tool_errors(logs: Path) -> None:
    """Fail on OpenCode tool errors that did not reach the Core journal."""
    errors = []
    for log_path in sorted(logs.glob("*.jsonl")):
        for line_number, line in enumerate(
            log_path.read_text(encoding="utf-8", errors="replace").splitlines(),
            start=1,
        ):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            part = event.get("part")
            state = part.get("state") if isinstance(part, dict) else None
            if not isinstance(state, dict) or state.get("status") != "error":
                continue
            errors.append({
                "log": log_path.name,
                "line": line_number,
                "tool": part.get("tool"),
                "error": state.get("error"),
            })
    if errors:
        raise SmokeError(
            "release smoke 存在 OpenCode 中间 tool error: "
            + json.dumps(errors, ensure_ascii=False)
        )


def require_gate(status: dict[str, Any], gate: str) -> None:
    gates = status.get("gates")
    if not isinstance(gates, dict) or gates.get(gate) is not True:
        raise SmokeError(f"{gate} gate 未通过: {json.dumps(status, ensure_ascii=False)}")


def assert_spec_argument_source(root: Path, marker: str) -> dict[str, Any]:
    """Prove that the argument passed to ``/sdlc-spec`` became source evidence."""
    source_dir = root / ".sdlc-pipeline" / "runs" / "sources"
    matches: list[dict[str, Any]] = []
    for path in sorted(source_dir.glob("SRC-*.json")):
        source = read_json(path)
        if marker in str(source.get("content", "")):
            matches.append(source)
    if not matches:
        raise SmokeError(
            "spec Candidate 虽已生成，但 /sdlc-spec 命令参数没有进入 Source Envelope"
        )
    return matches[-1]


def run_smoke(
    target: Path,
    logs: Path,
    executable: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    if not (target / ".sdlc-pipeline" / "installation.json").is_file():
        raise SmokeError("target 不是已通过 install_project 安装的项目")
    logs.mkdir(parents=True, exist_ok=True)

    run_opencode(target, logs, "01-sdlc-init", "/sdlc-init", executable, timeout_seconds)
    require_gate(core_status(target), "init")

    spec_marker = "SMOKE_ARGUMENT_PROBE_7F3A"
    specification = (
        "/sdlc-spec 为这个 Electron scaffold 创建最小候选：在首页增加“Pipeline ready”"
        "卡片，显示标题、已发布 Specs、测试计划状态。只需要 unit verification（test_key=unit；"
        "selector 留空），不添加 functional。请读取 scaffold.json 并逐字使用已声明的 extension_points；"
        "生成候选、validate 并展示 candidate ID/hash，不要发布，也不要询问额外问题。"
        f" 命令参数摄取探针：{spec_marker}。"
    )
    run_opencode(target, logs, "02-sdlc-spec", specification, executable, timeout_seconds)
    candidate = core_status(target).get("spec_candidate")
    if not isinstance(candidate, dict) or candidate.get("state") != "ready":
        raise SmokeError("spec 未生成 ready Candidate")
    candidate_id = candidate.get("candidate_id")
    content_hash = candidate.get("current_hash")
    if not isinstance(candidate_id, str) or not isinstance(content_hash, str):
        raise SmokeError("ready Candidate 缺少 candidate_id 或 current_hash")
    spec_source = assert_spec_argument_source(target, spec_marker)

    approval = (
        "/sdlc-spec 确认发布。请只使用当前 candidate 的 "
        f"candidate_id={candidate_id}、content_hash={content_hash} 和 confirmed=true "
        "调用 sdlc_approve_candidate；不要重新生成或修改 Candidate。"
    )
    run_opencode(target, logs, "03-sdlc-spec-approve", approval, executable, timeout_seconds)
    approved = core_status(target)
    require_gate(approved, "spec")
    published = approved.get("spec_candidate")
    if not isinstance(published, dict) or published.get("state") != "published":
        raise SmokeError("spec approval 未得到 published Candidate")

    run_opencode(target, logs, "04-sdlc-code", "/sdlc-code", executable, timeout_seconds)
    require_gate(core_status(target), "code")
    code_report = assert_code_stage(target, logs)
    assert_no_intermediate_failures(target)
    assert_no_raw_tool_errors(logs)
    return {
        "ok": True,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "target": str(target),
        "logs_dir": str(logs),
        "code": code_report,
        "spec_argument_source_id": spec_source.get("source_id"),
        "intermediate_failures": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--logs-dir", type=Path, required=True)
    parser.add_argument(
        "--opencode",
        default=os.environ.get("OPENCODE_BIN", default_opencode_executable()),
        help="OpenCode executable (default: OPENCODE_BIN or platform global CLI)",
    )
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()
    target = args.target.resolve()
    logs = args.logs_dir.resolve()
    report_path = logs / "release-smoke.json"
    try:
        report = run_smoke(target, logs, args.opencode, args.timeout_seconds)
    except Exception as error:
        report = {
            "ok": False,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "target": str(target),
            "logs_dir": str(logs),
            "error_type": type(error).__name__,
            "error": str(error),
        }
        write_json(report_path, report)
        print(json.dumps(report, ensure_ascii=False))
        return 1
    write_json(report_path, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
