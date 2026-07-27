from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import publish_spec
from .common import SdlcError
from .schema_validation import validate_schema_instance
from .sources import load_source
from .trace import scaffold


def publish_feature_contract(root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    """Publish one model-authored Feature Contract as deterministic R/D/T views."""
    validate_schema_instance(root, "feature-contract.schema.json", contract)
    feature = contract["feature"]
    criteria = feature["acceptance_criteria"]
    criterion_ids = [item["id"] for item in criteria]
    if len(set(criterion_ids)) != len(criterion_ids):
        raise SdlcError("Feature Contract 包含重复 AC-id")
    verification_ids = [item["ac_id"] for item in contract["verification"]]
    if set(verification_ids) != set(criterion_ids):
        raise SdlcError("verification 必须完整且只覆盖 Feature Contract 的 AC-id")

    sources = []
    refs = []
    for ref in feature["source_refs"]:
        source = load_source(root, ref["source_id"])
        anchors = {item["anchor"] for item in source["segments"]}
        if ref["anchor"] not in anchors:
            raise SdlcError(
                f"未知来源 anchor: {ref['source_id']}#{ref['anchor']}"
            )
        if source["source_id"] not in {item["source_id"] for item in sources}:
            sources.append(source)
        refs.append(f"{ref['source_id']}#{ref['anchor']}")

    scaffold_contract = scaffold(root)
    extension_paths = {
        item["id"]: item["path"]
        for item in scaffold_contract["extension_points"]
    }
    unknown = sorted(set(contract["design"]["extension_points"]) - set(extension_paths))
    if unknown:
        raise SdlcError(f"Feature Contract 引用未知 extension point: {unknown}")
    allowed_paths = sorted({
        extension_paths[item]
        for item in contract["design"]["extension_points"]
    })

    source_refs = refs
    acceptance = [
        {
            "id": f"AC-R-0001-{index:02d}",
            "description": (
                f"Given {item['given']}；When {item['when']}；Then {item['then']}"
            ),
            "source_refs": source_refs,
        }
        for index, item in enumerate(criteria, 1)
    ]
    modules = contract["design"]["modules"]
    interfaces = [
        (
            f"{item['name']}: input={item['input']}; output={item['output']}; "
            f"errors={', '.join(item['errors']) or 'none'}"
        )
        for item in contract["design"]["interfaces"]
    ]
    data_model = [
        f"{item['name']}: " + ", ".join(
            f"{field['name']}:{field['type']}"
            f"{'' if field['required'] else '?'}@{field['source']}"
            for field in item["fields"]
        )
        for item in contract["design"]["data_contracts"]
    ]
    payload = {
        "schema_version": "1.1",
        "flow": "standard",
        "spec_confirmed": contract["spec_confirmed"],
        "requirements": {
            "source_inputs": sources,
            "analysis": {
                "confirmed_facts": [],
                "impact_scope": feature["scope"],
                "assumptions": [],
                "open_questions": [],
                "risks": [],
                "decisions": contract["design"]["decisions"],
            },
            "items": [{
                "id": "R-0001",
                "title": feature["title"],
                "description": (
                    f"目标：{feature['goal']}；参与者：{feature['actor']}；"
                    f"主流程：" + " → ".join(feature["main_flow"])
                ),
                "acceptance_criteria": acceptance,
                "source_refs": source_refs,
            }],
            "change_flags": {},
        },
        "design": {"items": [{
            "id": "D-0001",
            "title": f"{feature['title']}功能设计",
            "description": "；".join(
                f"{item['name']}：{item['responsibility']}（seam: {item['seam']}）"
                for item in modules
            ),
            "requirement_ids": ["R-0001"],
            "module": feature["id"],
            "extension_point": contract["design"]["extension_points"][0],
            "allowed_paths": allowed_paths,
            "interfaces": interfaces,
            "data_model": data_model,
        }]},
        "test_plan": {"items": [
            {
                "id": f"T-{index:04d}",
                "title": f"{item['ac_id']} 交付验证",
                "requirement_ids": ["R-0001"],
                "design_ids": ["D-0001"],
                "level": item["level"],
                "preconditions": "实现候选已生成",
                "input": item["ac_id"],
                "expected": item["expected"],
                "mandatory": True,
                "command": item["test_key"],
            }
            for index, item in enumerate(contract["verification"], 1)
        ]},
    }
    result = publish_spec(root, payload, feature_contract=contract)
    return {"ok": True, "feature_id": feature["id"], **result}
