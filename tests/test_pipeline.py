from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sdlc_core.artifacts import load_current_spec  # noqa: E402
from sdlc_core.adapter import (  # noqa: E402
    before_task,
    build_context_pack,
    validate_coder_handoff,
)
from sdlc_core.cli import execute  # noqa: E402
from sdlc_core.common import SdlcError, git  # noqa: E402
from sdlc_core.journal import begin_attempt, finish_attempt  # noqa: E402
from sdlc_core.specs import approve_spec, prepare_spec  # noqa: E402
from sdlc_core.stores import (  # noqa: E402
    read_work_record,
    write_evidence_record,
    write_work_record,
)
from sdlc_core.task_state import record_input, task_status, transition  # noqa: E402
from sdlc_core.trace import (  # noqa: E402
    _is_pipeline_managed_path,
    implementation_fingerprint,
    validate_diff,
)


class TaskFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        contracts = self.root / ".sdlc-pipeline" / "contracts"
        contracts.mkdir(parents=True)
        (contracts / "lifecycle.json").write_text(
            json.dumps({
                "schema_version": "1.1",
                "project_type": "test",
                "tools": [],
                "commands": {
                    name: {
                        "argv": ["node", "--version"],
                        "timeout_seconds": 30,
                        **({"background": True} if name == "start" else {}),
                    }
                    for name in (
                        "install", "compile", "package", "start",
                        "lint", "typecheck",
                    )
                },
                "health": [{"type": "process", "timeout_seconds": 10}],
                "artifacts": ["dist/app.js"],
                "test_preflight": [{
                    "argv": ["node", "--test"],
                    "timeout_seconds": 30,
                }],
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
                "template_version": "1.0",
                "key_files": [],
                "protected_paths": [".sdlc-pipeline/**"],
                "allowed_paths": ["src/**", "tests/**", "assets"],
                "extension_points": [
                    {"id": "app", "path": "src/**"},
                    {"id": "renderer-assets", "path": "assets"},
                ],
                "lifecycle_hash": "0" * 64,
                "capabilities": [],
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

    def test_core_canonicalizes_agent_generated_spec_identifiers(self) -> None:
        record_input(self.root, "实现设备管理")
        spec = _spec()
        spec["requirements"][0]["id"] = "REQ-DEVICE"
        spec["requirements"][0]["feature_id"] = "FEATURE-DEVICE"
        spec["designs"][0]["id"] = "DESIGN-DEVICE"
        spec["designs"][0].pop("requirement_ids")
        spec["designs"][0]["extension_points"] = ["semantic renderer description"]
        spec["verification"][0].update({
            "id": "VERIFY-DEVICE",
            "design_ids": ["DESIGN-DEVICE"],
            "acceptance_criteria_ids": ["REQ-DEVICE-AC1"],
            "test_key": "invented-suite",
            "selector": "invented/path.test.ts",
        })
        spec["verification"][0].pop("requirement_ids")
        ready = prepare_spec(self.root, spec)
        self.assertEqual(
            ready["affected_ids"],
            {"R": ["R-0001"], "D": ["D-0001"], "T": ["T-0001"]},
        )
        published = approve_spec(
            self.root,
            spec,
            content_hash=ready["content_hash"],
            confirmed=True,
        )
        loaded = load_current_spec(self.root)
        self.assertEqual(loaded["requirements"]["items"][0]["feature_id"], "F-0001")
        self.assertEqual(loaded["design"]["items"][0]["requirement_ids"], ["R-0001"])
        self.assertEqual(loaded["test_plan"]["items"][0]["command"], "unit")
        self.assertEqual(
            loaded["test_plan"]["items"][0]["selector"],
            "tests/T-0001.test.ts",
        )
        self.assertTrue(published["baseline_id"])

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

    def test_awaiting_approval_accepts_revised_preview(self) -> None:
        record_input(self.root, "实现设备管理")
        first = _spec()
        first_ready = prepare_spec(self.root, first)
        revised = {**first, "title": "修订后的设备管理"}
        revised_ready = prepare_spec(self.root, revised)
        self.assertEqual(task_status(self.root)["stage"], "awaiting_spec_approval")
        self.assertNotEqual(first_ready["content_hash"], revised_ready["content_hash"])
        with self.assertRaises(SdlcError):
            approve_spec(
                self.root,
                first,
                content_hash=first_ready["content_hash"],
                confirmed=True,
            )
        published = approve_spec(
            self.root,
            revised,
            content_hash=revised_ready["content_hash"],
            confirmed=True,
        )
        self.assertTrue(published["baseline_id"])

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

    def test_successful_attempt_does_not_duplicate_result_under_work(self) -> None:
        attempt = begin_attempt(
            self.root,
            phase="init",
            step="init",
            operation="lifecycle",
            payload={"action": "init"},
        )
        finish_attempt(
            self.root,
            attempt,
            state="succeeded",
            result={"ok": True, "large": "not persisted"},
        )
        self.assertFalse((self.root / ".sdlc-pipeline/work/runs").exists())

    def test_attempt_error_body_is_kept_only_in_markdown_evidence(self) -> None:
        attempt = begin_attempt(
            self.root,
            phase="code",
            step="coder",
            operation="task-before",
            payload={"agent": "sdlc-coder"},
        )
        error = "业务错误详情" * 200

        finish_attempt(self.root, attempt, state="failed", error=error)

        run = json.loads(
            (
                self.root
                / ".sdlc-pipeline"
                / "state"
                / "runs"
                / attempt["run_id"]
                / "index.json"
            ).read_text(encoding="utf-8")
        )
        self.assertNotIn("last_failure", run)
        self.assertEqual(1, run["consecutive_failures"])
        error_path = self.root / run["last_error_ref"]
        self.assertIn(error, error_path.read_text(encoding="utf-8"))

    def test_coder_context_references_latest_failure_markdown(self) -> None:
        record_input(self.root, "实现设备管理")
        ready = prepare_spec(self.root, _spec())
        approve_spec(
            self.root,
            _spec(),
            content_hash=ready["content_hash"],
            confirmed=True,
        )
        source = self.root / "src" / "app.ts"
        source.parent.mkdir(parents=True)
        source.write_text("export const value = 1;\n", encoding="utf-8")
        attempt = begin_attempt(
            self.root,
            phase="code",
            step="compile_restart_verify",
            operation="lifecycle",
            payload={
                "action": "compile_restart_verify",
                "source_fingerprint": implementation_fingerprint(
                    self.root
                )["sha256"],
            },
        )
        finish_attempt(
            self.root,
            attempt,
            state="failed",
            error="compile failed",
        )
        write_evidence_record(
            self.root,
            "init",
            {"status": "pass", "created_at": "2026-01-01T00:00:00Z"},
            state="captured",
            title="Init",
        )

        before_task(self.root, "coder")

        context = read_work_record(self.root, "context/coder")
        failure_ref = context["brief"]["failure_ref"]
        self.assertEqual(
            f".sdlc-pipeline/evidence/errors/{attempt['run_id']}/"
            f"{attempt['attempt_id']}.md",
            failure_ref,
        )
        failure_resource = next(
            item for item in context["resources"]
            if item["path"] == failure_ref
        )
        self.assertEqual(0, failure_resource["tier"])
        self.assertEqual(
            ".sdlc-pipeline/work/input.md",
            context["brief"]["input_ref"],
        )
        input_resource = next(
            item for item in context["resources"]
            if item["path"] == context["brief"]["input_ref"]
        )
        self.assertEqual("original user requirement", input_resource["reason"])

    def test_coder_context_ignores_failure_for_old_source(self) -> None:
        git(self.root, "init")
        record_input(self.root, "实现设备管理")
        ready = prepare_spec(self.root, _spec())
        approve_spec(
            self.root,
            _spec(),
            content_hash=ready["content_hash"],
            confirmed=True,
        )
        source = self.root / "src" / "app.ts"
        source.parent.mkdir(parents=True)
        source.write_text("export const value = 1;\n", encoding="utf-8")
        attempt = begin_attempt(
            self.root,
            phase="code",
            step="compile_restart_verify",
            operation="lifecycle",
            payload={
                "action": "compile_restart_verify",
                "source_fingerprint": implementation_fingerprint(
                    self.root
                )["sha256"],
            },
        )
        finish_attempt(
            self.root,
            attempt,
            state="failed",
            error="compile failed",
        )
        source.write_text("export const value = 2;\n", encoding="utf-8")
        write_evidence_record(
            self.root,
            "init",
            {"status": "pass", "created_at": "2026-01-01T00:00:00Z"},
            state="captured",
            title="Init",
        )

        before_task(self.root, "coder")

        context = read_work_record(self.root, "context/coder")
        self.assertNotIn("failure_ref", context["brief"])
        self.assertFalse(any(
            item["reason"] == "latest code-gate failure evidence"
            for item in context["resources"]
        ))

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
        self.assertNotIn("id: tool.schema.string().optional()", plugin)
        self.assertNotIn("JSON.parse(args.options)", plugin)
        self.assertIn("校验失败后立即向用户报告原始错误并停止", plugin)

    def test_commands_separate_arguments_from_command_instructions(self) -> None:
        for name in ("sdlc-spec.md", "sdlc-code.md", "sdlc-test.md"):
            command = (ROOT / ".opencode" / "commands" / name).read_text(
                encoding="utf-8"
            )
            self.assertIn("<user-input>", command, name)
            self.assertIn("$ARGUMENTS", command, name)
            self.assertIn("</user-input>", command, name)

    def test_status_only_exposes_stage_relevant_contracts(self) -> None:
        record_input(self.root, "实现设备管理")
        spec_status = execute(self.root, "status", {})
        self.assertIn("spec_contract", spec_status)
        self.assertNotIn("templates", spec_status)
        ready = prepare_spec(self.root, _spec())
        approve_spec(
            self.root,
            _spec(),
            content_hash=ready["content_hash"],
            confirmed=True,
        )
        current_task = task_status(self.root)
        write_work_record(
            self.root,
            "coder-handoff",
            {
                "summary": "implemented",
                "open_issues": [],
                "task_id": current_task["task_id"],
                "stage_iteration": current_task["iterations"]["code"],
            },
            state="captured",
            title="Coder handoff",
        )

        code_status = execute(self.root, "status", {})

        self.assertNotIn("spec_contract", code_status)
        self.assertNotIn("templates", code_status)
        self.assertNotIn("active_rules", code_status)
        self.assertNotIn("lifecycle_tests", code_status)
        self.assertTrue(code_status["code_reverify_available"])
        self.assertEqual(
            ".sdlc-pipeline/work/records/coder-handoff.md",
            code_status["artifact_refs"]["coder-handoff"],
        )

    def test_agents_use_role_context_instead_of_directory_acl(self) -> None:
        coder = (ROOT / ".opencode/agents/sdlc-coder.md").read_text(
            encoding="utf-8"
        )
        tester = (ROOT / ".opencode/agents/sdlc-tester.md").read_text(
            encoding="utf-8"
        )
        main = (ROOT / ".opencode/agents/sdlc-main.md").read_text(
            encoding="utf-8"
        )
        plugin = (ROOT / ".opencode/plugins/sdlc-pipeline.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("sdlc_status: deny", coder)
        self.assertIn("禁止制造 no-op 编辑", coder)
        self.assertIn("按实现影响更新既有", coder)
        self.assertIn("禁止绕过失败继续做重复启动", coder)
        self.assertIn("open_issues` 必须是字符串数组", coder)
        for agent in (main, coder, tester):
            self.assertIn("read: allow", agent)
            self.assertIn("edit: allow", agent)
            self.assertIn("bash: allow", agent)
        coder_permissions = coder.split("---", 2)[1]
        tester_permissions = tester.split("---", 2)[1]
        self.assertNotIn("tests/**", coder_permissions)
        self.assertNotIn("tests/**", tester_permissions)
        self.assertIn("主会话拥有项目全部目录", main)
        self.assertNotIn("主会话禁止读取或修改业务源码", main)
        self.assertNotIn('"write-check"', plugin)
        self.assertNotIn('"path-check"', plugin)
        self.assertIn("不要反复 start 或深挖发布包", plugin)
        self.assertIn("handoff rejected", plugin)
        self.assertIn("本次命令必须停止", plugin)
        self.assertLess(
            plugin.index("handoff rejected"),
            plugin.index("receipt?.handoff?.open_issues"),
        )

    def test_coder_can_update_affected_existing_tests(self) -> None:
        record_input(self.root, "实现设备管理")
        ready = prepare_spec(self.root, _spec())
        approve_spec(
            self.root,
            _spec(),
            content_hash=ready["content_hash"],
            confirmed=True,
        )
        git(self.root, "init")
        write_work_record(
            self.root,
            "task/coder-before",
            {"worktree": {"sha256": "0" * 64, "entries": []}},
            state="captured",
            title="coder task before snapshot",
        )
        source = self.root / "src" / "app.ts"
        existing_test = self.root / "tests" / "app.test.ts"
        source.parent.mkdir(parents=True)
        existing_test.parent.mkdir(parents=True)
        source.write_text("export const value = 2;\n", encoding="utf-8")
        existing_test.write_text("expect(value).toBe(2);\n", encoding="utf-8")

        receipt = validate_coder_handoff(
            self.root,
            json.dumps({
                "summary": "更新实现及受影响的既有回归测试",
                "open_issues": [],
                "full_scan": False,
                "full_scan_reason": None,
            }),
        )

        self.assertIn("src/app.ts", receipt["handoff"]["changed_files"])
        self.assertIn(
            "tests/app.test.ts",
            receipt["handoff"]["changed_files"],
        )

    def test_tester_context_references_previous_coder_handoff(self) -> None:
        record_input(self.root, "实现设备管理")
        ready = prepare_spec(self.root, _spec())
        approve_spec(
            self.root,
            _spec(),
            content_hash=ready["content_hash"],
            confirmed=True,
        )
        index = write_work_record(
            self.root,
            "coder-handoff",
            {"summary": "implemented", "open_issues": []},
            state="validated",
            title="Coder handoff",
        )

        build_context_pack(self.root, "tester")
        context = read_work_record(self.root, "context/tester")

        self.assertEqual(["assets"], context["brief"]["asset_paths"])
        self.assertEqual(
            index["content_ref"],
            context["brief"]["previous_handoff_ref"],
        )
        resource = next(
            item for item in context["resources"]
            if item["path"] == index["content_ref"]
        )
        self.assertEqual(0, resource["tier"])
        self.assertEqual("previous coder handoff", resource["reason"])

    def test_human_review_rollback_invalidates_the_previous_coder_handoff(self) -> None:
        record_input(self.root, "实现设备管理")
        ready = prepare_spec(self.root, _spec())
        approve_spec(
            self.root,
            _spec(),
            content_hash=ready["content_hash"],
            confirmed=True,
        )
        current = task_status(self.root)
        write_work_record(
            self.root,
            "coder-handoff",
            {
                "summary": "first implementation",
                "open_issues": [],
                "task_id": current["task_id"],
                "stage_iteration": current["iterations"]["code"],
            },
            state="validated",
            title="Coder handoff",
        )
        self.assertTrue(execute(self.root, "status", {})["code_reverify_available"])

        transition(self.root, "code_completed")
        transition(self.root, "implementation_issue")

        rolled_back = execute(self.root, "status", {})
        self.assertEqual("code", rolled_back["task"]["stage"])
        self.assertFalse(rolled_back["code_reverify_available"])

    def test_delivery_scope_is_observed_without_becoming_a_directory_acl(self) -> None:
        record_input(self.root, "实现设备管理")
        ready = prepare_spec(self.root, _spec())
        approve_spec(
            self.root,
            _spec(),
            content_hash=ready["content_hash"],
            confirmed=True,
        )
        git(self.root, "init")
        outside = self.root / "architecture-notes.txt"
        outside.write_text("main or a role agent may update this file\n", encoding="utf-8")

        diff = validate_diff(self.root, {"entries": []})

        self.assertIn("architecture-notes.txt", diff["changed_paths"])
        self.assertIn(
            "architecture-notes.txt",
            diff["scope_observations"]["outside_declared_scope"],
        )

    def test_pipeline_managed_paths_are_not_business_diff(self) -> None:
        for path in (
            ".opencode/agents/sdlc-coder.md",
            ".sdlc-pipeline/contracts/lifecycle.json",
            "docs/sdlc/current.json",
            "AGENTS.md",
            "opencode.json",
        ):
            self.assertTrue(_is_pipeline_managed_path(path), path)
        self.assertFalse(_is_pipeline_managed_path("src/renderer/App.tsx"))

    def test_code_command_prefers_deterministic_reverification(self) -> None:
        command = (ROOT / ".opencode/commands/sdlc-code.md").read_text(
            encoding="utf-8"
        )
        plugin = (ROOT / ".opencode/plugins/sdlc-pipeline.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("code_reverify_available=true", command)
        self.assertIn("reverify_code", plugin)
        self.assertIn("compile_restart_verify", plugin)

    def test_task_hook_preserves_main_prompt_and_stops_on_open_issues(self) -> None:
        plugin = (ROOT / ".opencode/plugins/sdlc-pipeline.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("delegatedPrompt", plugin)
        self.assertIn("主会话委派内容（原文）", plugin)
        self.assertIn("receipt?.handoff?.open_issues", plugin)
        self.assertIn("未执行后续 gate，也未推进 Task", plugin)
        self.assertLess(
            plugin.index("receipt?.handoff?.open_issues"),
            plugin.index('action: role === "coder" ? "compile_restart_verify"'),
        )


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
