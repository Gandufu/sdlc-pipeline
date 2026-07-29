from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .artifacts import (
    current_spec_hashes,
    load_current_spec,
    require_code_ready,
    write_test_results,
)
from .common import (
    SdlcError,
    atomic_write,
    next_version,
    read_json,
    run_command,
    sha256_file,
    utc_now,
)
from .layout import (
    contracts_root,
    evidence_root,
    lifecycle_path as layout_lifecycle_path,
    rules_root,
    scaffold_path,
    templates_root,
)
from .records import (
    write_compact_index,
    write_markdown_record,
)
from .runs import pid_alive, read_active, record_active, retain_process, stop_active
from .stores import (
    read_evidence_record,
    read_work_record,
    write_evidence_record,
    write_work_record,
)
from .trace import (
    changed_path_fingerprints,
    implementation_fingerprint,
    test_source_fingerprint,
    verify_scaffold,
    worktree_fingerprint,
)
from .schema_validation import validate_schema_instance
from .tooling import ensure_tooling_ignores

from .policies import evaluate_hard_policies, executable_verifiers

ALLOWED_VARIABLES = {"PROJECT_ROOT", "PYTHON", "PORT"}
MANDATORY_CONTRACT_FIELDS = {
    "schema_version", "project_type", "tools", "commands", "health",
    "artifacts", "tests",
}


def ensure_project_agents_file(root: Path) -> dict[str, str]:
    """Create deterministic project guidance without replacing user rules."""
    path = root / "AGENTS.md"
    if path.exists():
        return {"status": "existing", "path": "AGENTS.md"}
    contract = load_contract(root)
    scaffold = read_json(scaffold_path(root))
    command_lines = []
    for name in ("install", "compile", "start", "stop", "restart"):
        command = contract["commands"].get(name)
        if command:
            command_lines.append(f"- `{name}`：`{' '.join(command['argv'])}`")
    test_lines = [
        f"- `{name}`：`{' '.join(command['argv'])}`"
        for name, command in contract["tests"].items()
        if command
    ]
    active_rules = read_json(
        contracts_root(root) / "active-rules.json",
        required=False,
    ) or {"rules": []}
    rule_lines = [
        f"- `{item['path']}`"
        for item in active_rules.get("rules", [])
    ]
    lines = [
        "# 项目协作说明",
        "",
        "此文件由 SDLC init 生成；可在 OpenCode 原生 `/init` 中继续增补。",
        "",
        "## 项目上下文",
        "",
        f"- 项目类型：`{contract['project_type']}`",
        f"- 脚手架：`{scaffold['template_id']}`",
        f"- 扩展点：{', '.join(item['id'] for item in scaffold['extension_points'])}",
        "",
        "## 生命周期命令",
        "",
        *command_lines,
        "",
        "## 测试命令",
        "",
        *(test_lines or ["- 当前 lifecycle 合约未声明测试命令。"]),
        "",
        "- Verification frontmatter 的 `test_key` 填写冒号左侧逻辑键（当前为 `functional`），",
        "不能填写 `pnpm functional` 等右侧 shell 命令。",
        "",
        "## SDLC 规则",
        "",
        "仅加载所选模板在 init 阶段激活的框架规则：",
        "",
        *(rule_lines or ["- 当前模板未声明框架规则。"]),
        "",
        "- 正式需求、设计、测试计划使用中文；原始输入、代码标识、命令和协议字段保持原样。",
        "- 通过 `/sdlc-spec`、`/sdlc-code`、`/sdlc-test` 依次推进，不直接编辑 `docs/sdlc` 正式产物。",
        "- code 阶段派发 coder 子 agent；test 阶段派发 tester 子 agent。",
        "- tester handoff 后由 plugin 只触发一次 verify_delivery；Core 负责测试生命周期与证据。",
        "",
    ]
    atomic_write(path, "\n".join(lines))
    return {"status": "created", "path": "AGENTS.md"}


