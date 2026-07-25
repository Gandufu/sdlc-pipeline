from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import load_current_spec
from .common import (
    SdlcError,
    atomic_write,
    git,
    git_available,
    read_json,
    sha256_file,
    sha256_json,
    utc_now,
    write_json,
)
from .lifecycle import artifact_evidence, load_contract
from .runs import token_summary
from .trace import trace_matrix, verify_scaffold


def manifests(root: Path) -> list[Path]:
    directory = root / "docs" / "sdlc" / "versions"
    return sorted(directory.glob("V????/manifest.json")) if directory.exists() else []


def current_version(root: Path) -> str | None:
    items = manifests(root)
    return items[-1].parent.name if items else None


def parent_manifest(root: Path) -> dict[str, Any] | None:
    items = manifests(root)
    return read_json(items[-1]) if items else None


def render_version_summary(manifest: dict[str, Any]) -> str:
    evidence = manifest["evidence"]
    restart = evidence.get("restart", {})
    changed_files = manifest.get("impact", {}).get("changed_files", [])
    open_issues = manifest.get("open_issues", [])
    artifacts = evidence.get("artifacts", {}).get("artifacts", [])
    lines = [
        f"# 交付摘要 {manifest['version']}",
        "",
        f"- 状态：`{manifest['status']}`",
        f"- 摘要：{manifest['summary']}",
        f"- 父版本：`{manifest.get('parent_version') or '无'}`",
        f"- 交付 commit：`{manifest.get('commit') or '待固化'}`",
        f"- Tag：`{manifest['tag']}`",
        "",
        "## 需求与追溯",
        "",
        f"- R-id：{', '.join(f'`{x}`' for x in manifest['ids']['requirements'])}",
        f"- D-id：{', '.join(f'`{x}`' for x in manifest['ids']['design'])}",
        f"- T-id：{', '.join(f'`{x}`' for x in manifest['ids']['tests'])}",
        "",
        "## 交付证据",
        "",
        f"- Compile：`{'pass' if evidence.get('compile', {}).get('ok') else 'fail'}`",
        f"- Stop：`{'pass' if restart.get('stop', {}).get('ok') else 'fail'}`",
        f"- Start：`{'pass' if restart.get('start', {}).get('ok') else 'fail'}`",
        f"- Health：`{'pass' if evidence.get('health', {}).get('ok') else 'fail'}`",
        f"- Tests：`{evidence.get('tests', '')}`",
        "",
        "## 实际变更",
        "",
        *([f"- `{path}`" for path in changed_files] or ["- 无"]),
        "",
        "## Artifacts",
        "",
    ]
    if artifacts:
        for artifact in artifacts:
            lines.append(
                f"- `{artifact.get('path', '')}` "
                f"SHA-256 `{artifact.get('sha256', '')}`"
            )
    else:
        lines.append("- 无")
    lines += ["", "## Open issues", ""]
    lines += [f"- {issue}" for issue in open_issues] or ["- 无"]
    return "\n".join(lines).rstrip() + "\n"


