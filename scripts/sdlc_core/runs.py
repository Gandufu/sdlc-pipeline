from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Any

from .common import SdlcError, run_native_capture, utc_now
from .layout import state_root
from .records import read_compact_index, write_compact_index


_OWNED_PROCESSES: dict[int, subprocess.Popen[Any]] = {}


def state_dir(root: Path) -> Path:
    return state_root(root)


def active_path(root: Path) -> Path:
    return state_dir(root) / "process.json"


def token_path(root: Path) -> Path:
    return state_dir(root) / "tokens.json"


def read_active(root: Path) -> dict[str, Any] | None:
    return read_compact_index(active_path(root), required=False)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.DWORD),
            ]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                exit_code = wintypes.DWORD()
                return bool(
                    kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                    and exit_code.value == 259
                )
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError, ValueError):
            return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def process_identity(pid: int) -> dict[str, Any] | None:
    """Return an OS creation marker that changes when a PID is reused."""
    if not pid_alive(pid):
        return None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class FILETIME(ctypes.Structure):
                _fields_ = [
                    ("dwLowDateTime", wintypes.DWORD),
                    ("dwHighDateTime", wintypes.DWORD),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetProcessTimes.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(FILETIME),
                ctypes.POINTER(FILETIME),
                ctypes.POINTER(FILETIME),
                ctypes.POINTER(FILETIME),
            ]
            kernel32.GetProcessTimes.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return None
            try:
                creation = FILETIME()
                exit_time = FILETIME()
                kernel_time = FILETIME()
                user_time = FILETIME()
                if not kernel32.GetProcessTimes(
                    handle,
                    ctypes.byref(creation),
                    ctypes.byref(exit_time),
                    ctypes.byref(kernel_time),
                    ctypes.byref(user_time),
                ):
                    return None
                marker = (
                    int(creation.dwHighDateTime) << 32
                ) | int(creation.dwLowDateTime)
                return {"scheme": "windows-filetime", "created": str(marker)}
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError, ValueError):
            return None
    proc_stat = Path(f"/proc/{pid}/stat")
    if proc_stat.is_file():
        try:
            text = proc_stat.read_text(encoding="utf-8")
            remainder = text[text.rfind(")") + 2:].split()
            return {"scheme": "proc-starttime", "created": remainder[19]}
        except (OSError, IndexError):
            return None
    try:
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    marker = result.stdout.strip()
    return {"scheme": "ps-lstart", "created": marker} if marker else None


def active_identity_matches(active: dict[str, Any] | None) -> bool:
    if not active:
        return False
    recorded = active.get("process_identity")
    current = process_identity(int(active.get("pid", 0)))
    return isinstance(recorded, dict) and recorded == current


def record_active(root: Path, value: dict[str, Any]) -> None:
    pid = int(value.get("pid", 0))
    identity = process_identity(pid)
    if identity is None:
        raise SdlcError(f"无法取得进程 {pid} 的创建身份，拒绝记录不安全 PID")
    write_compact_index(active_path(root), {
        **value, "process_identity": identity, "recorded_at": utc_now()
    })


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
    if not active_identity_matches(active):
        raise SdlcError(
            f"active PID {pid} 的创建身份不匹配，拒绝停止可能无关的进程"
        )
    try:
        if os.name == "nt":
            result = run_native_capture(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                timeout=timeout,
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
    reasoning_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    repeated_chars: int = 0,
    cost: float = 0,
    source: str = "opencode",
) -> dict[str, Any]:
    value = read_compact_index(token_path(root), required=False) or {
        "schema_version": "3.0",
        "phases": {},
    }
    item = value["phases"].setdefault(
        phase,
        {
            "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
            "reasoning": 0, "cost": 0, "repeated_chars": 0, "samples": 0,
        },
    )
    item.setdefault("reasoning", 0)
    item.setdefault("cost", 0)
    item["input"] += max(0, int(input_tokens))
    item["output"] += max(0, int(output_tokens))
    item["reasoning"] += max(0, int(reasoning_tokens))
    item["cache_read"] += max(0, int(cache_read_tokens))
    item["cache_write"] += max(0, int(cache_write_tokens))
    item["repeated_chars"] += max(0, int(repeated_chars))
    item["cost"] += max(0, float(cost))
    item["samples"] += 1
    item["source"] = source
    value["updated_at"] = utc_now()
    write_compact_index(token_path(root), value)
    return value


def token_summary(root: Path) -> dict[str, Any]:
    return read_compact_index(token_path(root), required=False) or {
        "schema_version": "3.0",
        "phases": {},
        "source": "unavailable",
    }