def activate_template_rules(root: Path) -> dict[str, Any]:
    """Materialize the selected template's rule set as init evidence."""
    scaffold = read_json(scaffold_path(root))
    template_id = scaffold["template_id"]
    manifest_path = templates_root(root) / "manifest.json"
    rules: list[dict[str, Any]] = []
    source = "unregistered-template"
    rule_ids = scaffold.get("rules", [])
    if manifest_path.exists():
        from .bootstrap import template_registry

        templates = template_registry(templates_root(root).parent)
        template = next(
            (item for item in templates if item["id"] == template_id),
            None,
        )
        if template is not None:
            source = "templates/manifest.json"
            rule_ids = template["rules"]
    if not isinstance(rule_ids, list) or any(
        not isinstance(name, str) for name in rule_ids
    ):
        raise SdlcError(f"模板 {template_id} 的 rules 必须是字符串数组")
    if rule_ids:
        if source == "unregistered-template":
            source = "scaffold.json"
        for name in rule_ids:
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
                raise SdlcError(f"模板 {template_id} 声明了非法 rule ID: {name}")
            relative = f".sdlc-pipeline/runtime/rules/{name}.md"
            path = root / relative
            if not path.is_file():
                raise SdlcError(f"模板 {template_id} 缺少声明的 rule: {relative}")
            entry: dict[str, Any] = {
                "id": name,
                "path": relative,
                "sha256": sha256_file(path),
                "classification": ["guidance"],
            }
            policy_relative = f".sdlc-pipeline/runtime/rules/{name}.policy.json"
            policy_path = root / policy_relative
            if policy_path.is_file():
                policy = read_json(policy_path)
                validate_schema_instance(root, "rule-policy.schema.json", policy)
                entry["policy_path"] = policy_relative
                entry["policy_sha256"] = sha256_file(policy_path)
                entry["classification"] = policy["classification"]
            rules.append(entry)
    active = {
        "schema_version": "1.0",
        "template_id": template_id,
        "source": source,
        "rules": rules,
    }
    write_compact_index(contracts_root(root) / "active-rules.json", active)
    return active


def contract_path(root: Path) -> Path:
    return layout_lifecycle_path(root)


def load_contract(root: Path) -> dict[str, Any]:
    value = read_json(contract_path(root))
    missing = sorted(MANDATORY_CONTRACT_FIELDS - set(value))
    validate_schema_instance(root, "lifecycle.schema.json", value)
    if missing:
        raise SdlcError(f"lifecycle.json 缺少字段: {', '.join(missing)}")
    commands = value["commands"]
    for name in ("install", "compile", "start", "stop", "restart"):
        if name not in commands:
            raise SdlcError(f"lifecycle commands 缺少 {name}")
    for section in (commands, value["tests"]):
        for name, command in section.items():
            if command is None:
                continue
            validate_command(command, name)
    for tool in value["tools"]:
        if "probe" not in tool:
            raise SdlcError(f"工具 {tool.get('name')} 缺少 probe")
        validate_command(tool["probe"], f"tool:{tool.get('name')}")
    return value


def validate_command(command: dict[str, Any], name: str) -> None:
    if not isinstance(command, dict):
        raise SdlcError(f"{name} 必须是命令对象")
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv or not all(
        isinstance(item, str) and item for item in argv
    ):
        raise SdlcError(f"{name}.argv 必须是非空字符串数组")
    for item in argv:
        cursor = 0
        while "${" in item[cursor:]:
            start = item.index("${", cursor)
            end = item.find("}", start)
            if end < 0:
                raise SdlcError(f"{name} 包含未闭合变量: {item}")
            variable = item[start + 2:end]
            if variable not in ALLOWED_VARIABLES:
                raise SdlcError(f"{name} 使用未受控变量: {variable}")
            cursor = end + 1


def _variables(root: Path, contract: dict[str, Any]) -> dict[str, str]:
    return {
        "PROJECT_ROOT": str(root),
        "PYTHON": os.environ.get("PYTHON", "python"),
        "PORT": str(contract.get("port", 8080)),
    }


def _expand(value: str, variables: dict[str, str]) -> str:
    for name, replacement in variables.items():
        value = value.replace("${" + name + "}", replacement)
    return value


