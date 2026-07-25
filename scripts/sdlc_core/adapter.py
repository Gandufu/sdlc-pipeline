from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .artifacts import load_current_spec, require_code_ready
from .common import SdlcError, read_json, utc_now, write_json
from .trace import changed_paths, validate_diff, verify_extension_points


MAX_CONTEXT_CHARS = 30_000


def validate_write_path(root: Path, path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise SdlcError("禁止写入项目之外的路径") from exc
    from .trace import allowed_design_paths, matches_path, scaffold

    contract = scaffold(root)
    if matches_path(relative, contract["protected_paths"]):
        raise SdlcError(f"禁止修改 protected path: {relative}")
    allowed = sorted(set(contract["allowed_paths"]) | set(allowed_design_paths(root)))
    if not matches_path(relative, allowed):
        raise SdlcError(f"路径不在设计/脚手架允许范围: {relative}")
    return {"ok": True, "path": relative}


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    candidates = [text]
    candidates += re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    for candidate in reversed(candidates):
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    raise SdlcError("subagent 输出中没有可解析的 JSON handoff")


def _context_files(root: Path) -> list[str]:
    spec = load_current_spec(root)
    paths = {
        "docs/sdlc/current/requirements.json",
        "docs/sdlc/current/design.json",
        "docs/sdlc/current/test-plan.json",
        ".sdlc-pipeline/lifecycle.json",
        ".sdlc-pipeline/scaffold.json",
    }
    contract = read_json(root / ".sdlc-pipeline" / "scaffold.json")
    template_id = contract["template_id"]
    manifest_path = root / ".sdlc-pipeline" / "templates" / "manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        template = next(
            (item for item in manifest if item["id"] == template_id), None
        )
        if template:
            for stack in template.get("stacks", []):
                path = f".sdlc-pipeline/rules/{stack}.md"
                if (root / path).exists():
                    paths.add(path)
    convention = f".sdlc-pipeline/templates/conventions/{template_id}.md"
    if (root / convention).exists():
        paths.add(convention)
    if (root / "docs" / "existing-framework.md").exists():
        paths.add("docs/existing-framework.md")
    for item in spec["design"]["items"]:
        for pattern in item["allowed_paths"]:
            if "*" not in pattern:
                path = root / pattern
                if path.is_file():
                    paths.add(pattern)
                elif path.is_dir():
                    for candidate in path.rglob("*"):
                        if candidate.is_file() and candidate.stat().st_size <= 80_000:
                            paths.add(candidate.relative_to(root).as_posix())
    return sorted(paths)


def build_context_pack(root: Path, role: str) -> dict[str, Any]:
    files = _context_files(root)
    packs: list[list[dict[str, str]]] = [[]]
    size = 0
    repeated = 0
    for name in files:
        path = root / name
        if not path.exists() or (
            path.stat().st_size > 80_000
            and name != "docs/sdlc/current/requirements.json"
        ):
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        if name == "docs/sdlc/current/requirements.json":
            requirements = json.loads(content)
            requirements["source_inputs"] = [
                {
                    "source": item["source"],
                    "sha256": hashlib.sha256(
                        item["content"].encode("utf-8")
                    ).hexdigest(),
                    "characters": len(item["content"]),
                }
                for item in requirements.get("source_inputs", [])
            ]
            content = json.dumps(requirements, ensure_ascii=False, indent=2) + "\n"
        entry_size = len(name) + len(content)
        if size and size + entry_size > MAX_CONTEXT_CHARS:
            packs.append([])
            size = 0
        packs[-1].append({"path": name, "content": content})
        size += entry_size
        if name.startswith("docs/sdlc/current/"):
            repeated += len(content)
    directory = root / ".sdlc-pipeline" / "runs" / "context"
    paths = []
    for index, pack in enumerate(packs, 1):
        path = directory / f"{role}-{index:02d}.json"
        write_json(path, {"role": role, "part": index, "files": pack})
        paths.append(path.relative_to(root).as_posix())
    return {
        "paths": paths,
        "parts": len(paths),
        "characters": sum(
            len(item["content"]) for pack in packs for item in pack
        ),
        "repeated_chars": repeated,
    }


