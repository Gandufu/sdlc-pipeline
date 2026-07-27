from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from sdlc_core.adapter import (  # noqa: E402
    before_task,
    build_context_pack,
    validate_coder_handoff,
    validate_executor_handoff,
    validate_write_path,
)
from sdlc_core.artifacts import load_current_spec, publish_spec, validate_spec  # noqa: E402
from sdlc_core.common import (  # noqa: E402
    SdlcError,
    sha256_contract_file,
    sha256_file,
    write_json,
)
from sdlc_core.common import sha256_json  # noqa: E402
from sdlc_core.cli import execute  # noqa: E402
from sdlc_core.lifecycle import (  # noqa: E402
    artifact_evidence,
    compile_restart_verify,
    execute_tests,
    init_project,
    install_system_tool,
    load_contract,
    run_test_plan,
)
from sdlc_core.journal import begin_attempt, journal_status  # noqa: E402
from sdlc_core.policies import evaluate_hard_policies  # noqa: E402
from sdlc_core.runs import clear_active, record_active, record_tokens, stop_active  # noqa: E402
from sdlc_core.sources import ingest_source  # noqa: E402
from sdlc_core.status import status  # noqa: E402
from sdlc_core.trace import (  # noqa: E402
    incremental_eligibility,
    trace_matrix,
    verify_scaffold,
)
from sdlc_core.versions import finalize  # noqa: E402


def run(*argv: str, cwd: Path) -> str:
    result = subprocess.run(
        argv, cwd=cwd, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=True,
    )
    return result.stdout.strip()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def spec_payload() -> dict:
    return {
        "schema_version": "1.0",
        "flow": "standard",
        "spec_confirmed": True,
        "requirements": {
            "source_inputs": [{
                "source": "user",
                "content": "增加一个可以验证编译、重启和测试闭环的健康接口。",
            }],
            "analysis": {
                "confirmed_facts": ["项目已有 feature extension point"],
                "impact_scope": ["src", "tests"],
                "assumptions": [],
                "open_questions": [],
                "risks": ["健康检查必须使用真实进程"],
                "decisions": ["沿用现有 lifecycle 测试命令"],
            },
            "items": [{
                "id": "R-0001",
                "title": "健康接口",
                "description": "交付可验证功能",
                "acceptance_criteria": ["编译、重启和测试全部通过"],
            }],
            "change_flags": {},
        },
        "design": {"items": [{
            "id": "D-0001",
            "title": "功能模块",
            "description": "在既有 extension point 内实现",
            "requirement_ids": ["R-0001"],
            "module": "feature",
            "extension_point": "feature",
            "allowed_paths": ["src", "tests"],
            "interfaces": ["feature() -> str"],
            "data_model": [],
        }]},
        "test_plan": {"items": [{
            "id": "T-0001",
            "title": "功能测试",
            "requirement_ids": ["R-0001"],
            "design_ids": ["D-0001"],
            "level": "unit",
            "preconditions": "已编译并运行",
            "input": "执行 unit",
            "expected": "退出码为 0",
            "mandatory": True,
            "command": "unit",
        }]},
    }