def resolve_command(root: Path, command: dict[str, Any]) -> tuple[list[str], Path, int]:
    contract = load_contract(root)
    variables = _variables(root, contract)
    argv_key = "windows_argv" if os.name == "nt" and command.get("windows_argv") else "argv"
    argv = [_expand(item, variables) for item in command[argv_key]]
    cwd = root / command.get("cwd", ".")
    try:
        cwd.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise SdlcError(f"命令工作目录越出项目: {cwd}") from exc
    return argv, cwd, int(command.get("timeout_seconds", 300))


def log_dir(root: Path) -> Path:
    path = evidence_root(root) / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def execute_command(
    root: Path,
    name: str,
    command: dict[str, Any],
    *,
    selector: str | None = None,
) -> dict[str, Any]:
    argv, cwd, timeout = resolve_command(root, command)
    if selector is not None:
        if command.get("allow_selector") is not True:
            raise SdlcError(f"{name} 不允许 selector")
        selector_path = root / selector
        try:
            relative_selector = selector_path.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise SdlcError(f"{name} selector 越出项目: {selector}") from exc
        if (
            not selector.startswith("tests/")
            or not selector_path.is_file()
            or relative_selector.as_posix() != selector
        ):
            raise SdlcError(f"{name} selector 必须是已存在的 tests/ 项目内文件: {selector}")
        argv.append(selector)
    started = time.monotonic()
    result = run_command(argv, cwd=cwd, timeout=timeout, check=False)
    duration = int((time.monotonic() - started) * 1000)
    stamp = int(time.time() * 1000)
    path = log_dir(root) / f"{stamp}-{name.replace(':', '-')}.log"
    atomic_write(
        path,
        f"$ {json.dumps(argv, ensure_ascii=False)}\n"
        f"[stdout]\n{result.stdout}\n[stderr]\n{result.stderr}\n"
        f"[exit]\n{result.returncode}\n",
    )
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "duration_ms": duration,
        "log": path.relative_to(root).as_posix(),
        "tail": (result.stderr or result.stdout)[-4000:],
        "argv": argv,
    }


def run_policy_gate(root: Path, phase: str) -> dict[str, Any]:
    hard = evaluate_hard_policies(root)
    commands = load_contract(root)["commands"]
    results = []
    for verifier in executable_verifiers(root, phase):
        key = verifier["command_key"]
        if key not in commands:
            raise SdlcError(
                f"policy {verifier['rule_id']}:{verifier['id']} "
                f"引用未知 lifecycle command key: {key}"
            )
        result = execute_command(
            root,
            f"policy-{verifier['rule_id']}-{verifier['id']}",
            commands[key],
        )
        results.append({**verifier, **result})
    report = {
        "schema_version": "1.0",
        "phase": phase,
        "ok": hard["ok"] and all(item["ok"] for item in results),
        "hard": hard,
        "verifiers": results,
        "created_at": utc_now(),
        "source_fingerprint": worktree_fingerprint(root),
    }
    write_evidence_record(
        root,
        f"policy/{phase}",
        report,
        state="passed" if report["ok"] else "failed",
        title=f"{phase} policy evidence",
    )
    if not report["ok"]:
        raise SdlcError(
            f"{phase} policy gate 未通过；hard={hard['violations']}，"
            f"verifiers={[item['id'] for item in results if not item['ok']]}"
        )
    return report


def probe_tools(root: Path) -> dict[str, Any]:
    contract = load_contract(root)
    results = []
    missing = []
    for tool in contract["tools"]:
        result = execute_command(root, f"probe-{tool['name']}", tool["probe"])
        constraint = tool.get("version", "")
        version_ok = _version_satisfies(result["tail"], constraint)
        result["ok"] = result["ok"] and version_ok
        item = {
            "name": tool["name"],
            "constraint": constraint,
            "version_ok": version_ok,
            "required": tool.get("required", True),
            **result,
        }
        results.append(item)
        if item["required"] and not item["ok"]:
            missing.append(tool["name"])
    return {
        "ok": not missing,
        "tools": results,
        "missing": missing,
        "install_policy": "template_declared_auto_install_on_init",
    }


