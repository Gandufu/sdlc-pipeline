from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))


class LightweightDeliveryContractTests(unittest.TestCase):
    def test_context_pack_is_a_progressive_resource_manifest(self) -> None:
        from sdlc_core.adapter import before_task
        from sdlc_core.artifacts import publish_spec
        from sdlc_core.lifecycle import init_project
        from tests.test_pipeline import ProjectFixture, spec_payload

        fixture = ProjectFixture()
        try:
            init_project(fixture.root)
            publish_spec(fixture.root, spec_payload())

            result = before_task(fixture.root, "coder")
            pack = json.loads(
                (fixture.root / result["context_pack"]["paths"][0]).read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(pack["mode"], "progressive")
            self.assertEqual(pack["brief"]["requirement_ids"], ["R-0001"])
            self.assertTrue(pack["resources"])
            self.assertNotIn("content", json.dumps(pack, ensure_ascii=False))
            self.assertTrue(all(
                {"path", "sha256", "tier", "reason"}.issubset(resource)
                for resource in pack["resources"]
            ))
            self.assertLess(result["context_pack"]["characters"], 15_000)
        finally:
            fixture.close()

    def test_focused_check_runs_only_feature_test_keys(self) -> None:
        from sdlc_core.artifacts import publish_spec
        from sdlc_core.common import SdlcError
        from sdlc_core.lifecycle import init_project, run_focused_checks
        from tests.test_pipeline import ProjectFixture, spec_payload

        fixture = ProjectFixture()
        try:
            init_project(fixture.root)
            publish_spec(fixture.root, spec_payload())

            (fixture.root / "tests/test_feature.py").write_text(
                "def test_feature(): assert True\n",
                encoding="utf-8",
            )
            result = run_focused_checks(fixture.root, ["T-0001"])
            repeated = run_focused_checks(fixture.root, ["T-0001"])

            self.assertTrue(result["ok"])
            self.assertEqual(result["selected"], ["T-0001"])
            self.assertTrue(repeated["results"][0]["cached"])
            self.assertEqual(
                repeated["results"][0]["log"],
                result["results"][0]["log"],
            )
            with self.assertRaisesRegex(SdlcError, "Feature Contract"):
                run_focused_checks(fixture.root, ["T-9999"])
        finally:
            fixture.close()

    def test_delivery_memory_is_derived_and_hash_invalidated(self) -> None:
        from sdlc_core.artifacts import publish_spec
        from sdlc_core.memory import delivery_memory
        from tests.test_pipeline import ProjectFixture, spec_payload

        fixture = ProjectFixture()
        try:
            payload = spec_payload()
            payload["requirements"]["analysis"]["decisions"] = ["复用 feature seam"]
            publish_spec(fixture.root, payload)

            first = delivery_memory(fixture.root)
            self.assertIn("复用 feature seam", first["decisions"])
            self.assertNotIn("原始用户输入", json.dumps(first, ensure_ascii=False))

            lifecycle = fixture.root / ".sdlc-pipeline/lifecycle.json"
            value = json.loads(lifecycle.read_text(encoding="utf-8"))
            value["project_type"] = "python-fixture-v2"
            lifecycle.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            second = delivery_memory(fixture.root)
            self.assertNotEqual(first["binding"], second["binding"])
            self.assertFalse(second["cached"])
        finally:
            fixture.close()

    def test_git_porcelain_preserves_first_unstaged_path(self) -> None:
        from sdlc_core.trace import changed_paths

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Tests"],
                cwd=root,
                check=True,
            )
            source = root / "src" / "main"
            source.mkdir(parents=True)
            path = source / "ipc.ts"
            path.write_text("export const value = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
            path.write_text("export const value = 2\n", encoding="utf-8")

            self.assertEqual(changed_paths(root), ["src/main/ipc.ts"])

    def test_feature_contract_is_the_single_model_authored_spec(self) -> None:
        schema = json.loads(
            (REPO / "schemas/feature-contract.schema.json").read_text(
                encoding="utf-8"
            )
        )
        required = set(schema["required"])
        self.assertTrue({
            "feature", "design", "verification", "spec_confirmed"
        }.issubset(required))
        feature_required = set(schema["properties"]["feature"]["required"])
        self.assertTrue({
            "id", "goal", "actor", "scope", "non_goals", "domain_data",
            "main_flow", "alternate_flows", "acceptance_criteria",
        }.issubset(feature_required))

    def test_feature_contract_publishes_one_atomic_three_view_bundle(self) -> None:
        from sdlc_core.feature_contracts import publish_feature_contract
        from sdlc_core.sources import ingest_source
        from tests.test_pipeline import ProjectFixture

        fixture = ProjectFixture()
        try:
            source = ingest_source(
                fixture.root,
                {"kind": "inline", "content": "设备管理展示系统信息"},
            )["envelope"]
            contract = {
                "schema_version": "1.0",
                "spec_confirmed": True,
                "feature": {
                    "id": "F-0001",
                    "title": "设备系统信息",
                    "goal": "展示设备的系统信息",
                    "actor": "设备管理员",
                    "source_refs": [{
                        "source_id": source["source_id"],
                        "anchor": "text:1",
                    }],
                    "scope": ["读取并展示系统信息"],
                    "non_goals": ["修改设备配置"],
                    "domain_data": [{
                        "name": "SystemInfo",
                        "description": "设备系统信息快照",
                    }],
                    "main_flow": ["打开设备管理", "读取系统信息", "展示结果"],
                    "alternate_flows": [{
                        "name": "读取失败",
                        "steps": ["显示可定位错误"],
                    }],
                    "acceptance_criteria": [{
                        "id": "AC-0001",
                        "given": "设备可访问",
                        "when": "打开系统信息",
                        "then": "展示系统信息字段",
                    }],
                },
                "design": {
                    "modules": [{
                        "name": "SystemInfoView",
                        "responsibility": "读取并展示系统信息",
                        "seam": "feature extension",
                    }],
                    "interfaces": [{
                        "name": "getSystemInfo",
                        "input": "deviceId:string",
                        "output": "SystemInfo",
                        "errors": ["UNREACHABLE"],
                    }],
                    "data_contracts": [{
                        "name": "SystemInfo",
                        "fields": [{
                            "name": "version",
                            "type": "string",
                            "required": True,
                            "source": "device API",
                        }],
                    }],
                    "extension_points": ["feature"],
                    "decisions": ["复用 scaffold feature seam"],
                },
                "verification": [{
                    "ac_id": "AC-0001",
                    "test_key": "functional",
                    "level": "functional",
                    "selector": "tests/functional/device-system-info.functional.ts",
                    "expected": "系统信息字段可见",
                }],
            }

            published = publish_feature_contract(fixture.root, contract)
            bundle = fixture.root / "docs/sdlc/bundles" / published["bundle_id"]
            for name in (
                "feature-contract.json", "requirements.json",
                "design.json", "test-plan.json",
            ):
                self.assertTrue((bundle / name).is_file(), name)
        finally:
            fixture.close()

    def test_plugin_has_one_coder_and_no_obsolete_delivery_contract(self) -> None:
        plugin = (
            REPO / ".opencode/plugins/sdlc-pipeline.js"
        ).read_text(encoding="utf-8")
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")
        lifecycle_schema = (
            REPO / "schemas/lifecycle.schema.json"
        ).read_text(encoding="utf-8")
        spec_schema = (
            REPO / "schemas/spec.schema.json"
        ).read_text(encoding="utf-8")

        self.assertFalse((REPO / ".opencode/agents/sdlc-executor.md").exists())
        self.assertNotIn("sdlc-executor", plugin + main)
        self.assertNotIn("idempotency_key", plugin)
        self.assertNotIn('"browser"', lifecycle_schema)
        self.assertIn("verify_delivery", plugin)

    def test_plugin_exposes_only_intent_level_lifecycle_actions(self) -> None:
        import re

        plugin = (
            REPO / ".opencode/plugins/sdlc-pipeline.js"
        ).read_text(encoding="utf-8")
        match = re.search(
            r"action: tool\.schema\.enum\(\[(.*?)\]\)",
            plugin,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        actions = set(re.findall(r'"([^"]+)"', match.group(1)))
        self.assertEqual(
            actions,
            {"init", "focused_check", "verify_delivery"},
        )
        self.assertIn('"sdlc-coder": ["focused_check"]', plugin)

    def test_coder_handoff_contains_only_agent_owned_information(self) -> None:
        schema = json.loads(
            (REPO / "schemas/handoff.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(schema["required"]),
            {"summary", "open_issues"},
        )
        properties = set(schema["properties"])
        self.assertNotIn("changed_files", properties)
        self.assertNotIn("design_to_code", properties)
        self.assertNotIn("test_to_files", properties)

    def test_policy_controls_are_not_required_feature_tests(self) -> None:
        policy_schema = json.loads(
            (REPO / "schemas/rule-policy.schema.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("required_test_keys", policy_schema["required"])
        self.assertNotIn("required_test_keys", policy_schema["properties"])
        typescript = json.loads(
            (REPO / "rules/typescript.policy.json").read_text(encoding="utf-8")
        )
        react = json.loads(
            (REPO / "rules/react.policy.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("required_test_keys", typescript)
        self.assertNotIn("required_test_keys", react)

    def test_repeated_identical_failure_is_bounded(self) -> None:
        from sdlc_core.common import SdlcError
        from sdlc_core.journal import begin_attempt, finish_attempt, journal_status

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for _ in range(2):
                attempt = begin_attempt(
                    root,
                    phase="code",
                    step="focused-check",
                    operation="lifecycle",
                    payload={"action": "focused-check"},
                )
                finish_attempt(
                    root,
                    attempt,
                    state="failed",
                    error="TypeScript compile failed: TS2322",
                )
            current = journal_status(root)
            self.assertEqual(current["state"], "blocked")
            self.assertEqual(current["last_failure"]["repeat_count"], 2)
            with self.assertRaisesRegex(SdlcError, "BLOCKED"):
                begin_attempt(
                    root,
                    phase="code",
                    step="focused-check",
                    operation="lifecycle",
                    payload={"action": "focused-check"},
                )


if __name__ == "__main__":
    unittest.main()