class ProjectFixture:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.port = free_port()
        (self.root / ".sdlc-pipeline").mkdir()
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / ".sdlc-pipeline" / ".gitignore").write_text(
            "runs/\n", encoding="utf-8"
        )
        (self.root / "app.py").write_text(
            "from http.server import BaseHTTPRequestHandler,HTTPServer\n"
            "import os\n"
            "class H(BaseHTTPRequestHandler):\n"
            " def do_GET(self):\n"
            "  self.send_response(200); self.end_headers(); self.wfile.write(b'ok')\n"
            " def log_message(self,*a): pass\n"
            "HTTPServer(('127.0.0.1',int(os.environ.get('PORT','"
            + str(self.port)
            + "'))),H).serve_forever()\n",
            encoding="utf-8",
        )
        (self.root / "build.py").write_text(
            "from pathlib import Path\n"
            "Path('dist').mkdir(exist_ok=True)\n"
            "Path('dist/artifact.txt').write_text('built',encoding='utf-8')\n",
            encoding="utf-8",
        )
        command = lambda code: {  # noqa: E731
            "argv": ["${PYTHON}", "-c", code], "timeout_seconds": 30
        }
        lifecycle = {
            "schema_version": "1.0",
            "project_type": "python-fixture",
            "port": self.port,
            "keep_running_after_init": False,
            "tools": [{
                "name": "python",
                "version": ">=3.10",
                "required": True,
                "probe": {"argv": ["${PYTHON}", "--version"], "timeout_seconds": 10},
                "system_install": {
                    "argv": ["${PYTHON}", "-c", "raise SystemExit(7)"],
                    "timeout_seconds": 10,
                },
            }],
            "commands": {
                "install": command("print('installed')"),
                "compile": {"argv": ["${PYTHON}", "build.py"], "timeout_seconds": 30},
                "start": {
                    "argv": ["${PYTHON}", "app.py"],
                    "timeout_seconds": 30,
                    "startup_grace_seconds": 0.5,
                    "background": True,
                },
                "stop": command("print('runner stop')"),
                "restart": command("print('runner restart')"),
            },
            "health": [
                {"type": "process", "timeout_seconds": 5},
                {
                    "type": "http",
                    "url": f"http://127.0.0.1:{self.port}",
                    "contains": "ok",
                    "timeout_seconds": 5,
                },
                {
                    "type": "browser",
                    "url": f"http://127.0.0.1:{self.port}",
                    "contains": "ok",
                    "timeout_seconds": 5,
                },
                {"type": "file", "path": "dist/artifact.txt", "timeout_seconds": 5},
            ],
            "artifacts": ["dist/artifact.txt"],
            "tests": {
                "unit": command("print('unit pass')"),
                "integration": command("print('integration pass')"),
                "e2e": command("print('e2e pass')"),
                "lint": command("print('lint pass')"),
                "static_analysis": command("print('static pass')"),
            },
        }
        write_json(self.root / ".sdlc-pipeline" / "lifecycle.json", lifecycle)
        scaffold = {
            "schema_version": "1.0",
            "template_id": "fixture",
            "template_version": "1.0.0",
            "key_files": [{
                "path": "app.py",
                "sha256": sha256_contract_file(self.root / "app.py"),
            }],
            "protected_paths": [
                ".sdlc-pipeline/lifecycle.json",
                ".sdlc-pipeline/scaffold.json",
                "app.py",
            ],
            "extension_points": [{"id": "feature", "path": "src"}],
            "allowed_paths": ["src", "tests"],
            "lifecycle_hash": sha256_contract_file(
                self.root / ".sdlc-pipeline" / "lifecycle.json"
            ),
            "capabilities": ["fixture"],
        }
        write_json(self.root / ".sdlc-pipeline" / "scaffold.json", scaffold)
        run("git", "init", "-q", cwd=self.root)
        run("git", "config", "user.email", "sdlc@example.invalid", cwd=self.root)
        run("git", "config", "user.name", "SDLC Test", cwd=self.root)
        run("git", "add", "-A", cwd=self.root)
        run("git", "commit", "-qm", "initial", cwd=self.root)

    def close(self) -> None:
        try:
            stop_active(self.root)
        finally:
            self.temp.cleanup()