def _version_satisfies(output: str, constraint: str) -> bool:
    if not constraint or not constraint.startswith(">="):
        return True
    required = tuple(int(part) for part in re.findall(r"\d+", constraint[2:])[:3])
    match = re.search(r"\d+(?:\.\d+){0,2}", output)
    if not match:
        return False
    actual = tuple(int(part) for part in match.group(0).split("."))
    width = max(len(required), len(actual))
    return actual + (0,) * (width - len(actual)) >= required + (0,) * (width - len(required))


def install_system_tool(root: Path, name: str, approved: bool) -> dict[str, Any]:
    if not approved:
        raise SdlcError("系统级安装必须先获得用户明确确认")
    contract = load_contract(root)
    tool = next((item for item in contract["tools"] if item["name"] == name), None)
    if not tool:
        raise SdlcError(f"lifecycle 未声明工具: {name}")
    command = tool.get("system_install")
    if not command:
        raise SdlcError(f"模板未提供 {name} 的受控系统安装命令，请人工安装后重试 init")
    if os.name != "nt" and command.get("windows_only"):
        raise SdlcError(f"{name} 的自动安装只支持 Windows")
    validate_command(command, f"system_install:{name}")
    result = execute_command(root, f"system-install-{name}", command)
    if not result["ok"]:
        raise SdlcError(f"{name} 系统安装失败，日志 {result['log']}\n{result['tail']}")
    reprobe = execute_command(root, f"reprobe-{name}", tool["probe"])
    if not reprobe["ok"]:
        raise SdlcError(f"{name} 安装命令成功但重新探测失败")
    return {"ok": True, "tool": name, "install": result, "probe": reprobe}


def run_phase(root: Path, action: str) -> dict[str, Any]:
    contract = load_contract(root)
    if action not in contract["commands"]:
        raise SdlcError(f"未知 lifecycle action: {action}")
    command = contract["commands"][action]
    if command is None:
        return {"ok": True, "action": action, "skipped": True}
    result = execute_command(root, action, command)
    if not result["ok"]:
        raise SdlcError(f"{action} 失败，日志 {result['log']}\n{result['tail']}")
    return {"action": action, **result}


def start(root: Path) -> dict[str, Any]:
    contract = load_contract(root)
    command = contract["commands"]["start"]
    argv, cwd, _timeout = resolve_command(root, command)
    stop_active(root)
    stamp = int(time.time() * 1000)
    log = log_dir(root) / f"{stamp}-start.log"
    stream = log.open("a", encoding="utf-8")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
            shell=False,
            creationflags=flags,
            start_new_session=os.name != "nt",
        )
    except OSError as exc:
        stream.close()
        raise SdlcError(f"启动失败: {exc}") from exc
    stream.close()
    time.sleep(min(float(command.get("startup_grace_seconds", 1)), 5))
    if process.poll() is not None:
        tail = log.read_text(encoding="utf-8", errors="replace")[-4000:]
        raise SdlcError(f"进程启动后立即退出 ({process.returncode})\n{tail}")
    record_active(root, {
        "pid": process.pid,
        "argv": argv,
        "cwd": str(cwd),
        "log": log.relative_to(root).as_posix(),
        "started_at": utc_now(),
    })
    retain_process(process)
    return {"ok": True, "pid": process.pid, "log": log.relative_to(root).as_posix()}


