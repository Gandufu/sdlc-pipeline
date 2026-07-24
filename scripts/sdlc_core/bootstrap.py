from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .common import SdlcError, git, run_command


def distribution_root(current_root: Path) -> Path:
    if (current_root / "templates" / "manifest.json").exists():
        return current_root
    runtime = current_root / ".sdlc-pipeline"
    if (runtime / "templates" / "manifest.json").exists():
        return runtime
    raise SdlcError("当前安装不包含 templates，无法执行 bootstrap init")


def _empty_or_missing(path: Path) -> bool:
    return not path.exists() or (path.is_dir() and not any(path.iterdir()))


def _copy_without_overwrite(source: Path, target: Path) -> list[str]:
    copied = []
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        destination = target / relative
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)
        copied.append(relative.as_posix())
    return copied


def bootstrap(
    current_root: Path,
    *,
    repo: str,
    ref: str,
    target: str,
    template: str,
) -> dict[str, Any]:
    destination = Path(target).expanduser().resolve()
    if not _empty_or_missing(destination):
        raise SdlcError("init target 必须不存在或为空目录")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.rmdir()
    result = run_command(
        ["git", "clone", "--no-checkout", repo, str(destination)],
        cwd=destination.parent,
        timeout=600,
        check=False,
    )
    if result.returncode:
        raise SdlcError(f"git clone 失败: {(result.stderr or result.stdout)[-4000:]}")
    git(destination, "checkout", ref)
    source_root = distribution_root(current_root)
    template_root = source_root / "templates" / template
    if not template_root.is_dir():
        raise SdlcError(f"未知模板: {template}")
    copied = _copy_without_overwrite(template_root, destination)
    # Imported lazily to keep the deterministic core usable after project install.
    import importlib.util

    installer_path = source_root / "scripts" / "install_project.py"
    spec = importlib.util.spec_from_file_location("sdlc_installer", installer_path)
    if not spec or not spec.loader:
        raise SdlcError("无法加载 OpenCode 项目 installer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install(destination, force=False)
    from .lifecycle import init_project

    report = init_project(destination)
    return {
        "ok": report.get("status") == "pass",
        "target": str(destination),
        "repo": repo,
        "ref": ref,
        "template": template,
        "scaffold_files_copied": copied,
        "report": report,
    }