class SchemaAndTraceTests(unittest.TestCase):
    def test_spec_schema_requires_confirmation_sources_and_analysis(self) -> None:
        schema = json.loads(
            (REPO / "schemas/spec.schema.json").read_text(encoding="utf-8")
        )
        self.assertIn("spec_confirmed", schema["required"])
        required = schema["properties"]["requirements"]["required"]
        self.assertIn("source_inputs", required)
        self.assertIn("analysis", required)

    def test_valid_spec_has_complete_rdt(self) -> None:
        ids = validate_spec(spec_payload())
        self.assertEqual(ids["R"], {"R-0001"})
        self.assertEqual(ids["D"], {"D-0001"})
        self.assertEqual(ids["T"], {"T-0001"})

    def test_spec_rejects_requirement_without_test(self) -> None:
        payload = spec_payload()
        payload["test_plan"]["items"][0]["requirement_ids"] = []
        with self.assertRaises(SdlcError):
            validate_spec(payload)

    def test_spec_rejects_non_object_requirements_without_traceback(self) -> None:
        payload = spec_payload()
        payload["requirements"] = [{}]
        with self.assertRaisesRegex(SdlcError, "requirements 必须是对象"):
            validate_spec(payload)

    def test_spec_rejects_three_digit_requirement_id(self) -> None:
        payload = spec_payload()
        payload["requirements"]["items"][0]["id"] = "R-001"
        with self.assertRaisesRegex(SdlcError, "非法 requirement ID: 'R-001'"):
            validate_spec(payload)

    def test_publish_requires_explicit_spec_confirmation(self) -> None:
        fixture = ProjectFixture()
        try:
            payload = spec_payload()
            payload["spec_confirmed"] = False
            with self.assertRaisesRegex(SdlcError, "明确确认"):
                publish_spec(fixture.root, payload)
        finally:
            fixture.close()

    def test_publish_rejects_shell_command_instead_of_lifecycle_test_key(self) -> None:
        fixture = ProjectFixture()
        try:
            payload = spec_payload()
            payload["test_plan"]["items"][0]["command"] = "pnpm test"
            with self.assertRaisesRegex(
                SdlcError,
                r"T-0001.*pnpm test.*unit",
            ):
                publish_spec(fixture.root, payload)
            self.assertFalse(
                (fixture.root / "docs/sdlc/current/test-plan.json").exists()
            )
        finally:
            fixture.close()

    def test_resolved_question_requires_resolution(self) -> None:
        payload = spec_payload()
        payload["requirements"]["analysis"]["open_questions"] = [{
            "id": "Q-0001",
            "question": "是否修改公共接口？",
            "blocking": True,
            "status": "resolved",
        }]
        with self.assertRaisesRegex(SdlcError, "resolution"):
            validate_spec(payload)

    def test_publish_is_fixed_json_and_markdown(self) -> None:
        fixture = ProjectFixture()
        try:
            result = publish_spec(fixture.root, spec_payload())
            self.assertTrue(result["ok"])
            markdown = (
                fixture.root / "docs/sdlc/current/requirements.md"
            ).read_text(encoding="utf-8")
            self.assertIn("# 需求规格", markdown)
            self.assertIn("## 原始输入", markdown)
            self.assertIn("## 分析与边界", markdown)
            self.assertIn("## 规范化需求", markdown)
            self.assertIn("用户确认：`true`", markdown)
            design_markdown = (
                fixture.root / "docs/sdlc/current/design.md"
            ).read_text(encoding="utf-8")
            test_markdown = (
                fixture.root / "docs/sdlc/current/test-plan.md"
            ).read_text(encoding="utf-8")
            self.assertIn("## 设计概述", design_markdown)
            self.assertIn("## 模块、接口与取舍", design_markdown)
            self.assertIn("## 测试策略与门禁", test_markdown)
            self.assertIn("## 测试用例", test_markdown)
            self.assertEqual(
                load_current_spec(fixture.root)["design"]["items"][0]["id"],
                "D-0001",
            )
        finally:
            fixture.close()

    def test_context_pack_hashes_raw_input_instead_of_repeating_it(self) -> None:
        fixture = ProjectFixture()
        try:
            payload = spec_payload()
            raw = "不应重复注入的原始需求-" * 3000
            payload["requirements"]["source_inputs"][0]["content"] = raw
            publish_spec(fixture.root, payload)
            context = build_context_pack(fixture.root, "coder")
            entries = [
                entry
                for path in context["paths"]
                for entry in json.loads(
                    (fixture.root / path).read_text(encoding="utf-8")
                )["files"]
            ]
            requirements = next(
                entry["content"]
                for entry in entries
                if entry["path"] == "docs/sdlc/current/requirements.json"
            )
            self.assertNotIn(raw, requirements)
            self.assertIn('"characters":', requirements)
            self.assertIn('"sha256":', requirements)
            self.assertIn('"id": "R-0001"', requirements)
            self.assertLess(context["repeated_chars"], len(raw))
        finally:
            fixture.close()

    def test_incremental_publish_requires_confirmation_and_parent(self) -> None:
        fixture = ProjectFixture()
        try:
            payload = spec_payload()
            payload["flow"] = "incremental"
            with self.assertRaises(SdlcError):
                publish_spec(fixture.root, payload)
            payload["incremental_confirmed"] = True
            with self.assertRaises(SdlcError):
                publish_spec(fixture.root, payload)
        finally:
            fixture.close()

    def test_historical_requirement_id_cannot_change(self) -> None:
        fixture = ProjectFixture()
        try:
            original = spec_payload()["requirements"]["items"][0]
            write_json(
                fixture.root / "docs/sdlc/versions/V0001/manifest.json",
                {
                    "status": "closed",
                    "version": "V0001",
                    "requirement_records": {
                        "R-0001": {"sha256": sha256_json(original), "supersedes": None}
                    },
                },
            )
            payload = spec_payload()
            payload["requirements"]["items"][0]["description"] = "changed"
            with self.assertRaises(SdlcError):
                publish_spec(fixture.root, payload)
        finally:
            fixture.close()

    def test_scaffold_detects_drift(self) -> None:
        fixture = ProjectFixture()
        try:
            self.assertTrue(verify_scaffold(fixture.root)["ok"])
            (fixture.root / "app.py").write_text("drift", encoding="utf-8")
            self.assertFalse(verify_scaffold(fixture.root)["ok"])
        finally:
            fixture.close()

    def test_scaffold_treats_lf_and_crlf_as_the_same_text(self) -> None:
        fixture = ProjectFixture()
        try:
            app = fixture.root / "app.py"
            app_lf = app.read_bytes().replace(b"\r\n", b"\n")
            app.write_bytes(app_lf.replace(b"\n", b"\r\n"))
            lifecycle = fixture.root / ".sdlc-pipeline" / "lifecycle.json"
            lifecycle_lf = lifecycle.read_bytes().replace(b"\r\n", b"\n")
            lifecycle.write_bytes(lifecycle_lf.replace(b"\n", b"\r\n"))
            self.assertTrue(verify_scaffold(fixture.root)["ok"])
        finally:
            fixture.close()

    def test_write_guard_rejects_protected_and_outside(self) -> None:
        fixture = ProjectFixture()
        try:
            publish_spec(fixture.root, spec_payload())
            self.assertTrue(validate_write_path(fixture.root, "src/ok.py")["ok"])
            with self.assertRaises(SdlcError):
                validate_write_path(fixture.root, "app.py")
            with self.assertRaises(SdlcError):
                validate_write_path(fixture.root, "../escape.py")
        finally:
            fixture.close()


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ProjectFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_contract_uses_argv(self) -> None:
        contract = load_contract(self.fixture.root)
        self.assertIsInstance(contract["commands"]["compile"]["argv"], list)

    def test_system_install_requires_explicit_confirmation(self) -> None:
        with self.assertRaises(SdlcError):
            install_system_tool(self.fixture.root, "python", False)
        with self.assertRaises(SdlcError):
            install_system_tool(self.fixture.root, "python", True)

    def test_init_compiles_starts_verifies_and_stops(self) -> None:
        report = init_project(self.fixture.root)
        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["compile"]["ok"])
        self.assertTrue(report["health"]["ok"])
        self.assertTrue(report["artifacts"]["ok"])
        self.assertTrue(report["stop"]["stopped"])

    def test_repeated_init_returns_existing_evidence_without_rerunning(self) -> None:
        first = init_project(self.fixture.root)
        with patch("sdlc_core.cli.init_project") as rerun:
            repeated = execute(
                self.fixture.root,
                "lifecycle",
                {"action": "init"},
            )
        rerun.assert_not_called()
        self.assertTrue(repeated["ok"])
        self.assertTrue(repeated["idempotent"])
        self.assertTrue(repeated["already_initialized"])
        self.assertEqual(repeated["report"]["created_at"], first["created_at"])

    def test_status_exposes_init_state_and_template_metadata(self) -> None:
        before = status(self.fixture.root)
        self.assertFalse(before["init_state"]["completed"])
        self.assertTrue(before["init_state"]["contracts_present"])
        self.assertEqual(
            [item["id"] for item in before["templates"]],
            ["sdlc-electron-scaffold"],
        )
        self.assertIn("capabilities", before["templates"][0])

        init_project(self.fixture.root)
        after = status(self.fixture.root)
        self.assertTrue(after["init_state"]["completed"])
        self.assertEqual(after["init_state"]["report_status"], "pass")

    def test_init_creates_project_agents_file_without_replacing_existing_rules(self) -> None:
        report = init_project(self.fixture.root)
        agents = self.fixture.root / "AGENTS.md"
        self.assertEqual(report["agents_md"]["status"], "created")
        self.assertTrue(agents.is_file())
        self.assertIn("# 项目协作说明", agents.read_text(encoding="utf-8"))

        agents.write_text("# 自定义规则\n", encoding="utf-8")
        report = init_project(self.fixture.root)
        self.assertEqual(report["agents_md"]["status"], "existing")
        self.assertEqual(agents.read_text(encoding="utf-8"), "# 自定义规则\n")

    def test_init_activates_only_rules_declared_by_selected_template(self) -> None:
        rules = self.fixture.root / ".sdlc-pipeline" / "rules"
        rules.mkdir()
        for name in ("typescript", "react", "java"):
            (rules / f"{name}.md").write_text(
                f"# {name} rules\n",
                encoding="utf-8",
            )
        write_json(
            self.fixture.root / ".sdlc-pipeline" / "templates" / "manifest.json",
            {
                "schema_version": "1.0",
                "templates": [{
                    "id": "fixture",
                    "name": "Fixture",
                    "description": "fixture template",
                    "stacks": ["typescript", "react"],
                    "rules": ["typescript", "react"],
                    "capabilities": ["fixture"],
                    "source": {
                        "kind": "git",
                        "repository": "https://example.invalid/fixture.git",
                        "ref": "main",
                    },
                }],
            },
        )

        report = init_project(self.fixture.root)
        active = json.loads(
            (rules / "active.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            [item["path"] for item in active["rules"]],
            [
                ".sdlc-pipeline/rules/typescript.md",
                ".sdlc-pipeline/rules/react.md",
            ],
        )
        self.assertEqual(report["active_rules"], active)
        self.assertNotIn("java.md", json.dumps(active))
        self.assertIn(
            "typescript.md",
            (self.fixture.root / "AGENTS.md").read_text(encoding="utf-8"),
        )

        publish_spec(self.fixture.root, spec_payload())
        context = build_context_pack(self.fixture.root, "coder")
        context_paths = {
            item["path"]
            for pack_path in context["paths"]
            for item in json.loads(
                (self.fixture.root / pack_path).read_text(encoding="utf-8")
            )["files"]
        }
        self.assertIn(".sdlc-pipeline/rules/typescript.md", context_paths)
        self.assertIn(".sdlc-pipeline/rules/react.md", context_paths)
        self.assertNotIn(".sdlc-pipeline/rules/java.md", context_paths)
        self.assertEqual(status(self.fixture.root)["active_rules"], active)

        (rules / "typescript.md").write_text("# drifted\n", encoding="utf-8")
        with self.assertRaisesRegex(SdlcError, "active rule.*hash"):
            build_context_pack(self.fixture.root, "coder")

    def test_unregistered_existing_project_uses_optional_scaffold_rules(self) -> None:
        rules = self.fixture.root / ".sdlc-pipeline" / "rules"
        rules.mkdir()
        (rules / "typescript.md").write_text(
            "# TypeScript rules\n",
            encoding="utf-8",
        )
        shutil.copytree(
            REPO / "templates",
            self.fixture.root / ".sdlc-pipeline" / "templates",
        )
        scaffold_path = self.fixture.root / ".sdlc-pipeline" / "scaffold.json"
        scaffold = json.loads(scaffold_path.read_text(encoding="utf-8"))
        scaffold["rules"] = ["typescript"]
        write_json(scaffold_path, scaffold)

        report = init_project(self.fixture.root)

        self.assertEqual(report["active_rules"]["source"], "scaffold.json")
        self.assertEqual(
            [item["id"] for item in report["active_rules"]["rules"]],
            ["typescript"],
        )

    def test_artifact_evidence_requires_every_declared_pattern(self) -> None:
        lifecycle_path = self.fixture.root / ".sdlc-pipeline/lifecycle.json"
        contract = json.loads(lifecycle_path.read_text(encoding="utf-8"))
        contract["artifacts"].append("dist/missing-artifact.bin")
        write_json(lifecycle_path, contract)
        artifact = self.fixture.root / "dist/artifact.txt"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("compiled\n", encoding="utf-8")

        evidence = artifact_evidence(self.fixture.root)

        self.assertFalse(evidence["ok"])
        self.assertEqual(evidence["missing"], ["dist/missing-artifact.bin"])

    def test_init_command_auto_installs_template_declared_missing_tools(self) -> None:
        missing = {
            "ok": False,
            "tools": [],
            "missing": ["python"],
            "install_policy": "template_declared_auto_install",
        }
        ready = {
            "ok": True,
            "tools": [],
            "missing": [],
            "install_policy": "template_declared_auto_install",
        }
        installed = {"ok": True, "tool": "python"}
        with patch(
            "sdlc_core.lifecycle.probe_tools",
            side_effect=[missing, ready],
        ), patch(
            "sdlc_core.lifecycle.install_system_tool",
            return_value=installed,
        ) as system_install:
            report = init_project(
                self.fixture.root,
                auto_install_missing=True,
            )

        system_install.assert_called_once_with(self.fixture.root, "python", True)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["system_installs"], [installed])

    def test_compile_restart_has_real_evidence(self) -> None:
        publish_spec(self.fixture.root, spec_payload())
        write_json(
            self.fixture.root / ".sdlc-pipeline/runs/coder-handoff.json",
            {
                "design_to_code": {"D-0001": ["src/feature.py"]},
                "test_to_files": {"T-0001": ["tests/test_feature.py"]},
                "changed_files": [],
                "open_issues": [],
            },
        )
        evidence = compile_restart_verify(self.fixture.root)
        self.assertTrue(evidence["compile"]["ok"])
        self.assertTrue(evidence["health"]["ok"])
        self.assertEqual(len(evidence["artifact_evidence"]["artifacts"]), 1)


class ClosedLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ProjectFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_coder_context_explicitly_excludes_test_actions(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())
        result = before_task(self.fixture.root, "coder")
        self.assertIn(
            "coder 仅可调用 sdlc_lifecycle(action=compile 或 health)",
            result["instruction"],
        )
        self.assertIn(
            "禁止调用 execute_test_plan 或 record_test_results",
            result["instruction"],
        )

    def _through_code(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())
        before_task(self.fixture.root, "coder")
        feature = self.fixture.root / "src" / "feature.py"
        test = self.fixture.root / "tests" / "test_feature.py"
        feature.write_text("def feature(): return 'ok'\n", encoding="utf-8")
        test.write_text("from src.feature import feature\nassert feature() == 'ok'\n", encoding="utf-8")
        handoff = {
            "design_to_code": {"D-0001": ["src/feature.py"]},
            "test_to_files": {"T-0001": ["tests/test_feature.py"]},
            "changed_files": ["src/feature.py", "tests/test_feature.py"],
            "open_issues": [],
            "full_scan": False,
            "full_scan_reason": None,
        }
        validate_coder_handoff(self.fixture.root, json.dumps(handoff))
        compile_restart_verify(self.fixture.root)

    def test_coder_handoff_must_match_git_diff(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())
        before_task(self.fixture.root, "coder")
        (self.fixture.root / "src" / "feature.py").write_text("x=1\n", encoding="utf-8")
        bad = {
            "design_to_code": {"D-0001": ["src/feature.py"]},
            "test_to_files": {"T-0001": ["tests/test_feature.py"]},
            "changed_files": ["made-up.py"],
            "open_issues": [],
        }
        with self.assertRaises(SdlcError):
            validate_coder_handoff(self.fixture.root, json.dumps(bad))

    def test_coder_gate_rejects_unresolved_blocking_question(self) -> None:
        init_project(self.fixture.root)
        payload = spec_payload()
        payload["requirements"]["analysis"]["open_questions"] = [{
            "id": "Q-0001",
            "question": "是否允许修改公共接口？",
            "blocking": True,
            "status": "open",
        }]
        publish_spec(self.fixture.root, payload)
        with self.assertRaisesRegex(SdlcError, "Q-0001"):
            before_task(self.fixture.root, "coder")
        write_json(
            self.fixture.root / ".sdlc-pipeline/runs/coder-handoff.json",
            {
                "design_to_code": {"D-0001": ["src/feature.py"]},
                "test_to_files": {"T-0001": ["tests/test_feature.py"]},
                "changed_files": [],
                "open_issues": [],
            },
        )
        with self.assertRaisesRegex(SdlcError, "Q-0001"):
            compile_restart_verify(self.fixture.root)
        current = status(self.fixture.root)
        self.assertEqual(current["blocking_questions"][0]["id"], "Q-0001")
        self.assertFalse(current["can_enter_next"])

    def test_executor_requires_every_tid(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())
        with self.assertRaises(SdlcError):
            validate_executor_handoff(
                self.fixture.root,
                json.dumps({"results": [], "open_issues": []}),
            )

    def test_test_gate_rejects_code_changed_after_compile(self) -> None:
        self._through_code()
        (self.fixture.root / "src" / "feature.py").write_text(
            "def feature(): return 'changed'\n", encoding="utf-8"
        )
        with self.assertRaises(SdlcError):
            run_test_plan(self.fixture.root)

    def test_test_execution_cannot_be_reused_after_test_plan_changes(self) -> None:
        self._through_code()
        execution = run_test_plan(self.fixture.root)
        executor = {
            "results": [
                {"id": item["id"], "status": item["status"], "evidence": item["log"]}
                for item in execution["results"]
            ],
            "open_issues": [],
        }
        payload = spec_payload()
        payload["test_plan"]["items"][0]["command"] = "integration"
        publish_spec(self.fixture.root, payload)
        with self.assertRaisesRegex(SdlcError, "测试执行证据.*当前 test-plan"):
            execute_tests(self.fixture.root, executor)

    def test_status_exposes_lifecycle_test_keys_and_invalidates_stale_candidate(
        self,
    ) -> None:
        self._through_code()
        execution = run_test_plan(self.fixture.root)
        executor = {
            "results": [
                {"id": item["id"], "status": item["status"], "evidence": item["log"]}
                for item in execution["results"]
            ],
            "open_issues": [],
        }
        execute_tests(self.fixture.root, executor)
        current = status(self.fixture.root)
        self.assertEqual(
            current["lifecycle_tests"]["available"],
            ["e2e", "integration", "lint", "static_analysis", "unit"],
        )
        self.assertEqual(
            current["lifecycle_tests"]["commands"]["unit"]["argv"][-1],
            "print('unit pass')",
        )
        self.assertTrue(current["gates"]["test"])

        payload = spec_payload()
        payload["test_plan"]["items"][0]["command"] = "integration"
        publish_spec(self.fixture.root, payload)
        stale = status(self.fixture.root)
        self.assertFalse(stale["gates"]["code"])
        self.assertFalse(stale["gates"]["test"])

    def test_full_init_spec_code_test_version(self) -> None:
        self._through_code()
        before_task(self.fixture.root, "executor")
        execution = run_test_plan(self.fixture.root)
        executor = {
            "results": [
                {"id": item["id"], "status": item["status"], "evidence": item["log"]}
                for item in execution["results"]
            ],
            "open_issues": [],
        }
        validate_executor_handoff(self.fixture.root, json.dumps(executor))
        results = execute_tests(self.fixture.root, executor)
        self.assertEqual(results["status"], "pass")
        record_tokens(
            self.fixture.root,
            "code",
            input_tokens=100,
            output_tokens=20,
            cache_read_tokens=50,
        )
        closed = finalize(
            self.fixture.root, results["version"], "fixture delivery", True
        )
        self.assertTrue(closed["ok"])
        self.assertEqual(
            run("git", "tag", "--list", "sdlc/V0001", cwd=self.fixture.root),
            "sdlc/V0001",
        )
        manifest = json.loads((
            self.fixture.root / "docs/sdlc/versions/V0001/manifest.json"
        ).read_text(encoding="utf-8"))
        summary = (
            self.fixture.root / "docs/sdlc/versions/V0001/summary.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(manifest["status"], "closed")
        self.assertEqual(manifest["token_usage"]["phases"]["code"]["input"], 100)
        self.assertIn("# 交付摘要 V0001", summary)
        self.assertIn("## 交付证据", summary)
        self.assertIn("`src/feature.py`", summary)
        self.assertEqual(
            run(
                "git", "ls-files", "docs/sdlc/versions/V0001/summary.md",
                cwd=self.fixture.root,
            ),
            "docs/sdlc/versions/V0001/summary.md",
        )
        final_status = status(self.fixture.root)
        self.assertEqual(final_status["current_version"], "V0001")
        self.assertEqual(final_status["stage"], "version")

    def test_incremental_needs_parent_manifest(self) -> None:
        publish_spec(self.fixture.root, spec_payload())
        eligibility = incremental_eligibility(self.fixture.root)
        self.assertFalse(eligibility["eligible"])
        self.assertIn("missing_parent_manifest", eligibility["reasons"])

    def test_trace_requires_code_and_test_mappings(self) -> None:
        publish_spec(self.fixture.root, spec_payload())
        incomplete = trace_matrix(self.fixture.root)
        self.assertFalse(incomplete["ok"])
        (self.fixture.root / "src/feature.py").write_text(
            "def feature(): return 'ok'\n", encoding="utf-8"
        )
        (self.fixture.root / "tests/test_feature.py").write_text(
            "def test_feature(): assert True\n", encoding="utf-8"
        )
        complete = trace_matrix(self.fixture.root, {
            "D-0001": ["src/feature.py"],
            "tests": {"T-0001": ["tests/test_feature.py"]},
        })
        self.assertTrue(complete["ok"])


class ReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ProjectFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_dirty_baseline_detects_second_edit_to_existing_dirty_path(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())
        feature = self.fixture.root / "src/feature.py"
        test_file = self.fixture.root / "tests/test_feature.py"
        feature.write_text("value = 'before'\n", encoding="utf-8")
        test_file.write_text("def test_feature(): assert True\n", encoding="utf-8")
        before_task(self.fixture.root, "coder")
        feature.write_text("value = 'after'\n", encoding="utf-8")
        handoff = {
            "design_to_code": {"D-0001": ["src/feature.py"]},
            "test_to_files": {"T-0001": ["tests/test_feature.py"]},
            "changed_files": ["src/feature.py"],
            "open_issues": [],
        }

        result = validate_coder_handoff(
            self.fixture.root, json.dumps(handoff)
        )

        self.assertEqual(result["diff"]["changed_paths"], ["src/feature.py"])
        self.assertEqual(
            result["diff"]["fingerprints"][0]["sha256"], sha256_file(feature)
        )

    def test_coder_retry_reuses_original_spec_baseline(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())
        first = before_task(self.fixture.root, "coder")
        feature = self.fixture.root / "src/feature.py"
        test_file = self.fixture.root / "tests/test_feature.py"
        feature.write_text("value = 'retry'\n", encoding="utf-8")
        test_file.write_text("def test_feature(): assert True\n", encoding="utf-8")

        retry = before_task(self.fixture.root, "coder")
        handoff = {
            "design_to_code": {"D-0001": ["src/feature.py"]},
            "test_to_files": {"T-0001": ["tests/test_feature.py"]},
            "changed_files": ["src/feature.py", "tests/test_feature.py"],
            "open_issues": [],
        }
        result = validate_coder_handoff(
            self.fixture.root, json.dumps(handoff)
        )

        self.assertEqual(first["baseline"], "created")
        self.assertEqual(retry["baseline"], "reused")
        self.assertEqual(
            result["diff"]["changed_paths"],
            ["src/feature.py", "tests/test_feature.py"],
        )

    def test_abandoned_attempt_is_reconciled_on_next_action(self) -> None:
        abandoned = begin_attempt(
            self.fixture.root,
            phase="code",
            step="compile",
            operation="lifecycle",
            payload={"action": "compile"},
        )
        path = (
            self.fixture.root
            / ".sdlc-pipeline/runs/journal"
            / abandoned["run_id"]
            / "attempts/code"
            / f"{abandoned['attempt_id']}.json"
        )
        value = json.loads(path.read_text(encoding="utf-8"))
        value["owner"] = {
            "pid": 4242,
            "process_identity": {
                "scheme": "windows-filetime",
                "created": "gone",
            },
        }
        write_json(path, value)

        next_attempt = begin_attempt(
            self.fixture.root,
            phase="code",
            step="health",
            operation="lifecycle",
            payload={"action": "health"},
        )

        recovered = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(recovered["state"], "aborted")
        self.assertEqual(next_attempt["attempt_id"], "A000002")

    def test_handoff_rejects_nonexistent_mapping_path(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())
        before_task(self.fixture.root, "coder")
        feature = self.fixture.root / "src/feature.py"
        test_file = self.fixture.root / "tests/test_feature.py"
        feature.write_text("value = 1\n", encoding="utf-8")
        test_file.write_text("def test_feature(): assert True\n", encoding="utf-8")
        handoff = {
            "design_to_code": {"D-0001": ["src/fake.py"]},
            "test_to_files": {"T-0001": ["tests/test_feature.py"]},
            "changed_files": ["src/feature.py", "tests/test_feature.py"],
            "open_issues": [],
        }
        with self.assertRaisesRegex(SdlcError, "文件不存在"):
            validate_coder_handoff(self.fixture.root, json.dumps(handoff))

    def test_spec_bundle_is_authoritative_and_repairs_current_mirror(self) -> None:
        published = publish_spec(self.fixture.root, spec_payload())
        pointer = json.loads(
            (self.fixture.root / "docs/sdlc/spec-current.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(pointer["bundle_id"], published["bundle_id"])
        mirror = self.fixture.root / "docs/sdlc/current/requirements.json"
        mirror.write_text("corrupt", encoding="utf-8")

        loaded = load_current_spec(self.fixture.root)

        self.assertEqual(loaded["requirements"]["items"][0]["id"], "R-0001")
        self.assertEqual(json.loads(mirror.read_text(encoding="utf-8"))["items"][0]["id"], "R-0001")

    def test_schema_rejects_unknown_top_level_property(self) -> None:
        payload = spec_payload()
        payload["unexpected"] = True
        with self.assertRaisesRegex(SdlcError, "不允许的字段"):
            validate_spec(payload, self.fixture.root)

    def test_source_envelope_and_spec_11_anchor_trace(self) -> None:
        ingested = ingest_source(self.fixture.root, {
            "kind": "inline",
            "source": "用户需求.md",
            "media_type": "text/markdown",
            "content": "用户必须能够保存设置。",
            "segments": [{"anchor": "p:1", "text": "用户必须能够保存设置。"}],
        })["envelope"]
        ref = f"{ingested['source_id']}#p:1"
        payload = spec_payload()
        payload["schema_version"] = "1.1"
        payload["requirements"]["source_inputs"] = [ingested]
        requirement = payload["requirements"]["items"][0]
        requirement["source_refs"] = [ref]
        requirement["acceptance_criteria"] = [{
            "id": "AC-R-0001-01",
            "description": "设置可以持久化保存",
            "source_refs": [ref],
        }]

        result = publish_spec(self.fixture.root, payload)

        self.assertTrue(result["ok"])
        markdown = (
            self.fixture.root / "docs/sdlc/current/requirements.md"
        ).read_text(encoding="utf-8")
        self.assertIn("AC-R-0001-01", markdown)
        self.assertIn(ingested["source_id"], markdown)

    def test_journal_idempotency_and_spec_checkpoint_resume(self) -> None:
        payload = {
            "kind": "spec",
            "payload": spec_payload(),
            "idempotency_key": "publish-spec-0001",
        }
        first = execute(self.fixture.root, "publish", payload)
        second = execute(self.fixture.root, "publish", payload)
        self.assertEqual(first["bundle_id"], second["bundle_id"])
        self.assertEqual(journal_status(self.fixture.root)["attempt_count"], 1)

        execute(self.fixture.root, "publish", {
            "kind": "checkpoint",
            "payload": {
                "state": "interviewing",
                "question": {
                    "id": "Q-0001",
                    "prompt": "是否需要离线支持？",
                    "answer": "需要",
                    "status": "resolved",
                    "rationale": "现场网络不稳定",
                },
            },
        })
        current = status(self.fixture.root)
        self.assertEqual(
            current["spec_checkpoint"]["decisions"][0]["answer"], "需要"
        )
        self.assertEqual(journal_status(self.fixture.root)["phase"], "spec")

    def test_hard_policy_produces_machine_violation(self) -> None:
        rules = self.fixture.root / ".sdlc-pipeline/rules"
        rules.mkdir(exist_ok=True)
        shutil.copy2(REPO / "rules/typescript.md", rules / "typescript.md")
        shutil.copy2(
            REPO / "rules/typescript.policy.json",
            rules / "typescript.policy.json",
        )
        write_json(rules / "active.json", {
            "schema_version": "1.0",
            "template_id": "fixture",
            "source": "test",
            "rules": [{
                "id": "typescript",
                "path": ".sdlc-pipeline/rules/typescript.md",
                "sha256": sha256_file(rules / "typescript.md"),
                "policy_path": ".sdlc-pipeline/rules/typescript.policy.json",
                "policy_sha256": sha256_file(rules / "typescript.policy.json"),
                "classification": ["guidance", "hard", "executable"],
            }],
        })
        (self.fixture.root / "src/unsafe.ts").write_text(
            "const value: any = 1\n", encoding="utf-8"
        )
        report = evaluate_hard_policies(self.fixture.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["violations"][0]["policy"], "typescript:no-explicit-any")

    def test_pid_identity_mismatch_refuses_to_kill(self) -> None:
        path = self.fixture.root / ".sdlc-pipeline/runs/active.json"
        write_json(path, {
            "pid": 4242,
            "process_identity": {
                "scheme": "windows-filetime",
                "created": "recorded",
            },
        })
        with (
            patch("sdlc_core.runs.pid_alive", return_value=True),
            patch(
                "sdlc_core.runs.process_identity",
                return_value={
                    "scheme": "windows-filetime",
                    "created": "reused",
                },
            ),
            patch("sdlc_core.runs.subprocess.run") as taskkill,
        ):
            with self.assertRaisesRegex(SdlcError, "创建身份不匹配"):
                stop_active(self.fixture.root)
        taskkill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
