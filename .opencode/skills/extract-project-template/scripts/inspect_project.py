#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


EXCLUDED = {
    ".git",
    ".idea",
    ".vite",
    ".vscode",
    "coverage",
    "dist",
    "node_modules",
    "out",
    "target",
}
MANIFEST_NAMES = {
    "package.json",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "pyproject.toml",
    "Cargo.toml",
}
LOCK_NAMES = {
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "poetry.lock",
    "Cargo.lock",
}
SECURITY_PATTERNS = {
    "context_isolation_enabled": "contextIsolation: true",
    "node_integration_disabled": "nodeIntegration: false",
    "sandbox_enabled": "sandbox: true",
    "content_security_policy": "Content-Security-Policy",
    "permission_request_handler": "setPermissionRequestHandler",
    "window_open_handler": "setWindowOpenHandler",
    "ipc_sender_validation": "senderFrame",
    "custom_protocol": "protocol.handle",
}


def relative_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED for part in relative.parts):
            continue
        files.append(relative)
    return sorted(files)


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def package_summary(root: Path, relative: Path) -> dict[str, Any]:
    package = load_json(root / relative) or {}
    return {
        "path": relative.as_posix(),
        "name": package.get("name"),
        "version": package.get("version"),
        "private": package.get("private"),
        "package_manager": package.get("packageManager"),
        "engines": package.get("engines", {}),
        "scripts": package.get("scripts", {}),
        "dependencies": package.get("dependencies", {}),
        "dev_dependencies": package.get("devDependencies", {}),
    }


def git_summary(root: Path) -> dict[str, Any]:
    if not (root / ".git").exists():
        return {"present": False}

    def run(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return result.stdout.strip()

    return {
        "present": True,
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "remotes": run("remote", "-v").splitlines(),
        "status": run("status", "--short").splitlines(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成只读项目模板提炼清单")
    parser.add_argument("--root", required=True, help="待分析项目根目录")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        parser.error(f"项目目录不存在: {root}")

    files = relative_files(root)
    packages = [
        package_summary(root, path)
        for path in files
        if path.name == "package.json"
    ]
    text_files: list[str] = []
    for relative in files:
        path = root / relative
        if path.suffix.lower() not in {".ts", ".tsx", ".js", ".jsx", ".html"}:
            continue
        try:
            text_files.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    source_text = "\n".join(text_files)
    result = {
        "root": str(root),
        "git": git_summary(root),
        "files": {
            "count": len(files),
            "manifests": [
                path.as_posix() for path in files if path.name in MANIFEST_NAMES
            ],
            "locks": [
                path.as_posix() for path in files if path.name in LOCK_NAMES
            ],
            "tests": [
                path.as_posix()
                for path in files
                if ".test." in path.name or ".spec." in path.name
            ],
            "documentation": [
                path.as_posix()
                for path in files
                if path.suffix.lower() == ".md"
            ],
        },
        "packages": packages,
        "security_signals": {
            name: pattern in source_text
            for name, pattern in SECURITY_PATTERNS.items()
        },
        "sdlc_contracts": {
            "lifecycle": (root / ".sdlc-pipeline" / "lifecycle.json").is_file(),
            "scaffold": (root / ".sdlc-pipeline" / "scaffold.json").is_file(),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