def verify_health(root: Path) -> dict[str, Any]:
    contract = load_contract(root)
    results = []
    active = read_active(root)
    for check in contract["health"]:
        kind = check["type"]
        started = time.monotonic()
        ok = False
        detail = ""
        timeout = int(check.get("timeout_seconds", 10))
        try:
            if kind == "process":
                pid = int((active or {}).get("pid", 0))
                ok = pid_alive(pid)
                detail = f"pid={pid}"
            elif kind == "http":
                url = _expand(check["url"], _variables(root, contract))
                request = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    body = response.read(8192).decode("utf-8", errors="replace")
                    expected = check.get("contains")
                    ok = 200 <= response.status < 400 and (
                        expected is None or expected in body
                    )
                    detail = f"status={response.status}"
            elif kind == "tcp":
                host = check.get("host", "127.0.0.1")
                port = int(_expand(str(check["port"]), _variables(root, contract)))
                with socket.create_connection((host, port), timeout=timeout):
                    ok, detail = True, f"{host}:{port}"
            elif kind == "file":
                path = root / check["path"]
                ok, detail = path.exists(), check["path"]
            elif kind == "command":
                result = execute_command(root, "health-command", check["command"])
                ok, detail = result["ok"], result["log"]
            else:
                raise SdlcError(f"未知 health 类型: {kind}")
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            detail = str(exc)
        results.append({
            "type": kind,
            "ok": ok,
            "detail": detail,
            "duration_ms": int((time.monotonic() - started) * 1000),
        })
    return {"ok": all(item["ok"] for item in results), "checks": results}