def before_task(root: Path, role: str) -> dict[str, Any]:
    if role not in {"coder", "executor"}:
        raise SdlcError(f"不允许的 subagent: {role}")
    from .status import status

    current = status(root)
    if role == "coder" and not (
        current["gates"]["init"] and current["gates"]["spec"]
    ):
        raise SdlcError("coder 门禁要求 init 与 spec 均通过")
    if role == "executor" and not current["gates"]["code"]:
        raise SdlcError("executor 门禁要求真实 compile/restart/verify 证据")
    if role == "coder":
        require_code_ready(load_current_spec(root))
    verify_extension_points(root)
    before = changed_paths(root)
    write_json(root / ".sdlc-pipeline" / "runs" / f"{role}-before.json", {
        "created_at": utc_now(),
        "changed_paths": before,
    })
    context = build_context_pack(root, role)
    from .runs import record_tokens

    record_tokens(
        root,
        role,
        repeated_chars=context["repeated_chars"],
        source="context-pack",
    )
    return {
        "ok": True,
        "role": role,
        "context_pack": context,
        "instruction": (
            "只读取列出的 context pack；超过一包时按模块逐包处理。"
            "最终只返回约定 JSON handoff。"
        ),
    }


def validate_coder_handoff(root: Path, text: str) -> dict[str, Any]:
    value = _extract_json(text)
    required = {"design_to_code", "test_to_files", "changed_files", "open_issues"}
    missing = sorted(required - set(value))
    if missing:
        raise SdlcError(f"coder handoff 缺少字段: {missing}")
    before = read_json(root / ".sdlc-pipeline" / "runs" / "coder-before.json")
    diff = validate_diff(root, before.get("changed_paths", []))
    declared = sorted(set(value["changed_files"]))
    actual = sorted(set(diff["changed_paths"]))
    missing_actual = sorted(set(actual) - set(declared))
    invented = sorted(set(declared) - set(actual))
    if missing_actual or invented:
        raise SdlcError(
            f"coder handoff 与 Git diff 不一致；遗漏={missing_actual}，虚构={invented}"
        )
    spec = load_current_spec(root)
    d_ids = {item["id"] for item in spec["design"]["items"]}
    t_ids = {item["id"] for item in spec["test_plan"]["items"]}
    if set(value["design_to_code"]) != d_ids:
        raise SdlcError("design_to_code 必须完整覆盖当前 D-id")
    if set(value["test_to_files"]) != t_ids:
        raise SdlcError("test_to_files 必须完整覆盖当前 T-id")
    for mapping in (value["design_to_code"], value["test_to_files"]):
        if any(not paths for paths in mapping.values()):
            raise SdlcError("D/T 映射不能包含空路径列表")
    value["validated_at"] = utc_now()
    value["compiled_claim_ignored"] = True
    write_json(root / ".sdlc-pipeline" / "runs" / "coder-handoff.json", value)
    return {"ok": True, "handoff": value, "diff": diff}


def validate_executor_handoff(root: Path, text: str) -> dict[str, Any]:
    value = _extract_json(text)
    required = {"results", "open_issues"}
    missing = sorted(required - set(value))
    if missing:
        raise SdlcError(f"executor handoff 缺少字段: {missing}")
    spec = load_current_spec(root)
    expected = {item["id"] for item in spec["test_plan"]["items"]}
    actual = {item.get("id") for item in value["results"]}
    if actual != expected:
        raise SdlcError(
            f"executor 结果未完整覆盖 T-id；缺少={sorted(expected-actual)}，"
            f"未知={sorted(actual-expected)}"
        )
    if any(item.get("status") not in {"pass", "fail", "skip"} for item in value["results"]):
        raise SdlcError("executor status 只能是 pass/fail/skip")
    value["validated_at"] = utc_now()
    write_json(root / ".sdlc-pipeline" / "runs" / "executor-handoff.json", value)
    return {"ok": True, "handoff": value}


def after_task(root: Path, role: str, output: str) -> dict[str, Any]:
    if role == "coder":
        return validate_coder_handoff(root, output)
    if role == "executor":
        return validate_executor_handoff(root, output)
    raise SdlcError(f"不允许的 subagent: {role}")
