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

from .artifacts import load_current_spec, render_test_results
from .common import (
    SdlcError,
    atomic_write,
    next_version,
    read_json,
    run_command,
    sha256_file,
    utc_now,
    write_json,
)
from .runs import pid_alive, read_active, record_active, retain_process, stop_active
from .trace import verify_scaffold, worktree_fingerprint


ALLOWED_VARIABLES = {"PROJECT_ROOT", "PYTHON", "PORT"}
MANDATORY_CONTRACT_FIELDS = {
    "schema_version", "project_type", "tools", "commands", "health",
    "artifacts", "tests",
}


def contract_path(root: Path) -> Path:
    return root / ".sdlc-pipeline" / "lifecycle.json"


def load_contract(root: Path) -> dict[str, Any]:
    value = read_json(contract_path(root))
    missing = sorted(MANDATORY_CONTRACT_FIELDS - set(value))
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
    path = root / ".sdlc-pipeline" / "runs" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def execute_command(root: Path, name: str, command: dict[str, Any]) -> dict[str, Any]:
    argv, cwd, timeout = resolve_command(root, command)
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
        "install_policy": "wrapper_corepack_existing_then_approved_system_install",
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
            elif kind in {"http", "browser"}:
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
    for pattern in contract["artifacts"]:
        matches = sorted(root.glob(pattern))
        for path in matches:
            if path.is_file():
                items.append({
                    "path": path.relative_to(root).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                })
    return {"ok": bool(items), "artifacts": items}


def compile_restart_verify(root: Path) -> dict[str, Any]:
    load_current_spec(root)
    read_json(root / ".sdlc-pipeline" / "runs" / "coder-handoff.json")
    drift = verify_scaffold(root)
    if not drift["ok"]:
        raise SdlcError(f"脚手架漂移，拒绝编译: {drift['drift']}")
    compile_result = run_phase(root, "compile")
    stopped = stop_active(root)
    started = start(root)
    health = verify_health(root)
    artifacts = artifact_evidence(root)
    if not health["ok"] or not artifacts["ok"]:
        raise SdlcError("重启后的 health 或 artifact 验证未通过")
    evidence = {
        "ok": True,
        "compiled_at": utc_now(),
        "compile": compile_result,
        "stop": stopped,
        "start": started,
        "health": health,
        "artifact_evidence": artifacts,
        "source_fingerprint": worktree_fingerprint(root),
    }
    write_json(root / ".sdlc-pipeline" / "runs" / "code-evidence.json", evidence)
    return evidence


def init_project(root: Path) -> dict[str, Any]:
    drift = verify_scaffold(root)
    if not drift["ok"]:
        raise SdlcError(f"脚手架初始校验失败: {drift['drift']}")
    tools = probe_tools(root)
    if not tools["ok"]:
        report = {
            "schema_version": "1.0",
            "status": "blocked",
            "created_at": utc_now(),
            "tools": tools,
            "approval_required": tools["missing"],
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
        "install": install,
        "compile": compile_result,
        "start": started,
        "health": health,
        "artifacts": artifacts,
        "stop": stopped,
        "keep_running_after_init": keep_running,
    }
    _write_init_report(root, report)
    if status != "pass":
        raise SdlcError("init 的 health/artifact 验收失败")
    return report


def _write_init_report(root: Path, report: dict[str, Any]) -> None:
    json_path = root / "docs" / "sdlc" / "init-report.json"
    write_json(json_path, report)
    lines = [
        "# SDLC Init 报告", "",
        f"- 状态：`{report['status']}`",
        f"- 时间：`{report['created_at']}`",
        f"- 缺失工具：{', '.join(report.get('tools', {}).get('missing', [])) or '无'}",
    ]
    for name in ("install", "compile", "start", "health", "artifacts", "stop"):
        if name in report:
            lines.append(f"- {name}：`{'pass' if report[name].get('ok') else 'fail'}`")
    atomic_write(root / "docs" / "sdlc" / "init-report.md", "\n".join(lines) + "\n")


def run_test_plan(root: Path) -> dict[str, Any]:
    code_evidence = read_json(root / ".sdlc-pipeline" / "runs" / "code-evidence.json")
    if not code_evidence.get("ok"):
        raise SdlcError("code 阶段没有真实 compile/restart/verify 证据")
    if code_evidence.get("source_fingerprint") != worktree_fingerprint(root):
        raise SdlcError("code 证据生成后工作树发生变化，必须重新 compile/restart/verify")
    spec = load_current_spec(root)
    commands = load_contract(root)["tests"]
    started_at = utc_now()
    results = []
    for case in spec["test_plan"]["items"]:
        command_name = case["command"]
        if command_name not in commands:
            raise SdlcError(f"{case['id']} 引用未知 lifecycle test command: {command_name}")
        result = execute_command(root, f"test-{case['id']}", commands[command_name])
        status = "pass" if result["ok"] else "fail"
        results.append({
            "id": case["id"],
            "mandatory": case["mandatory"],
            "status": status,
            "duration_ms": result["duration_ms"],
            "log": result["log"],
            "tail": result["tail"] if not result["ok"] else "",
        })
    execution = {
        "schema_version": "1.0",
        "started_at": started_at,
        "finished_at": utc_now(),
        "results": results,
    }
    write_json(root / ".sdlc-pipeline" / "runs" / "test-execution.json", execution)
    return {"ok": all(item["status"] == "pass" for item in results), **execution}


def execute_tests(root: Path, executor_result: dict[str, Any] | None = None) -> dict[str, Any]:
    execution = read_json(
        root / ".sdlc-pipeline" / "runs" / "test-execution.json",
        required=False,
    )
    if not execution:
        execution = run_test_plan(root)
    spec = load_current_spec(root)
    expected = {item["id"] for item in spec["test_plan"]["items"]}
    actual = {item["id"] for item in execution["results"]}
    if expected != actual:
        raise SdlcError("保存的测试执行与当前 test-plan 不匹配")
    if executor_result:
        reported = {item["id"]: item["status"] for item in executor_result.get("results", [])}
        measured = {item["id"]: item["status"] for item in execution["results"]}
        if reported != measured:
            raise SdlcError("executor handoff 与 runner 测试结果不一致")
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
        "executor": executor_result or {},
        "mandatory_failed": mandatory_failed,
        "open_issues": (executor_result or {}).get("open_issues", []),
    }
    directory = root / "docs" / "sdlc" / "test-results"
    write_json(directory / f"{version}.json", output)
    atomic_write(directory / f"{version}.md", render_test_results(output))
    candidate = {
        "schema_version": "1.0",
        "version": version,
        "status": "ready" if output["status"] == "pass" else "failed",
        "test_results": f"docs/sdlc/test-results/{version}.json",
        "created_at": utc_now(),
    }
    write_json(root / ".sdlc-pipeline" / "runs" / "version-candidate.json", candidate)
    return output