def artifact_evidence(root: Path) -> dict[str, Any]:
    contract = load_contract(root)
    items = []
    patterns = []
    missing = []
    for pattern in contract["artifacts"]:
        matches = sorted(root.glob(pattern))
        files = [path for path in matches if path.is_file()]
        patterns.append({
            "pattern": pattern,
            "matches": [path.relative_to(root).as_posix() for path in files],
        })
        if not files:
            missing.append(pattern)
        for path in files:
            items.append({
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    return {
        "ok": bool(items) and not missing,
        "patterns": patterns,
        "missing": missing,
        "artifacts": items,
    }


def compile_restart_verify(root: Path) -> dict[str, Any]:
    require_code_ready(load_current_spec(root))
    read_work_record(root, "coder-handoff")
    drift = verify_scaffold(root)
    if not drift["ok"]:
        raise SdlcError(f"脚手架漂移，拒绝编译: {drift['drift']}")
    compile_result = run_phase(root, "compile")
    policy = run_policy_gate(root, "code")
    artifacts = artifact_evidence(root)
    if not artifacts["ok"]:
        raise SdlcError("code 阶段 artifact 验证未通过")
    started: dict[str, Any] = {}
    health: dict[str, Any] = {}
    stopped: dict[str, Any] = {"stopped": False}
    try:
        started = start(root)
        health = verify_health(root)
        if not health["ok"]:
            raise SdlcError("code 阶段 readiness 未通过")
    finally:
        stopped = stop_active(root)
    evidence = {
        "ok": True,
        "compiled_at": utc_now(),
        "compile": compile_result,
        "start": started,
        "health": health,
        "stop": stopped,
        "artifact_evidence": artifacts,
        "policy": policy,
        "source_fingerprint": implementation_fingerprint(root),
        "worktree": worktree_fingerprint(root),
        "spec_hashes": current_spec_hashes(root),
    }
    write_evidence_record(
        root, "code", evidence, state="passed", title="Code gate evidence"
    )
    return evidence


def init_project(
    root: Path,
    *,
    auto_install_missing: bool = False,
) -> dict[str, Any]:
    drift = verify_scaffold(root)
    if not drift["ok"]:
        raise SdlcError(f"脚手架初始校验失败: {drift['drift']}")
    tooling_ignore = ensure_tooling_ignores(root, strict=True)
    active_rules = activate_template_rules(root)
    tools = probe_tools(root)
    system_installs = []
    if not tools["ok"] and auto_install_missing:
        for name in tools["missing"]:
            system_installs.append(install_system_tool(root, name, True))
        tools = probe_tools(root)
    if not tools["ok"]:
        report = {
            "schema_version": "1.0",
            "status": "blocked",
            "created_at": utc_now(),
            "tools": tools,
            "system_installs": system_installs,
            "active_rules": active_rules,
        }
        _write_init_report(root, report)
        return report
    install = run_phase(root, "install")
    compile_result = run_phase(root, "compile")
    started = start(root)
    health = verify_health(root)
    artifacts = artifact_evidence(root)
    keep_running = bool(load_contract(root).get("keep_running_after_init", False))
    stopped = {"ok": True, "stopped": False, "reason": "contract_keep_running"}
    if not keep_running:
        stopped = stop_active(root)
    status = "pass" if health["ok"] and artifacts["ok"] else "fail"
    report = {
        "schema_version": "1.0",
        "status": status,
        "created_at": utc_now(),
        "tools": tools,
        "system_installs": system_installs,
        "install": install,
        "compile": compile_result,
        "start": started,
        "health": health,
        "artifacts": artifacts,
        "stop": stopped,
        "keep_running_after_init": keep_running,
        "active_rules": active_rules,
        "tooling_ignore": tooling_ignore,
    }
    if status != "pass":
        _write_init_report(root, report)
        raise SdlcError("init 的 health/artifact 验收失败")
    report["agents_md"] = ensure_project_agents_file(root)
    _write_init_report(root, report)
    return report


def _write_init_report(root: Path, report: dict[str, Any]) -> None:
    write_evidence_record(
        root,
        "init",
        report,
        state=report["status"],
        title="SDLC Init 报告",
    )


def _validate_test_sources(
    root: Path,
    code_evidence: dict[str, Any],
) -> dict[str, Any]:
    spec = load_current_spec(root)
    declared = {
        item["selector"].replace("\\", "/")
        for item in spec["test_plan"]["items"]
        if item.get("selector")
    }
    missing = sorted(path for path in declared if not (root / path).is_file())
    if missing:
        raise SdlcError(f"Spec 声明的测试脚本不存在: {missing}")

    before = {
        item["path"]: item
        for item in code_evidence.get("worktree", {}).get("entries", [])
    }
    current = {
        item["path"]: item
        for item in changed_path_fingerprints(root)["entries"]
    }
    changed = sorted(
        path for path in set(before) | set(current)
        if before.get(path) != current.get(path)
    )
    outside = [
        path for path in changed
        if path not in declared
        and not path.startswith("docs/sdlc/test-results/")
        and not path.startswith("docs/sdlc/baselines/")
        and path != "docs/sdlc/current.json"
        and not path.startswith(".sdlc-pipeline/state/")
        and not path.startswith(".sdlc-pipeline/work/")
        and not path.startswith(".sdlc-pipeline/evidence/")
    ]
    if outside:
        raise SdlcError(
            f"code gate 后只允许修改 Spec 声明的测试脚本: {outside}"
        )
    return {
        "ok": True,
        "declared": sorted(declared),
        "changed": changed,
    }


def run_test_plan(root: Path) -> dict[str, Any]:
    code_evidence = read_evidence_record(root, "code")
    if not code_evidence.get("ok"):
        raise SdlcError("code 阶段没有真实 compile/restart/verify 证据")
    spec_hashes = current_spec_hashes(root)
    if code_evidence.get("spec_hashes") != spec_hashes:
        raise SdlcError("code 证据与当前 spec 不匹配，必须重新 compile/restart/verify")
    if code_evidence.get("source_fingerprint") != implementation_fingerprint(root):
        raise SdlcError("code 证据生成后业务源码发生变化，必须重新执行 code gate")
    test_sources = _validate_test_sources(root, code_evidence)
    spec = load_current_spec(root)
    commands = load_contract(root)["tests"]
    started_at = utc_now()
    results = []
    executions: dict[tuple[str, str], dict[str, Any]] = {}
    for case in spec["test_plan"]["items"]:
        command_name = case["command"]
        if command_name not in commands:
            raise SdlcError(f"{case['id']} 引用未知 lifecycle test command: {command_name}")
        execution_key = (command_name, case["selector"])
        reused_from = None
        if execution_key in executions:
            result = executions[execution_key]["result"]
            reused_from = executions[execution_key]["test_id"]
        else:
            result = execute_command(
                root,
                f"test-{case['id']}",
                commands[command_name],
                selector=case["selector"],
            )
            executions[execution_key] = {
                "test_id": case["id"],
                "result": result,
            }
        status = "pass" if result["ok"] else "fail"
        test_result = {
            "id": case["id"],
            "mandatory": case["mandatory"],
            "status": status,
            "duration_ms": result["duration_ms"],
            "log": result["log"],
            "tail": result["tail"] if not result["ok"] else "",
        }
        if reused_from:
            test_result["reused_execution_from"] = reused_from
        results.append(test_result)
    policy = {
        "schema_version": "1.0",
        "phase": "test",
        "ok": True,
        "verifiers": [],
        "created_at": utc_now(),
    }
    write_evidence_record(
        root,
        "policy/test",
        policy,
        state="passed",
        title="Test policy evidence",
    )
    execution = {
        "schema_version": "1.0",
        "started_at": started_at,
        "finished_at": utc_now(),
        "policy": policy,
        "results": results,
        "binding": {
            "spec_hashes": spec_hashes,
            "lifecycle_sha256": sha256_file(contract_path(root)),
            "source_fingerprint": code_evidence["source_fingerprint"],
            "test_source_fingerprint": test_source_fingerprint(root),
        },
        "test_sources": test_sources,
    }
    write_evidence_record(
        root,
        "test-execution",
        execution,
        state="passed" if all(item["status"] == "pass" for item in results) else "failed",
        title="Test execution evidence",
    )
    return {"ok": policy["ok"] and all(item["status"] == "pass" for item in results), **execution}


def run_focused_checks(
    root: Path,
    selected: list[str] | None = None,
) -> dict[str, Any]:
    """Run coder-selected feature checks without executing the delivery lifecycle."""
    spec = load_current_spec(root)
    cases = {item["id"]: item for item in spec["test_plan"]["items"]}
    feature_ids = sorted(cases)
    requested = feature_ids if selected is None else selected
    if (
        not isinstance(requested, list)
        or not requested
        or any(not isinstance(item, str) or not item for item in requested)
    ):
        raise SdlcError("focused_check test_ids 必须是非空字符串数组")
    selected_ids = list(dict.fromkeys(requested))
    unknown = sorted(set(selected_ids) - set(feature_ids))
    if unknown:
        raise SdlcError(
            f"focused_check 只能选择当前已发布 Spec 的 T-id；"
            f"未知={unknown}，允许={feature_ids}"
        )
    commands = load_contract(root)["tests"]
    results = []
    executions: dict[tuple[str, str], dict[str, Any]] = {}
    for test_id in selected_ids:
        case = cases[test_id]
        selector = case["selector"]
        binding = {
            "test_id": test_id,
            "command": case["command"],
            "selector": selector,
            "selector_sha256": sha256_file(root / selector) if (root / selector).is_file() else None,
            "spec_hashes": current_spec_hashes(root),
            "source_fingerprint": worktree_fingerprint(root),
        }
        cached = read_work_record(root, f"focused/{test_id}", required=False)
        if cached and cached.get("binding") == binding:
            results.append({**cached["result"], "cached": True})
            continue
        execution_key = (case["command"], selector)
        reused_from = None
        if execution_key in executions:
            result = executions[execution_key]["result"]
            reused_from = executions[execution_key]["test_id"]
        else:
            result = execute_command(
                root,
                f"focused-{test_id}",
                commands[case["command"]],
                selector=selector,
            )
            executions[execution_key] = {
                "test_id": test_id,
                "result": result,
            }
        focused_result = {
            "test_id": test_id,
            "test_key": case["command"],
            "selector": selector,
            "status": "pass" if result["ok"] else "fail",
            "duration_ms": result["duration_ms"],
            "log": result["log"],
            "tail": "" if result["ok"] else result["tail"],
            "cached": False,
        }
        if reused_from:
            focused_result["reused_execution_from"] = reused_from
        write_work_record(root, f"focused/{test_id}", {
            "schema_version": "1.0",
            "binding": binding,
            "result": focused_result,
            "created_at": utc_now(),
        }, state=focused_result["status"], title=f"Focused check {test_id}")
        results.append({
            **focused_result,
        })
    evidence = {
        "schema_version": "1.0",
        "ok": all(item["status"] == "pass" for item in results),
        "selected": selected_ids,
        "available": feature_ids,
        "results": results,
        "binding": {
            "spec_hashes": current_spec_hashes(root),
            "source_fingerprint": worktree_fingerprint(root),
        },
        "created_at": utc_now(),
        "authoritative_delivery_evidence": False,
    }
    write_evidence_record(
        root,
        "focused-check",
        evidence,
        state="passed" if evidence["ok"] else "failed",
        title="Focused check evidence",
    )
    return evidence


def execute_tests(root: Path) -> dict[str, Any]:
    execution = read_evidence_record(root, "test-execution", required=False)
    if not execution:
        execution = run_test_plan(root)
    code_evidence = read_evidence_record(root, "code")
    expected_binding = {
        "spec_hashes": current_spec_hashes(root),
        "lifecycle_sha256": sha256_file(contract_path(root)),
        "source_fingerprint": code_evidence.get("source_fingerprint"),
        "test_source_fingerprint": test_source_fingerprint(root),
    }
    if execution.get("binding") != expected_binding:
        raise SdlcError(
            "测试执行证据与当前 test-plan、lifecycle 或源码不匹配，"
            "必须重新执行交付验证"
        )
    spec = load_current_spec(root)
    expected = {item["id"] for item in spec["test_plan"]["items"]}
    actual = {item["id"] for item in execution["results"]}
    if expected != actual:
        raise SdlcError("保存的测试执行与当前 test-plan 不匹配")
    results = execution["results"]
    mandatory_failed = [
        item["id"] for item in results
        if item["mandatory"] and item["status"] != "pass"
    ]
    version = next_version(root)
    output = {
        "schema_version": "1.0",
        "version": version,
        "status": "pass" if not mandatory_failed else "fail",
        "started_at": execution["started_at"],
        "finished_at": utc_now(),
        "results": results,
        "policy": execution.get("policy", {}),
        "mandatory_failed": mandatory_failed,
        "open_issues": [],
    }
    validate_schema_instance(root, "test-results.schema.json", output)
    test_results_ref = write_test_results(root, output)
    candidate = {
        "schema_version": "1.0",
        "version": version,
        "status": "ready" if output["status"] == "pass" else "failed",
        "test_results": test_results_ref,
        "created_at": utc_now(),
        "binding": expected_binding,
    }
    write_work_record(
        root,
        "version-candidate",
        candidate,
        state=candidate["status"],
        title=f"Version candidate {version}",
    )
    return output


def verify_delivery(root: Path) -> dict[str, Any]:
    """Run the single authoritative delivery verification for a fingerprint."""
    read_work_record(root, "tester-handoff")
    binding = {
        "source_fingerprint": implementation_fingerprint(root),
        "test_source_fingerprint": test_source_fingerprint(root),
        "spec_hashes": current_spec_hashes(root),
        "lifecycle_sha256": sha256_file(contract_path(root)),
    }
    cached = read_evidence_record(root, "delivery", required=False)
    if cached and cached.get("binding") == binding:
        result_path = root / cached.get("test_results", "")
        if result_path.is_file():
            return {**cached, "cached": True}

    code = read_evidence_record(root, "code")
    if not code.get("ok") or code.get("source_fingerprint") != binding["source_fingerprint"]:
        raise SdlcError("code evidence 缺失或已失效；请先重新执行 code gate")
    _validate_test_sources(root, code)
    started: dict[str, Any] = {}
    health: dict[str, Any] = {}
    execution: dict[str, Any] = {}
    results: dict[str, Any] = {}
    cleanup: dict[str, Any] = {"stopped": False}
    try:
        started = start(root)
        health = verify_health(root)
        if not health["ok"]:
            raise SdlcError("test 阶段 readiness 未通过")
        execution = run_test_plan(root)
        results = execute_tests(root)
    finally:
        cleanup = stop_active(root)
    evidence = {
        "ok": results["status"] == "pass",
        "cached": False,
        "binding": binding,
        "code": code,
        "start": started,
        "health": health,
        "execution": execution,
        "test_results": (
            f"docs/sdlc/test-results/{results['version']}/index.json"
        ),
        "version": results["version"],
        "cleanup": cleanup,
        "verified_at": utc_now(),
    }
    write_evidence_record(
        root,
        "delivery",
        evidence,
        state="passed" if evidence["ok"] else "failed",
        title="Delivery evidence",
    )
    return evidence
