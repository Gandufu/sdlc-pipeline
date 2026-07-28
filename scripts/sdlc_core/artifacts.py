from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_store import current_bundle, materialize_bundle
from .common import SdlcError, read_json, sha256_json
from .schema_validation import validate_schema_instance
from .sources import load_source


def lifecycle_test_commands(root: Path) -> dict[str, dict[str, Any]]:
    contract = read_json(root / ".sdlc-pipeline" / "lifecycle.json")
    tests = contract.get("tests")
    if not isinstance(tests, dict):
        raise SdlcError("lifecycle.json tests 必须是对象")
    return {
        name: command
        for name, command in tests.items()
        if isinstance(name, str) and isinstance(command, dict)
    }


def current_spec_hashes(root: Path) -> dict[str, str]:
    bundle, manifest = _v2_bundle(root)
    files = manifest["files"]

    def group(prefix: str) -> str:
        return sha256_json({
            name: evidence["sha256"]
            for name, evidence in sorted(files.items())
            if name.startswith(prefix)
        })

    return {
        "feature_map": files["feature-map.json"]["sha256"],
        "requirements": group("requirements/"),
        "designs": group("designs/"),
        "verification": group("verification/"),
    }


def unresolved_blocking_questions(spec: dict[str, Any]) -> list[dict[str, Any]]:
    # A v2 baseline can only be published after candidate validation and exact-hash
    # approval. Interview questions live in the checkpoint, not in the baseline.
    return []


def require_code_ready(spec: dict[str, Any]) -> None:
    if spec.get("schema_version") != "2.0":
        raise SdlcError("code 门禁只接受已发布的 Schema v2 Spec")


def render_test_results(data: dict[str, Any]) -> str:
    lines = [
        f"# 测试结果 {data['version']}",
        "",
        f"- 状态：`{data['status']}`",
        f"- 开始：`{data['started_at']}`",
        f"- 结束：`{data['finished_at']}`",
        "",
        "| T-id | 结果 | 耗时(ms) | 日志 |",
        "|---|---:|---:|---|",
    ]
    for item in data["results"]:
        lines.append(
            f"| {item['id']} | {item['status']} | {item.get('duration_ms', 0)} | "
            f"`{item.get('log', '')}` |"
        )
    if data.get("open_issues"):
        lines += [
            "",
            "## Open issues",
            "",
            *[f"- {item}" for item in data["open_issues"]],
        ]
    return "\n".join(lines).rstrip() + "\n"


def load_current_spec(root: Path) -> dict[str, Any]:
    """Load the published v2 bundle and derive the runtime view used by Core.

    This view is never persisted as aggregate requirements/design/test-plan files.
    """
    materialize_bundle(root, "spec")
    bundle, _ = _v2_bundle(root)
    feature_map = read_json(bundle / "feature-map.json")
    validate_schema_instance(root, "v2/feature-map.schema.json", feature_map)
    requirements = _documents(root, bundle, "requirements", "v2/requirement.schema.json")
    designs = _documents(root, bundle, "designs", "v2/design.schema.json")
    verification = _documents(
        root, bundle, "verification", "v2/verification.schema.json"
    )
    scaffold = read_json(root / ".sdlc-pipeline" / "scaffold.json")
    extension_paths = {
        item["id"]: item["path"]
        for item in scaffold.get("extension_points", [])
    }
    source_ids = sorted({
        ref["source_id"]
        for requirement in requirements
        for ref in requirement["source_refs"]
    })
    sources = [load_source(root, source_id) for source_id in source_ids]
    runtime_requirements = [
        {
            **item,
            "description": (
                f"目标：{item['goal']}；参与者：{item['actor']}；"
                f"主流程：" + " → ".join(item["main_flow"])
            ),
        }
        for item in requirements
    ]
    runtime_designs = [
        {
            **design,
            "description": "；".join(
                f"{item['name']}：{item['responsibility']}（seam: {item['seam']}）"
                for item in design["modules"]
            ),
            "module": design["modules"][0]["name"],
            "extension_point": design["extension_points"][0],
            "allowed_paths": sorted({
                extension_paths[item] for item in design["extension_points"]
            }),
        }
        for design in designs
    ]
    runtime_tests = [
        {
            **item,
            "title": f"{item['id']} 交付验证",
            "command": item["test_key"],
            "input": ", ".join(item["acceptance_criteria_ids"]),
        }
        for item in verification
    ]
    return {
        "schema_version": "2.0",
        "flow": "standard",
        "feature_map": feature_map,
        "requirements": {
            "source_inputs": sources,
            "analysis": {
                "confirmed_facts": [],
                "impact_scope": sorted({
                    scope for item in requirements for scope in item["scope"]
                }),
                "assumptions": [],
                "open_questions": [],
                "risks": [],
                "decisions": [
                    decision for item in designs for decision in item["decisions"]
                ],
            },
            "items": runtime_requirements,
        },
        "design": {"items": runtime_designs},
        "test_plan": {"items": runtime_tests},
    }


def _v2_bundle(root: Path) -> tuple[Path, dict[str, Any]]:
    selected = current_bundle(root, "spec")
    if not selected:
        raise SdlcError("没有已发布的 Schema v2 Spec bundle")
    bundle, manifest = selected
    if manifest.get("metadata", {}).get("schema_version") != "2.0":
        raise SdlcError("当前 Spec bundle 不是 Schema v2")
    files = manifest.get("files", {})
    required = {"feature-map.json"}
    if not required <= set(files):
        raise SdlcError("Schema v2 Spec bundle 缺少 feature-map.json")
    for prefix in ("requirements/", "designs/", "verification/"):
        if not any(name.startswith(prefix) for name in files):
            raise SdlcError(f"Schema v2 Spec bundle 缺少 {prefix}")
    return bundle, manifest


def _documents(
    root: Path,
    bundle: Path,
    folder: str,
    schema_name: str,
) -> list[dict[str, Any]]:
    directory = bundle / folder
    documents = [read_json(path) for path in sorted(directory.glob("*.json"))]
    if not documents:
        raise SdlcError(f"Schema v2 Spec bundle 缺少 {folder} artifact")
    for document in documents:
        validate_schema_instance(root, schema_name, document)
    return documents
