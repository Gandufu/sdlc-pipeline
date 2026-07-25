"""Install the OpenCode-only SDLC Pipeline adapter into a project."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
VERSION = "0.6.0"
MANAGED = (
    ("scripts", ".sdlc-pipeline/scripts"),
    ("templates", ".sdlc-pipeline/templates"),
    ("rules", ".sdlc-pipeline/rules"),
    ("references", ".sdlc-pipeline/references"),
    ("schemas", ".sdlc-pipeline/schemas"),
    (".opencode", ".sdlc-pipeline/opencode"),
    (".opencode/plugins/sdlc-pipeline.js", ".opencode/plugins/sdlc-pipeline.js"),
    (".opencode/agents/sdlc-main.md", ".opencode/agents/sdlc-main.md"),
    (".opencode/agents/sdlc-coder.md", ".opencode/agents/sdlc-coder.md"),
    (".opencode/agents/sdlc-executor.md", ".opencode/agents/sdlc-executor.md"),
    (".opencode/commands/sdlc-init.md", ".opencode/commands/sdlc-init.md"),
    (".opencode/commands/sdlc-spec.md", ".opencode/commands/sdlc-spec.md"),
    (".opencode/commands/sdlc-code.md", ".opencode/commands/sdlc-code.md"),
    (".opencode/commands/sdlc-test.md", ".opencode/commands/sdlc-test.md"),
    (".opencode/skills/sdlc-pipeline/SKILL.md", ".opencode/skills/sdlc-pipeline/SKILL.md"),
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
            if item.is_dir() or "__pycache__" in item.parts or item.suffix == ".pyc":
                continue
            relative = item.relative_to(source)
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


def _source(name: str) -> Path:
    direct = PLUGIN_ROOT / name
    if direct.exists():
        return direct
    if name == ".opencode":
        return PLUGIN_ROOT / "opencode"
    if name.startswith(".opencode/"):
        return PLUGIN_ROOT / "opencode" / name.removeprefix(".opencode/")
    return direct


def install(target: Path, force: bool = False) -> dict[str, object]:
    target = target.expanduser().resolve()
    if not target.is_dir():
        raise ValueError(f"目标项目不存在或不是目录: {target}")
    marker = target / ".sdlc-pipeline" / "installation.json"
    if marker.exists() and not force:
        raise ValueError("项目已安装；升级请使用 --force")
    for source_name, destination_name in MANAGED:
        _copy(_source(source_name), target / destination_name, force)
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
        "desktop_compatible": True,
    }
    atomic_write(marker, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    atomic_write(
        target / ".sdlc-pipeline" / ".gitignore",
        "runs/\n**/__pycache__/\n*.py[cod]\n",
    )
    return {"ok": True, "target": str(target), **value}


def main() -> int:
    parser = argparse.ArgumentParser(description="安装 OpenCode 项目级 SDLC Pipeline")
    parser.add_argument("--target", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(json.dumps(install(Path(args.target), args.force), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
