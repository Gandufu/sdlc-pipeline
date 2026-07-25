from __future__ import annotations

import importlib.util
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .common import SdlcError, git, run_command


# The adapter may run from the repository during development or from
# <project>/.sdlc-pipeline after project-local installation.  In both layouts
# this file is exactly two directories below the distribution root.
def distribution_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if (root / "templates" / "manifest.json").exists():
        return root
    raise SdlcError("当前安装不包含 templates，无法执行 init")


def _copy_without_overwrite(
    source: Path, target: Path, *, skip_top_level: set[str] | None = None
) -> list[str]:
    copied: list[str] = []
    skipped = skip_top_level or set()
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        if relative.parts and relative.parts[0] in skipped:
            continue
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


def _ensure_bootstrap_workspace(root: Path) -> None:
    if not root.exists() or not root.is_dir():
        raise SdlcError("/sdlc-init 必须在已创建的项目目录中执行")
    allowed = {".opencode", ".sdlc-pipeline", "opencode.json"}
    unexpected = sorted(item.name for item in root.iterdir() if item.name not in allowed)
    if unexpected:
        raise SdlcError(
            "导入模板前项目目录必须为空（允许已安装的 SDLC 插件文件）；"
            f"发现: {', '.join(unexpected)}"
        )
    if (root / ".git").exists():
        raise SdlcError("导入模板前项目目录不能已有 Git 工作树")


def _load_installer(source_root: Path) -> Any:
    installer_path = source_root / "scripts" / "install_project.py"
    spec = importlib.util.spec_from_file_location("sdlc_installer", installer_path)
    if not spec or not spec.loader:
        raise SdlcError("无法加载 OpenCode 项目 installer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_adapter_if_needed(destination: Path, source_root: Path) -> None:
    marker = destination / ".sdlc-pipeline" / "installation.json"
    if not marker.exists():
        _load_installer(source_root).install(destination, force=False)


def _git_head(root: Path) -> str:
    return git(root, "rev-parse", "HEAD", check=False)


def _create_builtin_git_baseline(root: Path, template: str) -> str:
    if (root / ".git").exists():
        return _git_head(root)
    result = run_command(["git", "init"], cwd=root, timeout=60, check=False)
    if result.returncode:
        raise SdlcError(f"无法初始化 Git 仓库: {(result.stderr or result.stdout)[-4000:]}")
    result = run_command(["git", "add", "-A"], cwd=root, timeout=60, check=False)
    if result.returncode:
        raise SdlcError(f"无法建立模板基线: {(result.stderr or result.stdout)[-4000:]}")
    result = run_command(
        ["git", "commit", "-m", f"chore: initialize {template} template"],
        cwd=root,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise SdlcError(
            "无法建立 Git 基线；请先配置 user.name 和 user.email 后重新执行 init。\n"
            f"{(result.stderr or result.stdout)[-4000:]}"
        )
    return _git_head(root)


def _validate_github_template(source: Path) -> None:
    if (source / ".opencode").exists() or (source / "opencode.json").exists():
        raise SdlcError(
            "GitHub 模板不能携带 .opencode 或 opencode.json；这些由已安装的插件统一管理"
        )
    contract_root = source / ".sdlc-pipeline"
    required = {"lifecycle.json", "scaffold.json"}
    actual = {item.name for item in contract_root.iterdir()} if contract_root.is_dir() else set()
    if not required <= actual or actual - required:
        raise SdlcError(
            "GitHub 模板必须且只能在 .sdlc-pipeline 中提供 lifecycle.json 与 scaffold.json；"
            "runner、commands 和运行现场由插件安装"
        )


def _import_github_template(
    destination: Path, *, repo: str, ref: str
) -> tuple[list[str], str]:
    with tempfile.TemporaryDirectory(prefix="sdlc-template-") as temporary:
        checkout = Path(temporary) / "template"
        result = run_command(
            ["git", "clone", "--no-checkout", repo, str(checkout)],
            cwd=Path(temporary),
            timeout=600,
            check=False,
        )
        if result.returncode:
            raise SdlcError(f"GitHub 模板 clone 失败: {(result.stderr or result.stdout)[-4000:]}")
        result = run_command(
            ["git", "checkout", ref], cwd=checkout, timeout=120, check=False
        )
        if result.returncode:
            raise SdlcError(f"GitHub 模板 ref 无法 checkout: {(result.stderr or result.stdout)[-4000:]}")
        _validate_github_template(checkout)
        copied = _copy_without_overwrite(
            checkout, destination, skip_top_level={".git", ".sdlc-pipeline"}
        )
        (destination / ".sdlc-pipeline").mkdir(parents=True, exist_ok=True)
        for name in ("lifecycle.json", "scaffold.json"):
            shutil.copy2(checkout / ".sdlc-pipeline" / name, destination / ".sdlc-pipeline" / name)
            copied.append(f".sdlc-pipeline/{name}")
        shutil.copytree(checkout / ".git", destination / ".git")
        return copied, _git_head(destination)


def bootstrap(
    current_root: Path,
    *,
    template: str | None = None,
    github: str | None = None,
    ref: str | None = None,
) -> dict[str, Any]:
    """Fill the current empty project directory, then prove it can run.

    A built-in template is copied from the plugin distribution.  A GitHub
    template is cloned to a temporary directory and imported into this same
    project directory, including its Git metadata.  There is deliberately no
    target argument: the OpenCode worktree is always the evidence root.
    """
    destination = current_root.expanduser().resolve()
    _ensure_bootstrap_workspace(destination)
    if bool(template) == bool(github):
        raise SdlcError("init 必须二选一：提供内置 template，或提供 github 模板地址")
    source_root = distribution_root()
    if github:
        copied, baseline = _import_github_template(
            destination, repo=github, ref=ref or "HEAD"
        )
        source = {"kind": "github", "repo": github, "ref": ref or "HEAD"}
    else:
        template_root = source_root / "templates" / str(template)
        if not template_root.is_dir():
            raise SdlcError(f"未知内置模板: {template}")
        copied = _copy_without_overwrite(template_root, destination)
        _install_adapter_if_needed(destination, source_root)
        baseline = _create_builtin_git_baseline(destination, str(template))
        source = {"kind": "builtin", "template": template}
    _install_adapter_if_needed(destination, source_root)
    from .lifecycle import init_project

    report = init_project(destination)
    return {
        "ok": report.get("status") == "pass",
        "project_root": str(destination),
        "source": source,
        "git_baseline": baseline,
        "files_imported": copied,
        "report": report,
    }
