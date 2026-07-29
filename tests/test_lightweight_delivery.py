from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from sdlc_core.records import read_markdown_record  # noqa: E402


class LightweightDeliveryContractTests(unittest.TestCase):
    def test_context_pack_is_a_progressive_resource_manifest(self) -> None:
        from sdlc_core.adapter import before_task
        from sdlc_core.lifecycle import init_project
        from tests.test_pipeline import ProjectFixture, publish_spec, spec_payload

        fixture = ProjectFixture()
        try:
            init_project(fixture.root)
            publish_spec(fixture.root, spec_payload())
            (fixture.root / "src/feature.py").write_text(
                "def feature(): return 'existing'\n",
                encoding="utf-8",
            )

            result = before_task(fixture.root, "coder")
            pack = read_markdown_record(
                fixture.root / result["context_pack"]["paths"][0]
            )

            self.assertEqual(pack["mode"], "progressive")
            self.assertEqual(pack["brief"]["requirement_ids"], ["R-0001"])
            self.assertEqual(pack["brief"]["first_delivery"], {
                "requirement_id": "R-0001",
                "design_ids": ["D-0001"],
            })
            self.assertTrue(pack["resources"])
            self.assertNotIn("content", json.dumps(pack, ensure_ascii=False))
            self.assertTrue(all(
                {"path", "sha256", "tier", "reason"}.issubset(resource)
                for resource in pack["resources"]
            ))
            self.assertLessEqual(len(pack["resources"]), 10)
            self.assertIn(
                "src/feature.py",
                {resource["path"] for resource in pack["resources"]},
            )
            self.assertFalse(any(
                resource["path"].startswith(
                    ".sdlc-pipeline/runtime/scripts/"
                )
                for resource in pack["resources"]
            ))
            self.assertLess(result["context_pack"]["characters"], 8_000)
        finally:
            fixture.close()

    def test_focused_check_runs_only_feature_test_keys(self) -> None:
        from sdlc_core.common import SdlcError
        from sdlc_core.lifecycle import init_project, run_focused_checks
        from tests.test_pipeline import ProjectFixture, publish_spec, spec_payload

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
            with self.assertRaisesRegex(SdlcError, "当前已发布 Spec"):
                run_focused_checks(fixture.root, ["T-9999"])
        finally:
            fixture.close()

    def test_focused_check_executes_shared_selector_once(self) -> None:
        from copy import deepcopy

        from sdlc_core.lifecycle import init_project, run_focused_checks
        from tests.test_pipeline import ProjectFixture, publish_spec, spec_payload

        fixture = ProjectFixture()
        try:
            init_project(fixture.root)
            payload = spec_payload()
            second = deepcopy(payload["test_plan"]["items"][0])
            second["id"] = "T-0002"
            payload["test_plan"]["items"].append(second)
            publish_spec(fixture.root, payload)
            (fixture.root / "tests/test_feature.py").write_text(
                "def test_feature(): assert True\n",
                encoding="utf-8",
            )

            result = run_focused_checks(
                fixture.root,
                ["T-0001", "T-0002"],
            )

            self.assertTrue(result["ok"])
            self.assertEqual(len(result["results"]), 2)
            self.assertEqual(
                result["results"][0]["log"],
                result["results"][1]["log"],
            )
            self.assertEqual(
                result["results"][1]["reused_execution_from"],
                "T-0001",
            )
        finally:
            fixture.close()

    def test_delivery_memory_is_derived_and_hash_invalidated(self) -> None:
        from sdlc_core.memory import delivery_memory
        from tests.test_pipeline import ProjectFixture, publish_spec, spec_payload

        fixture = ProjectFixture()
        try:
            payload = spec_payload()
            payload["requirements"]["analysis"]["decisions"] = ["复用 feature seam"]
            publish_spec(fixture.root, payload)

            first = delivery_memory(fixture.root)
            self.assertIn("复用 feature seam", first["decisions"])
            self.assertNotIn("原始用户输入", json.dumps(first, ensure_ascii=False))

            lifecycle = (
                fixture.root
                / ".sdlc-pipeline/contracts/lifecycle.json"
            )
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

    def test_layout_v3_artifact_schemas_are_the_only_spec_schemas(self) -> None:
        names = {
            path.relative_to(REPO / "schemas").as_posix()
            for path in (REPO / "schemas").rglob("*.schema.json")
        }
        self.assertIn("artifacts/requirement.schema.json", names)
        self.assertIn("artifacts/design.schema.json", names)
        self.assertIn("artifacts/verification.schema.json", names)
        self.assertNotIn("feature-contract.schema.json", names)
        self.assertNotIn("spec.schema.json", names)

    def test_v3_candidate_publishes_one_atomic_markdown_baseline(self) -> None:
        from tests.test_pipeline import ProjectFixture, publish_spec, spec_payload

        fixture = ProjectFixture()
        try:
            published = publish_spec(fixture.root, spec_payload())
            bundle = fixture.root / "docs/sdlc/baselines" / published["baseline_id"]
            expected = {
                "manifest.json",
                "requirements/R-0001.md",
                "designs/D-0001.md",
                "verification/T-0001.md",
                "spec.md",
            }
            actual = {
                path.relative_to(bundle).as_posix()
                for path in bundle.rglob("*")
                if path.is_file()
            }
            self.assertTrue(expected.issubset(actual))
            self.assertEqual(
                len([path for path in actual if path.endswith("/content.md")]),
                1,
            )
            self.assertEqual(
                len([
                    path
                    for path in actual
                    if path.startswith("sources/") and path.endswith("/index.json")
                ]),
                1,
            )
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
        self.assertFalse((REPO / ".opencode/agents/sdlc-executor.md").exists())
        self.assertTrue((REPO / ".opencode/agents/sdlc-tester.md").exists())
        self.assertNotIn("sdlc-executor", plugin + main)
        self.assertNotIn("sdlc_publish_contract", plugin + main)
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
            {"init", "verify_delivery"},
        )
        self.assertNotIn('"sdlc-coder": ["focused_check"]', plugin)

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
