from __future__ import annotations

from pathlib import Path


LAYOUT_VERSION = "3.0"


def pipeline_root(root: Path) -> Path:
    return root / ".sdlc-pipeline"


def runtime_root(root: Path) -> Path:
    return pipeline_root(root) / "runtime"


def contracts_root(root: Path) -> Path:
    return pipeline_root(root) / "contracts"


def state_root(root: Path) -> Path:
    return pipeline_root(root) / "state"


def work_root(root: Path) -> Path:
    return pipeline_root(root) / "work"


def evidence_root(root: Path) -> Path:
    return pipeline_root(root) / "evidence"


def lifecycle_path(root: Path) -> Path:
    return contracts_root(root) / "lifecycle.json"


def scaffold_path(root: Path) -> Path:
    return contracts_root(root) / "scaffold.json"


def rules_root(root: Path) -> Path:
    return runtime_root(root) / "rules"


def references_root(root: Path) -> Path:
    return runtime_root(root) / "references"


def schemas_root(root: Path) -> Path:
    return runtime_root(root) / "schemas"


def templates_root(root: Path) -> Path:
    return runtime_root(root) / "templates"


def scripts_root(root: Path) -> Path:
    return runtime_root(root) / "scripts"


def relative_to_project(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
