from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from sdlc_core.sources import ingest_source  # noqa: E402
from sdlc_core.common import SdlcError  # noqa: E402
from sdlc_core.artifacts import load_current_spec  # noqa: E402
from sdlc_core.spec_publisher import approve_and_promote  # noqa: E402
from sdlc_core.delivery_trace import build_delivery_trace  # noqa: E402
from sdlc_core.common import write_json  # noqa: E402
from sdlc_core.schema_validation import validate_schema_instance  # noqa: E402
from sdlc_core.spec_candidates import (  # noqa: E402
    begin_candidate,
    put_design,
    put_requirement,
    put_verification,
    validate_candidate,
)
from tests.test_pipeline import ProjectFixture  # noqa: E402


class SchemaV2CandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ProjectFixture()
        self.source = ingest_source(
            self.fixture.root,
            {
                "kind": "inline",
                "source": "用户需求",
                "content": "设备管理员可以查看设备系统信息。",
                "segments": [{
                    "anchor": "requirement:system-info",
                    "text": "设备管理员可以查看设备系统信息。",
                }],
            },
        )["envelope"]

    def tearDown(self) -> None:
        self.fixture.close()

    def test_candidate_requirement_update_creates_immutable_revision(self) -> None:
        created = begin_candidate(
            self.fixture.root,
            title="设备管理",
            source_refs=[{
                "source_id": self.source["source_id"],
                "anchor": "requirement:system-info",
            }],
        )

        updated = put_requirement(
            self.fixture.root,
            created["candidate_id"],
            {
                "feature_id": "F-0001",
                "title": "查看系统信息",
                "goal": "管理员能够查看设备系统信息",
                "actor": "设备管理员",
                "scope": ["读取并展示系统信息"],
                "non_goals": ["修改系统信息"],
                "source_refs": [{
                    "source_id": self.source["source_id"],
                    "anchor": "requirement:system-info",
                }],
                "main_flow": ["进入设备管理", "读取系统信息", "展示结果"],
                "alternate_flows": [],
                "acceptance_criteria": [{
                    "given": "设备可访问",
                    "when": "打开系统信息",
                    "then": "展示设备系统信息",
                    "source_refs": [{
                        "source_id": self.source["source_id"],
                        "anchor": "requirement:system-info",
                    }],
                }],
            },
        )

        self.assertEqual(created["revision"], 1)
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(updated["artifact_id"], "R-0001")
        revision_one = (
            self.fixture.root
            / ".sdlc-pipeline/runs/spec-candidates"
            / created["candidate_id"]
            / "revisions/0001/manifest.json"
        )
        revision_two = revision_one.parents[1] / "0002/requirements/R-0001.json"
        self.assertTrue(revision_one.is_file())
        self.assertTrue(revision_two.is_file())
        document = json.loads(revision_two.read_text(encoding="utf-8"))
        self.assertEqual(document["id"], "R-0001")
        self.assertEqual(document["acceptance_criteria"][0]["id"], "AC-R-0001-01")

    def test_validate_candidate_freezes_complete_r_d_t_chain(self) -> None:
        candidate_id = self._candidate_with_requirement()
        design = put_design(
            self.fixture.root,
            candidate_id,
            {
                "title": "设备系统信息读取",
                "requirement_ids": ["R-0001"],
                "modules": [{
                    "name": "DeviceSystemInfo",
                    "responsibility": "读取并规范化系统信息",
                    "seam": "设备管理用例接口",
                }],
                "interfaces": [{
                    "name": "readSystemInfo",
                    "input": "DeviceConnection",
                    "output": "SystemInfo",
                    "errors": ["UNREACHABLE"],
                }],
                "data_contracts": [],
                "extension_points": ["feature"],
                "decisions": ["通过应用服务隔离设备客户端"],
            },
        )
        verification = put_verification(
            self.fixture.root,
            candidate_id,
            {
                "requirement_ids": ["R-0001"],
                "design_ids": [design["artifact_id"]],
                "acceptance_criteria_ids": ["AC-R-0001-01"],
                "level": "functional",
                "test_key": "functional",
                "selector": "tests/functional/device-system-info.functional.ts",
                "preconditions": "候选应用已启动",
                "expected": "展示设备系统信息",
                "mandatory": True,
            },
        )

        ready = validate_candidate(self.fixture.root, candidate_id)

        self.assertEqual(design["artifact_id"], "D-0001")
        self.assertEqual(verification["artifact_id"], "T-0001")
        self.assertEqual(ready["state"], "ready")
        self.assertTrue(ready["content_hash"].startswith("sha256:"))
        revision = (
            self.fixture.root
            / ".sdlc-pipeline/runs/spec-candidates"
            / candidate_id
            / "revisions"
            / f"{ready['revision']:04d}"
        )
        self.assertTrue((revision / "preview.md").is_file())
        report = json.loads((revision / "validation.json").read_text(encoding="utf-8"))
        self.assertTrue(report["ok"])

    def test_validate_candidate_reports_incomplete_trace_without_ready(self) -> None:
        candidate_id = self._candidate_with_requirement()

        with self.assertRaisesRegex(SdlcError, "未关联 Design"):
            validate_candidate(self.fixture.root, candidate_id)

        pointer = json.loads((
            self.fixture.root
            / ".sdlc-pipeline/runs/spec-candidates"
            / candidate_id
            / "candidate.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(pointer["state"], "draft")

    def test_approval_uses_frozen_hash_and_publishes_v2_bundle(self) -> None:
        candidate_id, ready = self._ready_candidate()
        with self.assertRaisesRegex(SdlcError, "hash"):
            approve_and_promote(
                self.fixture.root,
                candidate_id=candidate_id,
                content_hash="sha256:" + ("0" * 64),
                confirmed=True,
            )

        published = approve_and_promote(
            self.fixture.root,
            candidate_id=candidate_id,
            content_hash=ready["content_hash"],
            confirmed=True,
        )
        repeated = approve_and_promote(
            self.fixture.root,
            candidate_id=candidate_id,
            content_hash=ready["content_hash"],
            confirmed=True,
        )

        self.assertEqual(published["bundle_id"], repeated["bundle_id"])
        self.assertTrue(repeated["idempotent"])
        self.assertEqual(load_current_spec(self.fixture.root)["schema_version"], "2.0")
        pointer = json.loads((
            self.fixture.root
            / ".sdlc-pipeline/runs/spec-candidates"
            / candidate_id
            / "candidate.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(pointer["state"], "published")
        self.assertEqual(pointer["published_bundle_id"], published["bundle_id"])

    def test_delivery_trace_is_derived_from_changed_files_after_code(self) -> None:
        candidate_id, ready = self._ready_candidate()
        approve_and_promote(
            self.fixture.root,
            candidate_id=candidate_id,
            content_hash=ready["content_hash"],
            confirmed=True,
        )
        implementation = self.fixture.root / "src/device/system-info.py"
        implementation.parent.mkdir(parents=True, exist_ok=True)
        implementation.write_text("def read_system_info(): return {}\n", encoding="utf-8")
        selector = (
            self.fixture.root
            / "tests/functional/device-system-info.functional.ts"
        )
        selector.parent.mkdir(parents=True, exist_ok=True)
        selector.write_text("export {}\n", encoding="utf-8")
        results = self.fixture.root / "docs/sdlc/test-results/V0001.json"
        write_json(results, {
            "schema_version": "1.0",
            "status": "pass",
            "results": [{"id": "T-0001", "status": "pass"}],
        })

        trace = build_delivery_trace(
            self.fixture.root,
            changed_files=[
                "src/device/system-info.py",
                "tests/functional/device-system-info.functional.ts",
            ],
            test_results_path="docs/sdlc/test-results/V0001.json",
        )

        self.assertTrue(trace["ok"])
        self.assertEqual(trace["rows"][0]["precision"], "scoped")
        self.assertEqual(
            trace["rows"][0]["changed_files"][0]["path"],
            "src/device/system-info.py",
        )
        self.assertEqual(
            trace["rows"][0]["verification"][0]["precision"],
            "direct",
        )

    def test_schema_resolver_rejects_network_reference(self) -> None:
        schema_dir = self.fixture.root / ".sdlc-pipeline/schemas"
        schema_dir.mkdir(parents=True, exist_ok=True)
        write_json(schema_dir / "unsafe.schema.json", {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "https://example.invalid/schema.json",
        })

        with self.assertRaisesRegex(SdlcError, "禁止网络"):
            validate_schema_instance(
                self.fixture.root, "unsafe.schema.json", {}
            )

    def _candidate_with_requirement(self) -> str:
        created = begin_candidate(
            self.fixture.root,
            title="设备管理",
            source_refs=[{
                "source_id": self.source["source_id"],
                "anchor": "requirement:system-info",
            }],
        )
        put_requirement(
            self.fixture.root,
            created["candidate_id"],
            {
                "feature_id": "F-0001",
                "title": "查看系统信息",
                "goal": "管理员能够查看设备系统信息",
                "actor": "设备管理员",
                "scope": ["读取并展示系统信息"],
                "non_goals": ["修改系统信息"],
                "source_refs": [{
                    "source_id": self.source["source_id"],
                    "anchor": "requirement:system-info",
                }],
                "main_flow": ["进入设备管理", "读取系统信息", "展示结果"],
                "alternate_flows": [],
                "acceptance_criteria": [{
                    "given": "设备可访问",
                    "when": "打开系统信息",
                    "then": "展示设备系统信息",
                    "source_refs": [{
                        "source_id": self.source["source_id"],
                        "anchor": "requirement:system-info",
                    }],
                }],
            },
        )
        return created["candidate_id"]

    def _ready_candidate(self) -> tuple[str, dict]:
        candidate_id = self._candidate_with_requirement()
        design = put_design(
            self.fixture.root,
            candidate_id,
            {
                "title": "设备系统信息读取",
                "requirement_ids": ["R-0001"],
                "modules": [{
                    "name": "DeviceSystemInfo",
                    "responsibility": "读取并规范化系统信息",
                    "seam": "设备管理用例接口",
                }],
                "interfaces": [],
                "data_contracts": [],
                "extension_points": ["feature"],
                "decisions": [],
            },
        )
        put_verification(
            self.fixture.root,
            candidate_id,
            {
                "requirement_ids": ["R-0001"],
                "design_ids": [design["artifact_id"]],
                "acceptance_criteria_ids": ["AC-R-0001-01"],
                "level": "functional",
                "test_key": "functional",
                "selector": "tests/functional/device-system-info.functional.ts",
                "preconditions": "候选应用已启动",
                "expected": "展示设备系统信息",
                "mandatory": True,
            },
        )
        return candidate_id, validate_candidate(self.fixture.root, candidate_id)


if __name__ == "__main__":
    unittest.main()