def build_manifest(root: Path, version: str, summary: str) -> dict[str, Any]:
    spec = load_current_spec(root)
    candidate = read_json(root / ".sdlc-pipeline" / "runs" / "version-candidate.json")
    if candidate.get("version") != version or candidate.get("status") != "ready":
        raise SdlcError("版本候选不存在、版本不匹配或测试未通过")
    results_path = root / candidate["test_results"]
    results = read_json(results_path)
    if results.get("status") != "pass":
        raise SdlcError("mandatory 测试未全部通过")
    code_evidence = read_json(root / ".sdlc-pipeline" / "runs" / "code-evidence.json")
    handoff = read_json(
        root / ".sdlc-pipeline" / "runs" / "coder-handoff.json",
        required=False,
    ) or {}
    trace = trace_matrix(root, {
        **handoff.get("design_to_code", {}),
        "tests": handoff.get("test_to_files", {}),
    })
    if not trace["ok"]:
        raise SdlcError("R→D→C→T 追溯不完整，拒绝固化版本")
    scaffold = verify_scaffold(root)
    if not scaffold["ok"]:
        raise SdlcError(f"scaffold 漂移: {scaffold['drift']}")
    current = root / "docs" / "sdlc" / "current"
    parent = parent_manifest(root)
    initial_sha = parent.get("final_git_sha") if parent else git(root, "rev-parse", "HEAD")
    contract = load_contract(root)
    init_report = read_json(root / "docs" / "sdlc" / "init-report.json")
    observed_tools = {
        item["name"]: item for item in init_report.get("tools", {}).get("tools", [])
    }
    return {
        "schema_version": "1.0",
        "version": version,
        "status": "candidate",
        "summary": summary,
        "parent_version": parent.get("version") if parent else None,
        "initial_git_sha": initial_sha,
        "final_git_sha": None,
        "template": {
            "id": scaffold["contract"]["template_id"],
            "version": scaffold["contract"]["template_version"],
            "scaffold_hash": sha256_file(root / ".sdlc-pipeline" / "scaffold.json"),
            "lifecycle_hash": sha256_file(root / ".sdlc-pipeline" / "lifecycle.json"),
        },
        "environment": {
            item["name"]: {
                "constraint": item.get("version", ""),
                "observed": observed_tools.get(item["name"], {}).get("tail", "").splitlines()[:3],
            }
            for item in contract["tools"]
        },
        "artifact_hashes": {
            "requirements": sha256_file(current / "requirements.json"),
            "design": sha256_file(current / "design.json"),
            "test_plan": sha256_file(current / "test-plan.json"),
            "test_results": sha256_file(results_path),
        },
        "ids": {
            "requirements": [x["id"] for x in spec["requirements"]["items"]],
            "design": [x["id"] for x in spec["design"]["items"]],
            "tests": [x["id"] for x in spec["test_plan"]["items"]],
        },
        "requirement_records": {
            item["id"]: {
                "sha256": sha256_json(item),
                "supersedes": item.get("supersedes"),
            }
            for item in spec["requirements"]["items"]
        },
        "impact": {
            "flow": spec["flow"],
            "changed_files": handoff.get("changed_files", []),
            "full_scan": handoff.get("full_scan", False),
            "full_scan_reason": handoff.get("full_scan_reason"),
        },
        "trace": trace["rows"],
        "evidence": {
            "compile": code_evidence["compile"],
            "restart": {"stop": code_evidence["stop"], "start": code_evidence["start"]},
            "health": code_evidence["health"],
            "artifacts": artifact_evidence(root),
            "tests": candidate["test_results"],
        },
        "token_usage": token_summary(root),
        "open_issues": sorted(set(
            handoff.get("open_issues", []) + results.get("open_issues", [])
        )),
        "commit": None,
        "tag": f"sdlc/{version}",
        "created_at": utc_now(),
        "closed_at": None,
    }


def finalize(root: Path, version: str, summary: str, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise SdlcError("sdlc_finalize 必须携带用户明确确认")
    if not git_available(root):
        raise SdlcError("目标项目不是 Git 工作树")
    tag = f"sdlc/{version}"
    if git(root, "tag", "--list", tag, check=False):
        raise SdlcError(f"tag 已存在: {tag}")
    manifest = build_manifest(root, version, summary)
    path = root / "docs" / "sdlc" / "versions" / version / "manifest.json"
    # A commit cannot contain its own SHA. First commit the delivered source and
    # test results, then record that immutable delivery SHA in a small evidence
    # commit which is the annotated tag target.
    git(root, "add", "-A")
    status = git(root, "status", "--short")
    if not status:
        raise SdlcError("工作树没有可固化的变更")
    message = f"sdlc({version}): complete {summary}"
    git(root, "commit", "-m", message)
    delivery_sha = git(root, "rev-parse", "HEAD")
    manifest["status"] = "closed"
    manifest["final_git_sha"] = delivery_sha
    manifest["commit"] = delivery_sha
    manifest["closed_at"] = utc_now()
    write_json(path, manifest)
    summary_path = path.with_name("summary.md")
    atomic_write(summary_path, render_version_summary(manifest))
    git(
        root,
        "add",
        path.relative_to(root).as_posix(),
        summary_path.relative_to(root).as_posix(),
    )
    git(root, "commit", "-m", f"sdlc({version}): record evidence")
    evidence_sha = git(root, "rev-parse", "HEAD")
    git(root, "tag", "-a", tag, "-m", f"SDLC {version}: {summary}")
    candidate_path = root / ".sdlc-pipeline" / "runs" / "version-candidate.json"
    candidate = read_json(candidate_path)
    candidate["status"] = "closed"
    candidate["final_git_sha"] = delivery_sha
    write_json(candidate_path, candidate)
    return {
        "ok": True,
        "version": version,
        "commit": delivery_sha,
        "evidence_commit": evidence_sha,
        "tag": tag,
        "message": message,
    }
