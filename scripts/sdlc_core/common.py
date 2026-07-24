from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ID_PATTERNS = {
    "requirement": re.compile(r"^R-\d{4}$"),
    "design": re.compile(r"^D-\d{4}$"),
    "test": re.compile(r"^T-\d{4}$"),
}


class SdlcError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def project_root(start: str | Path | None = None) -> Path:
    path = Path(start or os.getcwd()).resolve()
    for candidate in (path, *path.parents):
        if (candidate / ".sdlc-pipeline").exists() or (candidate / ".git").exists():
            return candidate
    return path


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, *, required: bool = True) -> Any:
    if not path.exists():
        if required:
            raise SdlcError(f"缺少文件: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SdlcError(f"无法读取 JSON {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def run_command(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int = 30,
    check: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if not argv or not all(isinstance(item, str) and item for item in argv):
        raise SdlcError("命令必须是非空 argv 数组")
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            timeout=timeout,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            env=env,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SdlcError(f"命令执行失败 {argv!r}: {exc}") from exc
    if check and result.returncode:
        tail = (result.stderr or result.stdout)[-4000:]
        raise SdlcError(f"命令返回 {result.returncode}: {argv!r}\n{tail}")
    return result


def git(root: Path, *args: str, check: bool = True) -> str:
    return run_command(["git", *args], cwd=root, timeout=60, check=check).stdout.strip()


def git_available(root: Path) -> bool:
    result = run_command(
        ["git", "rev-parse", "--is-inside-work-tree"], cwd=root, check=False
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def next_version(root: Path) -> str:
    versions = root / "docs" / "sdlc" / "versions"
    numbers = []
    if versions.exists():
        for child in versions.iterdir():
            match = re.fullmatch(r"V(\d{4})", child.name)
            if match:
                numbers.append(int(match.group(1)))
    return f"V{max(numbers, default=0) + 1:04d}"


def require_fields(value: dict[str, Any], fields: tuple[str, ...], context: str) -> None:
    missing = [field for field in fields if value.get(field) in (None, "", [])]
    if missing:
        raise SdlcError(f"{context} 缺少必填字段: {', '.join(missing)}")
