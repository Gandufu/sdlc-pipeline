from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_documents import read_artifact_document
from .artifact_store import current_baseline
from .common import SdlcError, read_json, sha256_json
from .layout import lifecycle_path, relative_to_project, scaffold_path
from .records import (
    read_compact_index,
    read_markdown_record,
    write_compact_index,
    write_markdown_record,
)
from .schema_validation import validate_schema_instance


def lifecycle_test_commands(root: Path) -> dict[str, dict[str, Any]]:
    contract = read_json(lifecycle_path(root))
    tests = contract.get("tests")
    if not isinstance(tests, dict):
        raise SdlcError("lifecycle.json tests 必须是对象")
    return {
        name: command
        for name, command in tests.items()
        if isinstance(name, str) and isinstance(command, dict)
    }


def current_spec_hashes(root: Path) -> dict[str, str]:
    _, manifest = _baseline(root)

    def group(name: str) -> str:
        return sha256_json({
            item["id"]: item["sha256"]
            for item in manifest[name]
        })

    return {
        "feature_map": sha256_json(_full_feature_map(manifest)),
        "requirements": group("requirements"),
        "designs": group("designs"),
        "verification": group("verification"),
    }


def unresolved_blocking_questions(spec: dict[str, Any]) -> list[dict[str, Any]]:
    return []


def require_code_ready(spec: dict[str, Any]) -> None:
    if spec.get("schema_version") != "3.0":
        raise SdlcError("code 门禁只接受已发布的 Storage Layout v3 Spec")


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


def write_test_results(root: Path, data: dict[str, Any]) -> str:
    directory = root / "docs" / "sdlc" / "test-results" / data["version"]
    content_path = directory / "result.md"
    write_markdown_record(
        content_path,
        data,
        title=f"测试结果 {data['version']}",
        summary_lines=[
            f"- 状态: `{data['status']}`",
            f"- 测试数: `{len(data['results'])}`",
        ],
    )
    index_path = directory / "index.json"
    index = {
        "schema_version": "3.0",
        "version": data["version"],
        "state": data["status"],
        "result_ids": [
            {"id": item["id"], "state": item["status"]}
            for item in data["results"]
        ],
        "content_ref": relative_to_project(root, content_path),
        "content_hash": sha256_json(data),
        "started_at": data["started_at"],
        "finished_at": data["finished_at"],
    }
    write_compact_index(index_path, index)
    return relative_to_project(root, index_path)


def load_test_results(root: Path, index_ref: str) -> dict[str, Any]:
    index = read_compact_index(root / index_ref)
    value = read_markdown_record(root / index["content_ref"])
    if sha256_json(value) != index["content_hash"]:
        raise SdlcError("测试结果 Markdown 与索引 hash 不匹配")
    return value


def load_current_spec(root: Path) -> dict[str, Any]:
    baseline, manifest = _baseline(root)
    feature_map = _full_feature_map(manifest)
    validate_schema_instance(root, "artifacts/feature-map.schema.json", feature_map)
    requirements = _documents(
        root, baseline, manifest, "requirements", "artifacts/requirement.schema.json"
    )
    designs = _documents(
        root, baseline, manifest, "designs", "artifacts/design.schema.json"
    )
    verification = _documents(
        root, baseline, manifest, "verification", "artifacts/verification.schema.json"
    )
    scaffold = read_json(scaffold_path(root))
    extension_paths = {
        item["id"]: item["path"]
        for item in scaffold.get("extension_points", [])
    }
    runtime_requirements = [
        {
            **item,
            "description": (
                f"目标：{item['goal']}；参与者：{item['actor']}；"
                f"主流程：" + " → ".join(item["main_flow"])
            ),
            "content_ref": next(
                (baseline / record["content_ref"]).relative_to(root).as_posix()
                for record in manifest["requirements"]
                if record["id"] == item["id"]
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
            "content_ref": next(
                (baseline / record["content_ref"]).relative_to(root).as_posix()
                for record in manifest["designs"]
                if record["id"] == design["id"]
            ),
        }
        for design in designs
    ]
    runtime_tests = [
        {
            **item,
            "title": f"{item['id']} 交付验证",
            "command": item["test_key"],
            "input": ", ".join(item["acceptance_criteria_ids"]),
            "content_ref": next(
                (baseline / record["content_ref"]).relative_to(root).as_posix()
                for record in manifest["verification"]
                if record["id"] == item["id"]
            ),
        }
        for item in verification
    ]
    return {
        "schema_version": "3.0",
        "flow": "standard",
        "baseline_id": manifest["baseline_id"],
        "feature_map": feature_map,
        "requirements": {
            "source_inputs": [],
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


def _baseline(root: Path) -> tuple[Path, dict[str, Any]]:
    selected = current_baseline(root)
    if not selected:
        raise SdlcError("没有已发布的 Storage Layout v3 Spec baseline")
    baseline, manifest = selected
    for group in ("requirements", "designs", "verification"):
        if not manifest.get(group):
            raise SdlcError(f"Spec baseline 缺少 {group}")
    return baseline, manifest


def _full_feature_map(manifest: dict[str, Any]) -> dict[str, Any]:
    return dict(manifest["feature_index"])


def _documents(
    root: Path,
    baseline: Path,
    manifest: dict[str, Any],
    group: str,
    schema_name: str,
) -> list[dict[str, Any]]:
    documents = []
    for record in manifest[group]:
        document = read_artifact_document(
            baseline / record["content_ref"], group
        )
        validate_schema_instance(root, schema_name, document)
        documents.append(document)
    return documents
