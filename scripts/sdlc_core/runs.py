from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Any

from .common import SdlcError, read_json, utc_now, write_json


_OWNED_PROCESSES: dict[int, subprocess.Popen[Any]] = {}


def state_dir(root: Path) -> Path:
    return root / ".sdlc-pipeline" / "runs"


def active_path(root: Path) -> Path:
    return state_dir(root) / "active.json"


def token_path(root: Path) -> Path:
    return state_dir(root) / "tokens.json"


def read_active(root: Path) -> dict[str, Any] | None:
    return read_json(active_path(root), required=False)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def record_active(root: Path, value: dict[str, Any]) -> None:
    write_json(active_path(root), {**value, "recorded_at": utc_now()})


def retain_process(process: subprocess.Popen[Any]) -> None:
    """Keep a background Popen alive until the runner stops and reaps it."""
    _OWNED_PROCESSES[process.pid] = process


def clear_active(root: Path) -> None:
    path = active_path(root)
    if path.exists():
        path.unlink()


def stop_active(root: Path, timeout: int = 15) -> dict[str, Any]:
    active = read_active(root)
    if not active:
        return {"ok": True, "stopped": False, "reason": "no_active_process"}
    pid = int(active.get("pid", 0))
    if not pid_alive(pid):
        clear_active(root)
        return {"ok": True, "stopped": False, "reason": "stale_pid", "pid": pid}
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
            if result.returncode and pid_alive(pid):
                raise SdlcError(result.stderr.strip() or f"taskkill failed: {pid}")
        else:
            os.killpg(pid, signal.SIGTERM)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SdlcError(f"停止进程 {pid} 失败: {exc}") from exc
    process = _OWNED_PROCESSES.pop(pid, None)
    if process is not None:
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout)
    clear_active(root)
    return {"ok": True, "stopped": True, "pid": pid}


def record_tokens(
    root: Path,
    phase: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    repeated_chars: int = 0,
    source: str = "opencode",
) -> dict[str, Any]:
    value = read_json(token_path(root), required=False) or {
        "schema_version": "1.0",
        "phases": {},
    }
    item = value["phases"].setdefault(
        phase,
        {
            "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
            "repeated_chars": 0, "samples": 0,
        },
    )
    item["input"] += max(0, int(input_tokens))
    item["output"] += max(0, int(output_tokens))
    item["cache_read"] += max(0, int(cache_read_tokens))
    item["cache_write"] += max(0, int(cache_write_tokens))
    item["repeated_chars"] += max(0, int(repeated_chars))
    item["samples"] += 1
    item["source"] = source
    value["updated_at"] = utc_now()
    write_json(token_path(root), value)
    return value


def token_summary(root: Path) -> dict[str, Any]:
    return read_json(token_path(root), required=False) or {
        "schema_version": "1.0",
        "phases": {},
        "source": "unavailable",
    }
