from __future__ import annotations

import importlib.util
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .common import SdlcError, git, read_json, run_command
from .layout import contracts_root


# The adapter may run from the repository during development or from
# <project>/.sdlc-pipeline/runtime after project-local installation. In both layouts
# this file is exactly two directories below the distribution root.
def distribution_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if (root / "templates" / "manifest.json").exists():
        return root
    raise SdlcError("当前安装不包含模板数据源注册表，无法执行 init")


def template_registry(root: Path | None = None) -> list[dict[str, Any]]:
    registry_path = (root or distribution_root()) / "templates" / "manifest.json"
    registry = read_json(registry_path)
    if not isinstance(registry, dict) or registry.get("schema_version") != "1.0":
        raise SdlcError("模板数据源注册表格式无效")
    templates = registry.get("templates")
    if not isinstance(templates, list):
        raise SdlcError("模板数据源注册表缺少 templates 数组")
    ids: set[str] = set()
    for item in templates:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise SdlcError("模板数据源条目缺少 id")
        required_text = ("name", "description")
        if any(
            not isinstance(item.get(field), str) or not item[field].strip()
            for field in required_text
        ):
            raise SdlcError(f"模板 {item['id']} 缺少 name/description")
        for field in ("stacks", "rules", "capabilities"):
            values = item.get(field)
            if (
                not isinstance(values, list)
                or not values
                or any(not isinstance(value, str) or not value for value in values)
            ):
                raise SdlcError(f"模板 {item['id']} 的 {field} 必须是非空字符串数组")
        if item["id"] in ids:
            raise SdlcError(f"模板数据源 ID 重复: {item['id']}")
        ids.add(item["id"])
        source = item.get("source")
        if not isinstance(source, dict) or source.get("kind") != "git":
            raise SdlcError(f"模板 {item['id']} 的 source 必须是 git")
        if not source.get("repository") or not source.get("ref"):
            raise SdlcError(f"模板 {item['id']} 的 source 缺少 repository/ref")
    return templates


def resolve_template_source(template_id: str) -> dict[str, Any]:
    templates = template_registry()
    template = next(
        (item for item in templates if item["id"] == template_id),
        None,
    )
    if template is None:
        available = ", ".join(item["id"] for item in templates) or "无"
        raise SdlcError(f"未知模板数据源: {template_id}；可用: {available}")
    return template


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


def _resume_registered_template(
    destination: Path, template: str
) -> dict[str, Any] | None:
    contract_root = contracts_root(destination)
    if not all(
        (contract_root / name).is_file()
        for name in ("lifecycle.json", "scaffold.json")
    ):
        return None
    from .trace import verify_scaffold

    verification = verify_scaffold(destination)
    installed_template = verification["contract"]["template_id"]
    if installed_template != template:
        raise SdlcError(
            f"当前目录已初始化为模板 {installed_template}，不能改用 {template}"
        )
    if not verification["ok"]:
        raise SdlcError(
            "模板已复制但 scaffold 存在真实漂移，拒绝覆盖；"
            f"详情: {verification['issues']}"
        )
    source_root = distribution_root()
    _install_adapter_if_needed(destination, source_root)
    if not (destination / ".git").exists():
        raise SdlcError("模板合约已存在但缺少远程模板 Git 历史，无法安全续跑")
    baseline = _git_head(destination)
    metadata = resolve_template_source(template)
    remote = metadata["source"]
    from .lifecycle import init_project

    report = init_project(destination, auto_install_missing=True)
    return {
        "ok": report.get("status") == "pass",
        "project_root": str(destination),
        "source": {
            "kind": "registry",
            "template": template,
            "repository": remote["repository"],
            "ref": remote["ref"],
            "commit": baseline,
        },
        "git_baseline": baseline,
        "files_imported": [],
        "resumed": True,
        "report": report,
    }


def _validate_github_template(source: Path) -> None:
    if (source / ".opencode").exists() or (source / "opencode.json").exists():
        raise SdlcError(
            "GitHub 模板不能携带 .opencode 或 opencode.json；这些由已安装的插件统一管理"
        )
    contract_root = source / ".sdlc-pipeline" / "contracts"
    required = {"lifecycle.json", "scaffold.json"}
    actual = {item.name for item in contract_root.iterdir()} if contract_root.is_dir() else set()
    pipeline_root = source / ".sdlc-pipeline"
    pipeline_entries = (
        {item.name for item in pipeline_root.iterdir()}
        if pipeline_root.is_dir()
        else set()
    )
    if (
        pipeline_entries != {"contracts"}
        or not required <= actual
        or actual - required
    ):
        raise SdlcError(
            "GitHub 模板必须且只能在 .sdlc-pipeline/contracts 中提供 "
            "lifecycle.json 与 scaffold.json；"
            "runner、commands 和运行现场由插件安装"
        )


def _import_github_template(
    destination: Path, *, repo: str, ref: str
) -> tuple[list[str], str]:
    with tempfile.TemporaryDirectory(prefix="sdlc-template-") as temporary:
        checkout = Path(temporary) / "template"
        result = run_command(
            [
                "git", "-c", "core.autocrlf=false",
                "clone", "--no-checkout", repo, str(checkout),
            ],
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
        contracts_root(destination).mkdir(parents=True, exist_ok=True)
        for name in ("lifecycle.json", "scaffold.json"):
            shutil.copy2(
                checkout / ".sdlc-pipeline" / "contracts" / name,
                contracts_root(destination) / name,
            )
            copied.append(f".sdlc-pipeline/contracts/{name}")
        shutil.copytree(checkout / ".git", destination / ".git")
        return copied, _git_head(destination)


def bootstrap(
    current_root: Path,
    *,
    template: str | None = None,
    github: str | None = None,
    ref: str | None = None,
) -> dict[str, Any]:
    """Import a registered or ad-hoc Git template, then prove it can run.

    The plugin distribution contains metadata only.  Both a registered
    template ID and an explicit Git URL resolve to the same remote import path.
    There is deliberately no target argument: the OpenCode worktree is always
    the evidence root.
    """
    destination = current_root.expanduser().resolve()
    if template and not github:
        resumed = _resume_registered_template(destination, template)
        if resumed is not None:
            return resumed
    _ensure_bootstrap_workspace(destination)
    if bool(template) == bool(github):
        raise SdlcError("init 必须二选一：提供模板数据源 ID，或提供 github 模板地址")
    source_root = distribution_root()
    if github:
        resolved_ref = ref or "HEAD"
        copied, baseline = _import_github_template(
            destination, repo=github, ref=resolved_ref
        )
        source = {
            "kind": "github",
            "repository": github,
            "ref": resolved_ref,
            "commit": baseline,
        }
    else:
        metadata = resolve_template_source(str(template))
        remote = metadata["source"]
        copied, baseline = _import_github_template(
            destination,
            repo=str(remote["repository"]),
            ref=str(remote["ref"]),
        )
        source = {
            "kind": "registry",
            "template": template,
            "repository": remote["repository"],
            "ref": remote["ref"],
            "commit": baseline,
        }
    _install_adapter_if_needed(destination, source_root)
    from .lifecycle import init_project

    report = init_project(destination, auto_install_missing=True)
    return {
        "ok": report.get("status") == "pass",
        "project_root": str(destination),
        "source": source,
        "git_baseline": baseline,
        "files_imported": copied,
        "report": report,
    }
