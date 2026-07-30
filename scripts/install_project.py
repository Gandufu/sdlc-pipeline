"""Install the OpenCode-only SDLC Pipeline adapter into a project."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


_SOURCE_FILE = globals().get("__file__")
PLUGIN_ROOT = (
    Path(_SOURCE_FILE).resolve().parent.parent
    if _SOURCE_FILE and not str(_SOURCE_FILE).startswith("<")
    else Path.cwd().resolve()
)
VERSION = "0.24.2"
DEFAULT_REPOSITORY = "https://github.com/Gandufu/sdlc-pipeline.git"
DEFAULT_REF = "main"
OPENCODE_PLUGIN_VERSION = "^1.18.7"
COPY_EXCLUDED_PARTS = {"node_modules", "__pycache__", ".cache"}
MANAGED = (
    ("scripts", ".sdlc-pipeline/runtime/scripts"),
    ("templates", ".sdlc-pipeline/runtime/templates"),
    ("rules", ".sdlc-pipeline/runtime/rules"),
    ("references", ".sdlc-pipeline/runtime/references"),
    ("schemas", ".sdlc-pipeline/runtime/schemas"),
    (".opencode/plugins/sdlc-pipeline.js", ".opencode/plugins/sdlc-pipeline.js"),
    (".opencode/agents/sdlc-main.md", ".opencode/agents/sdlc-main.md"),
    (".opencode/agents/sdlc-coder.md", ".opencode/agents/sdlc-coder.md"),
    (".opencode/agents/sdlc-tester.md", ".opencode/agents/sdlc-tester.md"),
    (".opencode/commands/sdlc-init.md", ".opencode/commands/sdlc-init.md"),
    (".opencode/commands/sdlc-spec.md", ".opencode/commands/sdlc-spec.md"),
    (".opencode/commands/sdlc-code.md", ".opencode/commands/sdlc-code.md"),
    (".opencode/commands/sdlc-test.md", ".opencode/commands/sdlc-test.md"),
    (".opencode/skills/sdlc-pipeline/SKILL.md", ".opencode/skills/sdlc-pipeline/SKILL.md"),
    (
        ".opencode/skills/extract-project-template",
        ".opencode/skills/extract-project-template",
    ),
)
OBSOLETE_MANAGED = (
    ".opencode/agents/sdlc-executor.md",
    ".sdlc-pipeline/opencode",
    ".sdlc-pipeline/scripts",
    ".sdlc-pipeline/templates",
    ".sdlc-pipeline/rules",
    ".sdlc-pipeline/references",
    ".sdlc-pipeline/schemas",
    ".sdlc-pipeline/runs",
    ".sdlc-pipeline/lifecycle.json",
    ".sdlc-pipeline/scaffold.json",
    ".sdlc-pipeline/runtime/schemas/feature-contract.schema.json",
    ".sdlc-pipeline/runtime/schemas/spec.schema.json",
    ".sdlc-pipeline/runtime/schemas/source-envelope.schema.json",
    ".sdlc-pipeline/runtime/schemas/interactions/spec-checkpoint.schema.json",
    ".sdlc-pipeline/runtime/schemas/v2",
    ".sdlc-pipeline/runtime/scripts/sdlc_core/feature_contracts.py",
)


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


def _copy(source: Path, destination: Path, force: bool) -> None:
    if source.is_dir():
        for item in source.rglob("*"):
            relative = item.relative_to(source)
            if (
                item.is_dir()
                or any(part in COPY_EXCLUDED_PARTS for part in relative.parts)
                or item.suffix == ".pyc"
            ):
                continue
            target = destination / relative
            if target.exists() and not force:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
    else:
        if destination.exists() and not force:
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _ensure_opencode_dependencies(target: Path) -> None:
    package_path = target / ".opencode" / "package.json"
    package: dict[str, Any] = {}
    if package_path.exists():
        value = json.loads(package_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"OpenCode package 配置必须是 JSON object: {package_path}")
        package = value
    dependencies = package.setdefault("dependencies", {})
    if not isinstance(dependencies, dict):
        raise ValueError(
            f"OpenCode package dependencies 必须是 JSON object: {package_path}"
        )
    package.setdefault("private", True)
    package.setdefault("type", "module")
    dependencies.setdefault("@opencode-ai/plugin", OPENCODE_PLUGIN_VERSION)
    atomic_write(
        package_path,
        json.dumps(package, ensure_ascii=False, indent=2) + "\n",
    )


def _ensure_tooling_ignores(target: Path) -> dict[str, object]:
    runtime_scripts = target / ".sdlc-pipeline" / "runtime" / "scripts"
    runtime_text = str(runtime_scripts)
    if runtime_text not in sys.path:
        sys.path.insert(0, runtime_text)
    from sdlc_core.tooling import ensure_tooling_ignores

    return ensure_tooling_ignores(target)


def _contract_self_check(target: Path) -> dict[str, object]:
    runtime_scripts = target / ".sdlc-pipeline" / "runtime" / "scripts"
    runtime_text = str(runtime_scripts)
    if runtime_text not in sys.path:
        sys.path.insert(0, runtime_text)
    from sdlc_core.schema_validation import (
        check_schema_documents,
        validate_schema_instance,
    )

    checked: list[str] = [
        f".sdlc-pipeline/runtime/schemas/{name}"
        for name in check_schema_documents(target)
    ]
    for path in sorted(
        (target / ".sdlc-pipeline" / "runtime" / "rules").glob("*.policy.json")
    ):
        validate_schema_instance(target, "rule-policy.schema.json", json.loads(
            path.read_text(encoding="utf-8")
        ))
        checked.append(path.relative_to(target).as_posix())
    manifest = (
        target / ".sdlc-pipeline" / "runtime" / "templates" / "manifest.json"
    )
    if manifest.is_file():
        validate_schema_instance(
            target,
            "template-registry.schema.json",
            json.loads(manifest.read_text(encoding="utf-8")),
        )
        checked.append(manifest.relative_to(target).as_posix())
    return {"ok": True, "checked": checked}


def _refresh_active_rules(target: Path) -> dict[str, object] | None:
    contracts = target / ".sdlc-pipeline" / "contracts"
    if not all(
        (contracts / name).is_file()
        for name in ("lifecycle.json", "scaffold.json")
    ):
        return None
    runtime_scripts = target / ".sdlc-pipeline" / "runtime" / "scripts"
    runtime_text = str(runtime_scripts)
    if runtime_text not in sys.path:
        sys.path.insert(0, runtime_text)
    from sdlc_core.lifecycle import activate_template_rules

    return activate_template_rules(target)


def _source(name: str) -> Path:
    direct = PLUGIN_ROOT / name
    if direct.exists():
        return direct
    if (
        PLUGIN_ROOT.name == "runtime"
        and PLUGIN_ROOT.parent.name == ".sdlc-pipeline"
    ):
        project_root = PLUGIN_ROOT.parent.parent
        installed = project_root / name
        if installed.exists():
            return installed
    if name == ".opencode":
        return PLUGIN_ROOT / "opencode"
    if name.startswith(".opencode/"):
        return PLUGIN_ROOT / "opencode" / name.removeprefix(".opencode/")
    return direct


def is_distribution(root: Path) -> bool:
    """Return whether root contains the complete installable distribution."""
    return (
        (root / "scripts" / "sdlc.py").is_file()
        and (root / "templates" / "manifest.json").is_file()
        and (root / ".opencode" / "plugins" / "sdlc-pipeline.js").is_file()
    )


def _clone_distribution(repository: str, ref: str, parent: Path) -> Path:
    destination = parent / "sdlc-pipeline"
    try:
        clone = subprocess.run(
            [
                "git", "-c", "core.autocrlf=false",
                "clone", "--no-checkout", repository, str(destination),
            ],
            cwd=parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise RuntimeError("无法运行 Git；请安装 Git 后重试 installer") from exc
    if clone.returncode:
        raise RuntimeError(
            f"无法从 {repository} 拉取 SDLC Pipeline："
            f"{(clone.stderr or clone.stdout)[-4000:]}"
        )
    checkout = subprocess.run(
        ["git", "checkout", ref],
        cwd=destination,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if checkout.returncode:
        raise RuntimeError(
            f"无法 checkout SDLC Pipeline ref {ref}："
            f"{(checkout.stderr or checkout.stdout)[-4000:]}"
        )
    if not is_distribution(destination):
        raise RuntimeError("下载内容不是完整的 SDLC Pipeline 发行包")
    return destination


def _load_installer(source_root: Path) -> Any:
    path = source_root / "scripts" / "install_project.py"
    spec = importlib.util.spec_from_file_location("sdlc_remote_installer", path)
    if not spec or not spec.loader:
        raise RuntimeError("无法加载下载的 SDLC Pipeline installer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_from_repository(
    target: Path, force: bool, repository: str, ref: str
) -> dict[str, object]:
    """Install from a raw-script invocation without requiring a local clone."""
    with tempfile.TemporaryDirectory(prefix="sdlc-pipeline-") as temporary:
        source_root = _clone_distribution(repository, ref, Path(temporary))
        result = _load_installer(source_root).install(target, force)
    result["plugin_dependencies"] = prepare_opencode_plugin_dependencies(
        target.expanduser().resolve()
    )
    return result


def install(target: Path, force: bool = False) -> dict[str, object]:
    target = target.expanduser().resolve()
    if not target.is_dir():
        raise ValueError(f"目标项目不存在或不是目录: {target}")
    marker = target / ".sdlc-pipeline" / "installation.json"
    if marker.exists() and not force:
        raise ValueError("项目已安装；升级请使用 --force")
    for source_name, destination_name in MANAGED:
        _copy(_source(source_name), target / destination_name, force)
    if force:
        for obsolete_name in OBSOLETE_MANAGED:
            obsolete = target / obsolete_name
            if obsolete.is_file():
                obsolete.unlink()
            elif obsolete.is_dir():
                shutil.rmtree(obsolete)
    contract_self_check = _contract_self_check(target)
    active_rules = _refresh_active_rules(target)
    _ensure_opencode_dependencies(target)
    config_path = target / "opencode.json"
    config = {}
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    config.setdefault("$schema", "https://opencode.ai/config.json")
    config.setdefault("default_agent", "sdlc-main")
    atomic_write(config_path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    value = {
        "name": "sdlc-pipeline",
        "version": VERSION,
        "host": "opencode",
        "layout": "project-local",
        "layout_version": "4.0",
        "desktop_compatible": True,
    }
    atomic_write(
        target / ".sdlc-pipeline" / ".gitignore",
        "state/\nwork/\nevidence/\n**/__pycache__/\n*.py[cod]\n",
    )
    tooling_ignore = _ensure_tooling_ignores(target)
    atomic_write(marker, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return {
        "ok": True,
        "target": str(target),
        **value,
        "contract_self_check": contract_self_check,
        "active_rules": active_rules,
        "tooling_ignore": tooling_ignore,
    }


def prepare_opencode_plugin_dependencies(target: Path) -> dict[str, str]:
    """Install the SDK needed before OpenCode can load the project plugin."""
    package_root = target / ".opencode"
    managers = (
        (
            "npm",
            [
                "install",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                "--package-lock=false",
            ],
        ),
        ("bun", ["install", "--ignore-scripts"]),
    )
    selected: tuple[str, str, list[str]] | None = None
    for name, args in managers:
        executable = shutil.which(name)
        if executable:
            selected = (name, executable, args)
            break
    if not selected:
        raise RuntimeError(
            "无法准备 OpenCode 插件依赖：系统中未找到 npm 或 bun。"
            "安装器必须先完成插件 SDK bootstrap，之后 /sdlc-init 才能自动探测模板环境。"
        )
    name, executable, args = selected
    result = subprocess.run(
        [executable, *args],
        cwd=package_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        details = (result.stderr or result.stdout)[-4000:]
        raise RuntimeError(
            f"OpenCode 插件依赖安装失败（{name}）: {details}"
        )
    installed = (
        package_root
        / "node_modules"
        / "@opencode-ai"
        / "plugin"
        / "package.json"
    )
    if not installed.is_file():
        raise RuntimeError(
            f"OpenCode 插件依赖安装未生成预期文件: {installed}"
        )
    metadata = json.loads(installed.read_text(encoding="utf-8"))
    return {
        "manager": name,
        "package": "@opencode-ai/plugin",
        "version": str(metadata.get("version", "unknown")),
    }


def install_complete(target: Path, force: bool = False) -> dict[str, object]:
    """Install project files and make the plugin loadable in one operation."""
    result = install(target, force)
    resolved = target.expanduser().resolve()
    result["plugin_dependencies"] = prepare_opencode_plugin_dependencies(resolved)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="安装 OpenCode 项目级 SDLC Pipeline")
    parser.add_argument("--target", required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--ref", default=DEFAULT_REF)
    args = parser.parse_args()
    if is_distribution(PLUGIN_ROOT):
        result = install_complete(Path(args.target), args.force)
    else:
        result = install_from_repository(
            Path(args.target), args.force, args.repository, args.ref
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
