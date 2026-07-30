from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sdlc_core.artifacts import load_current_spec  # noqa: E402
from sdlc_core.cli import execute  # noqa: E402
from sdlc_core.common import SdlcError  # noqa: E402
from sdlc_core.specs import approve_spec, prepare_spec  # noqa: E402
from sdlc_core.task_state import record_input, task_status, transition  # noqa: E402


class TaskFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        contracts = self.root / ".sdlc-pipeline" / "contracts"
        contracts.mkdir(parents=True)
        (contracts / "lifecycle.json").write_text(
            json.dumps({
                "schema_version": "1.1",
                "commands": {},
                "tests": {
                    "unit": {
                        "argv": ["node", "--test"],
                        "cwd": ".",
                        "timeout_seconds": 30,
                        "requires_runtime": False,
                        "allow_selector": True,
                        "selector_patterns": ["tests/*.test.ts"],
                    }
                },
            }),
            encoding="utf-8",
        )
        (contracts / "scaffold.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "template_id": "test",
                "protected_paths": [".sdlc-pipeline/**"],
                "allowed_paths": ["src/**", "tests/**"],
                "extension_points": [{"id": "app", "path": "src/**"}],
            }),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_raw_input_creates_task_and_only_appends_user_text(self) -> None:
        first = record_input(self.root, "实现设备管理")
        second = record_input(self.root, "增加刷新功能")
        self.assertEqual(first["task"]["task_id"], second["task"]["task_id"])
        text = (self.root / ".sdlc-pipeline/work/input.md").read_text(encoding="utf-8")
        self.assertIn("实现设备管理", text)
        self.assertIn("增加刷新功能", text)
        self.assertNotIn("assistant", text.lower())

    def test_final_state_graph_supports_all_rework_edges(self) -> None:
        record_input(self.root, "需求")
        transition(self.root, "spec_prepared")
        transition(self.root, "spec_approved")
        transition(self.root, "code_completed")
        transition(self.root, "implementation_issue")
        transition(self.root, "code_completed")
        transition(self.root, "requirements_issue")
        transition(self.root, "spec_prepared")
        transition(self.root, "spec_approved")
        transition(self.root, "code_completed")
        transition(self.root, "review_passed")
        transition(self.root, "test_issue")
        transition(self.root, "test_completed")
        transition(self.root, "finalized")
        self.assertEqual(task_status(self.root)["stage"], "finalized")

    def test_invalid_transition_is_rejected(self) -> None:
        record_input(self.root, "需求")
        with self.assertRaises(SdlcError):
            transition(self.root, "review_passed")

    def test_missing_spec_diagnostic_does_not_reference_removed_layout(self) -> None:
        with self.assertRaisesRegex(SdlcError, "^没有已发布的 Spec baseline$"):
            load_current_spec(self.root)

    def test_finalized_input_creates_linked_task(self) -> None:
        record_input(self.root, "任务一")
        for event in (
            "spec_prepared", "spec_approved", "code_completed",
            "review_passed", "test_completed", "finalized",
        ):
            transition(self.root, event)
        previous = task_status(self.root)["task_id"]
        created = record_input(self.root, "任务二")
        self.assertEqual(created["task"]["previous_task_id"], previous)
        self.assertEqual(created["task"]["stage"], "spec")

    def test_prepare_persists_only_hash_then_approve_publishes_baseline(self) -> None:
        record_input(self.root, "实现设备管理")
        spec = _spec()
        ready = prepare_spec(self.root, spec)
        self.assertEqual(task_status(self.root)["stage"], "awaiting_spec_approval")
        work = self.root / ".sdlc-pipeline" / "work"
        self.assertEqual(
            sorted(path.name for path in work.iterdir()),
            ["input.md"],
        )
        published = approve_spec(
            self.root,
            spec,
            content_hash=ready["content_hash"],
            confirmed=True,
        )
        self.assertEqual(task_status(self.root)["stage"], "code")
        baseline = self.root / "docs/sdlc/baselines" / published["baseline_id"]
        self.assertTrue((baseline / "spec.md").is_file())
        self.assertTrue((baseline / "requirements/R-0001.md").is_file())
        self.assertFalse((self.root / ".sdlc-pipeline/work/candidates").exists())
        self.assertFalse((self.root / ".sdlc-pipeline/work/sources").exists())
        loaded = load_current_spec(self.root)
        self.assertEqual(loaded["requirements"]["items"][0]["id"], "R-0001")

    def test_approve_rejects_changed_or_unconfirmed_spec(self) -> None:
        record_input(self.root, "实现设备管理")
        spec = _spec()
        ready = prepare_spec(self.root, spec)
        changed = {**spec, "title": "变化后的需求"}
        with self.assertRaises(SdlcError):
            approve_spec(
                self.root,
                changed,
                content_hash=ready["content_hash"],
                confirmed=True,
            )
        with self.assertRaises(SdlcError):
            approve_spec(
                self.root,
                spec,
                content_hash=ready["content_hash"],
                confirmed=False,
            )

    def test_cli_spec_does_not_create_attempt_or_temporary_body(self) -> None:
        execute(self.root, "task-state", {
            "action": "record-input",
            "text": "实现设备管理",
        })
        ready = execute(self.root, "spec", {
            "action": "prepare",
            "spec": _spec(),
        })
        self.assertEqual(ready["state"], "awaiting_spec_approval")
        self.assertFalse((self.root / ".sdlc-pipeline/state/runs").exists())
        self.assertFalse((self.root / ".sdlc-pipeline/work/runs").exists())

    def test_removed_subsystems_are_not_shipped(self) -> None:
        for path in (
            "scripts/sdlc_core/sources.py",
            "scripts/sdlc_core/spec_candidates.py",
            "scripts/sdlc_core/spec_publisher.py",
            "scripts/sdlc_core/feedback.py",
            "schemas/candidate-revision.schema.json",
            "schemas/interactions/spec-work.schema.json",
            "schemas/interactions/rework.schema.json",
        ):
            self.assertFalse((ROOT / path).exists(), path)

    def test_plugin_surface_is_five_tools(self) -> None:
        plugin = (ROOT / ".opencode/plugins/sdlc-pipeline.js").read_text(encoding="utf-8")
        tools = {
            name for name in (
                "sdlc_status", "sdlc_task", "sdlc_spec",
                "sdlc_lifecycle", "sdlc_finalize",
            )
            if f"{name}: tool(" in plugin
        }
        self.assertEqual(len(tools), 5)
        for removed in ("sdlc_ingest_source", "sdlc_begin_candidate", "sdlc_begin_rework"):
            self.assertNotIn(removed, plugin)


def _spec() -> dict:
    return {
        "title": "设备管理",
        "requirements": [{
            "feature_id": "F-0001",
            "title": "查看设备",
            "goal": "用户可以查看设备状态",
            "actor": "管理员",
            "scope": ["设备列表"],
            "non_goals": [],
            "main_flow": ["打开设备列表", "显示设备状态"],
            "alternate_flows": [],
            "acceptance_criteria": [{
                "given": "存在设备",
                "when": "打开设备列表",
                "then": "显示设备状态",
            }],
        }],
        "designs": [{
            "title": "设备模块",
            "requirement_ids": ["R-0001"],
            "modules": [{"name": "Device", "responsibility": "设备查询", "seam": "renderer"}],
            "interfaces": [],
            "data_contracts": [],
            "extension_points": ["app"],
            "decisions": [],
        }],
        "verification": [{
            "requirement_ids": ["R-0001"],
            "design_ids": ["D-0001"],
            "acceptance_criteria_ids": ["AC-R-0001-01"],
            "level": "unit",
            "test_key": "unit",
            "selector": "tests/device.test.ts",
            "preconditions": "存在设备",
            "expected": "显示设备状态",
            "mandatory": True,
        }],
    }


if __name__ == "__main__":
    unittest.main()
