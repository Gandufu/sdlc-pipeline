from __future__ import annotations

import json
import io
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from sdlc_core.adapter import (  # noqa: E402
    after_task,
    before_task,
    build_context_pack,
    validate_coder_handoff,
    validate_write_path,
)
from sdlc_core.artifacts import load_current_spec, load_test_results  # noqa: E402
from sdlc_core.common import (  # noqa: E402
    SdlcError,
    read_json,
    run_command,
    sha256_contract_file,
    sha256_file,
    write_json,
)
from sdlc_core.common import sha256_json  # noqa: E402
from sdlc_core.records import read_markdown_record  # noqa: E402
from sdlc_core.stores import write_evidence_record, write_work_record  # noqa: E402
from sdlc_core.cli import execute  # noqa: E402
from sdlc_core.lifecycle import (  # noqa: E402
    artifact_evidence,
    compile_restart_verify,
    execute_tests,
    init_project,
    install_system_tool,
    load_contract,
    run_test_plan,
    verify_delivery,
)
from sdlc_core.journal import begin_attempt, finish_attempt, journal_status  # noqa: E402
from sdlc_core.policies import evaluate_hard_policies  # noqa: E402
from sdlc_core.runs import (  # noqa: E402
    clear_active,
    pid_alive,
    read_active,
    record_active,
    record_tokens,
    stop_active,
)
from sdlc_core.sources import (  # noqa: E402
    MAX_SOURCE_SEGMENT_CHARS,
    ingest_source,
    query_source,
)
from sdlc_core.spec_candidates import (  # noqa: E402
    begin_candidate,
    put_design,
    put_requirement,
    put_verification,
    validate_candidate,
)
from sdlc_core.spec_publisher import approve_and_promote  # noqa: E402
from sdlc_core.status import status  # noqa: E402
from sdlc_core.trace import (  # noqa: E402
    verify_scaffold,
)
from sdlc_core.versions import finalize, parent_manifest  # noqa: E402


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
            "level": "functional",
            "preconditions": "已编译并运行",
            "input": "执行 functional",
            "expected": "退出码为 0",
            "mandatory": True,
            "command": "functional",
            "selector": "tests/functional/T-0001.functional.ts",
        }]},
    }


def publish_spec(root: Path, blueprint: dict) -> dict:
    """Publish the compact fixture through the Storage Layout v3 public seams."""
    source_input = blueprint["requirements"]["source_inputs"][0]
    if source_input.get("source_id"):
        source = source_input
    else:
        source = ingest_source(root, {
            "kind": "inline",
            "source": source_input.get("source", "test fixture"),
            "content": source_input["content"],
        })
    source_ref = {
        "source_id": source["source_id"],
        "anchor": source["anchors"][0]["anchor"],
    }
    created = begin_candidate(
        root,
        title=blueprint["requirements"]["items"][0]["title"],
        source_refs=[source_ref],
    )
    acceptance_by_requirement: dict[str, list[str]] = {}
    for requirement in blueprint["requirements"]["items"]:
        criteria = []
        for index, criterion in enumerate(requirement["acceptance_criteria"], 1):
            if isinstance(criterion, dict):
                description = criterion.get("description", "")
                identifier = criterion.get("id")
            else:
                description = str(criterion)
                identifier = None
            criteria.append({
                **({"id": identifier} if identifier else {}),
                "given": "前置条件满足",
                "when": "执行功能",
                "then": description,
                "source_refs": [source_ref],
            })
        put_requirement(
            root,
            created["candidate_id"],
            {
                "id": requirement["id"],
                "feature_id": "F-0001",
                "title": requirement["title"],
                "goal": requirement["description"],
                "actor": "用户",
                "scope": blueprint["requirements"]["analysis"]["impact_scope"],
                "non_goals": [],
                "source_refs": [source_ref],
                "main_flow": ["执行功能", "观察结果"],
                "alternate_flows": [],
                "acceptance_criteria": criteria,
                "supersedes": requirement.get("supersedes"),
            },
        )
        acceptance_by_requirement[requirement["id"]] = [
            f"AC-{requirement['id']}-{index:02d}"
            for index in range(1, len(criteria) + 1)
        ]
    for design in blueprint["design"]["items"]:
        put_design(
            root,
            created["candidate_id"],
            {
                "id": design["id"],
                "title": design["title"],
                "requirement_ids": design["requirement_ids"],
                "modules": [{
                    "name": design["module"],
                    "responsibility": design["description"],
                    "seam": design["extension_point"],
                }],
                "interfaces": [],
                "data_contracts": [],
                "extension_points": [design["extension_point"]],
                "decisions": blueprint["requirements"]["analysis"]["decisions"],
            },
        )
    for test in blueprint["test_plan"]["items"]:
        put_verification(
            root,
            created["candidate_id"],
            {
                "id": test["id"],
                "requirement_ids": test["requirement_ids"],
                "design_ids": test["design_ids"],
                "acceptance_criteria_ids": sorted({
                    identifier
                    for requirement_id in test["requirement_ids"]
                    for identifier in acceptance_by_requirement[requirement_id]
                }),
                "level": test["level"],
                "test_key": test["command"],
                "selector": test["selector"],
                "preconditions": test["preconditions"],
                "expected": test["expected"],
                "mandatory": test["mandatory"],
            },
        )
    ready = validate_candidate(root, created["candidate_id"])
    return approve_and_promote(
        root,
        candidate_id=created["candidate_id"],
        content_hash=ready["content_hash"],
        confirmed=True,
    )


class ProjectFixture:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.port = free_port()
        (self.root / ".sdlc-pipeline" / "contracts").mkdir(parents=True)
        (self.root / ".sdlc-pipeline" / "runtime" / "templates").mkdir(parents=True)
        (self.root / ".sdlc-pipeline" / "runtime" / "rules").mkdir(parents=True)
        shutil.copy2(
            REPO / "templates" / "manifest.json",
            self.root
            / ".sdlc-pipeline"
            / "runtime"
            / "templates"
            / "manifest.json",
        )
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "tests" / "functional").mkdir()
        (self.root / ".sdlc-pipeline" / ".gitignore").write_text(
            "state/\nwork/\nevidence/\n", encoding="utf-8"
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
                "package": command("print('packaged')"),
                "start": {
                    "argv": ["${PYTHON}", "app.py"],
                    "timeout_seconds": 30,
                    "startup_grace_seconds": 0.5,
                    "background": True,
                },
                "lint": command("print('lint pass')"),
                "typecheck": command("print('typecheck pass')"),
            },
            "health": [
                {"type": "process", "timeout_seconds": 5},
                {
                    "type": "http",
                    "url": f"http://127.0.0.1:{self.port}",
                    "contains": "ok",
                    "timeout_seconds": 5,
                },
                {"type": "file", "path": "dist/artifact.txt", "timeout_seconds": 5},
            ],
            "artifacts": ["dist/artifact.txt"],
            "tests": {
                "functional": {
                    **command("print('functional pass')"),
                    "allow_selector": True,
                },
            },
        }
        lifecycle_path = (
            self.root / ".sdlc-pipeline" / "contracts" / "lifecycle.json"
        )
        write_json(lifecycle_path, lifecycle)
        scaffold = {
            "schema_version": "1.0",
            "template_id": "fixture",
            "template_version": "1.0.0",
            "key_files": [{
                "path": "app.py",
                "sha256": sha256_contract_file(self.root / "app.py"),
            }],
            "protected_paths": [
                ".sdlc-pipeline/contracts/lifecycle.json",
                ".sdlc-pipeline/contracts/scaffold.json",
                "app.py",
            ],
            "extension_points": [{"id": "feature", "path": "src"}],
            "allowed_paths": ["src", "tests"],
            "lifecycle_hash": sha256_contract_file(
                lifecycle_path
            ),
            "capabilities": ["fixture"],
        }
        write_json(
            self.root / ".sdlc-pipeline" / "contracts" / "scaffold.json",
            scaffold,
        )
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

    def use_lifecycle_v11(self, *, preflight_code: str = "print('preflight pass')") -> None:
        """Install a v1.1 contract before init and bind it into the fixture scaffold."""
        (self.root / "tests" / "unit").mkdir(exist_ok=True)
        lifecycle_path = (
            self.root / ".sdlc-pipeline" / "contracts" / "lifecycle.json"
        )
        lifecycle = read_json(lifecycle_path)
        command = lambda code: {  # noqa: E731
            "argv": ["${PYTHON}", "-c", code], "timeout_seconds": 30
        }
        lifecycle["schema_version"] = "1.1"
        lifecycle["test_preflight"] = [command(preflight_code)]
        lifecycle["tests"]["unit"] = {
            **command("print('unit pass')"),
            "allow_selector": True,
            "requires_runtime": False,
            "selector_patterns": ["tests/unit/*.unit.py"],
        }
        lifecycle["tests"]["functional"].update({
            "requires_runtime": True,
            "selector_patterns": ["tests/functional/*.functional.ts"],
        })
        write_json(lifecycle_path, lifecycle)
        scaffold_path = (
            self.root / ".sdlc-pipeline" / "contracts" / "scaffold.json"
        )
        scaffold = read_json(scaffold_path)
        scaffold["lifecycle_hash"] = sha256_contract_file(lifecycle_path)
        write_json(scaffold_path, scaffold)
        run("git", "add", "-A", cwd=self.root)
        run("git", "commit", "-qm", "lifecycle v1.1", cwd=self.root)


class SchemaAndTraceTests(unittest.TestCase):
    def test_publish_rejects_shell_command_instead_of_lifecycle_test_key(self) -> None:
        fixture = ProjectFixture()
        try:
            payload = spec_payload()
            payload["test_plan"]["items"][0]["command"] = "pnpm test"
            with self.assertRaisesRegex(
                SdlcError,
                r"未知 lifecycle test_key",
            ):
                publish_spec(fixture.root, payload)
            self.assertFalse(
                (fixture.root / "docs/sdlc/current.json").exists()
            )
        finally:
            fixture.close()

    def test_v11_publishes_unit_verification_for_declared_selector(self) -> None:
        fixture = ProjectFixture()
        try:
            fixture.use_lifecycle_v11()
            payload = spec_payload()
            payload["test_plan"]["items"][0].update({
                "level": "unit",
                "preconditions": "已编译",
                "input": "执行 unit",
                "command": "unit",
                "selector": "tests/unit/T-0001.unit.py",
            })

            result = publish_spec(fixture.root, payload)

            self.assertTrue(result["ok"])
            self.assertEqual(
                load_current_spec(fixture.root)["test_plan"]["items"][0]["selector"],
                "tests/unit/T-0001.unit.py",
            )
        finally:
            fixture.close()

    def test_publish_contains_only_v3_markdown_baseline(self) -> None:
        fixture = ProjectFixture()
        try:
            result = publish_spec(fixture.root, spec_payload())
            self.assertTrue(result["ok"])
            bundle = fixture.root / "docs/sdlc/baselines" / result["baseline_id"]
            self.assertTrue((bundle / "manifest.json").is_file())
            self.assertTrue((bundle / "requirements/R-0001.md").is_file())
            self.assertTrue((bundle / "designs/D-0001.md").is_file())
            self.assertTrue((bundle / "verification/T-0001.md").is_file())
            if os.name == "nt":
                acl = subprocess.run(
                    ["icacls", str(bundle)],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                self.assertEqual(acl.returncode, 0, acl.stderr)
                self.assertIn("(I)", acl.stdout)
            for obsolete in (
                "feature-contract.json", "requirements.json",
                "design.json", "test-plan.json",
            ):
                self.assertFalse((bundle / obsolete).exists())
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
            pack = read_markdown_record(fixture.root / context["paths"][0])
            encoded = json.dumps(pack, ensure_ascii=False)
            requirements = next(
                entry for entry in pack["resources"]
                if entry["path"].endswith("/requirements/R-0001.md")
            )
            self.assertNotIn(raw, encoded)
            self.assertEqual(len(requirements["sha256"]), 64)
            self.assertEqual(pack["brief"]["requirement_ids"], ["R-0001"])
            self.assertEqual(context["repeated_chars"], 0)
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
            lifecycle = (
                fixture.root / ".sdlc-pipeline/contracts/lifecycle.json"
            )
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
        self.assertIsInstance(contract["commands"]["package"]["argv"], list)

    def test_system_install_requires_explicit_confirmation(self) -> None:
        with self.assertRaises(SdlcError):
            install_system_tool(self.fixture.root, "python", False)
        with self.assertRaises(SdlcError):
            install_system_tool(self.fixture.root, "python", True)

    def test_init_compiles_starts_verifies_and_stops(self) -> None:
        report = init_project(self.fixture.root)
        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["compile"]["ok"])
        self.assertTrue(report["package"]["ok"])
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
        rules = self.fixture.root / ".sdlc-pipeline" / "runtime" / "rules"
        rules.mkdir(exist_ok=True)
        for name in ("typescript", "react", "java"):
            (rules / f"{name}.md").write_text(
                f"# {name} rules\n",
                encoding="utf-8",
            )
        write_json(
            self.fixture.root
            / ".sdlc-pipeline"
            / "runtime"
            / "templates"
            / "manifest.json",
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
            (
                self.fixture.root
                / ".sdlc-pipeline/contracts/active-rules.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            [item["path"] for item in active["rules"]],
            [
                ".sdlc-pipeline/runtime/rules/typescript.md",
                ".sdlc-pipeline/runtime/rules/react.md",
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
            for item in read_markdown_record(
                self.fixture.root / pack_path
            )["resources"]
        }
        self.assertIn(".sdlc-pipeline/runtime/rules/typescript.md", context_paths)
        self.assertIn(".sdlc-pipeline/runtime/rules/react.md", context_paths)
        self.assertNotIn(".sdlc-pipeline/runtime/rules/java.md", context_paths)
        self.assertEqual(status(self.fixture.root)["active_rules"], active)

        (rules / "typescript.md").write_text("# drifted\n", encoding="utf-8")
        with self.assertRaisesRegex(SdlcError, "active rule.*hash"):
            build_context_pack(self.fixture.root, "coder")

    def test_unregistered_existing_project_uses_optional_scaffold_rules(self) -> None:
        rules = self.fixture.root / ".sdlc-pipeline" / "runtime" / "rules"
        rules.mkdir(exist_ok=True)
        (rules / "typescript.md").write_text(
            "# TypeScript rules\n",
            encoding="utf-8",
        )
        shutil.copytree(
            REPO / "templates",
            self.fixture.root / ".sdlc-pipeline" / "runtime" / "templates",
            dirs_exist_ok=True,
        )
        scaffold_path = (
            self.fixture.root
            / ".sdlc-pipeline"
            / "contracts"
            / "scaffold.json"
        )
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
        lifecycle_path = (
            self.fixture.root
            / ".sdlc-pipeline/contracts/lifecycle.json"
        )
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

    def test_code_gate_has_compile_policy_and_artifact_evidence(self) -> None:
        publish_spec(self.fixture.root, spec_payload())
        write_work_record(
            self.fixture.root,
            "coder-handoff",
            {
                "summary": "fixture",
                "open_issues": [],
            },
            state="validated",
        )
        evidence = compile_restart_verify(self.fixture.root)
        self.assertTrue(evidence["compile"]["ok"])
        self.assertTrue(evidence["package"]["ok"])
        self.assertTrue(evidence["policy"]["ok"])
        self.assertEqual(len(evidence["artifact_evidence"]["artifacts"]), 1)
        self.assertTrue(evidence["start"]["pid"])
        self.assertTrue(evidence["health"]["ok"])
        self.assertTrue(evidence["preview"]["running"])
        self.assertEqual(
            evidence["preview"]["access_url"],
            f"http://127.0.0.1:{self.fixture.port}",
        )
        self.assertTrue(read_active(self.fixture.root))


class ClosedLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ProjectFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_coder_context_excludes_test_sources_and_verification(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())
        result = before_task(self.fixture.root, "coder")
        manifest = read_markdown_record(
            self.fixture.root / result["context_pack"]["paths"][0]
        )
        self.assertNotIn("test_ids", manifest["brief"])
        self.assertNotIn("verification", manifest["brief"])
        self.assertNotIn("tests", manifest["brief"]["allowed_paths"])
        self.assertFalse(any(
            item["reason"] == "authoritative Verification"
            or item["path"].startswith("tests/")
            for item in manifest["resources"]
        ))
        self.assertIn("只实现业务代码", result["instruction"])

    def test_coder_write_guard_rejects_test_sources(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())
        execute(self.fixture.root, "task-before", {
            "role": "coder",
            "owner_pid": os.getpid(),
        })

        with self.assertRaisesRegex(SdlcError, "coder 禁止修改测试脚本"):
            execute(self.fixture.root, "write-check", {
                "path": "tests/functional/feature.functional.ts",
                "owner_pid": os.getpid(),
            })

    def _through_code(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())
        before_task(self.fixture.root, "coder")
        feature = self.fixture.root / "src" / "feature.py"
        feature.write_text("def feature(): return 'ok'\n", encoding="utf-8")
        handoff = {
            "summary": "fixture implementation",
            "open_issues": [],
            "full_scan": False,
            "full_scan_reason": None,
        }
        validate_coder_handoff(self.fixture.root, json.dumps(handoff))
        compile_restart_verify(self.fixture.root)

    def _author_tests(self) -> None:
        (self.fixture.root / "tests" / "functional" / "T-0001.functional.ts").write_text(
            "from src.feature import feature\nassert feature() == 'ok'\n",
            encoding="utf-8",
        )

    def _through_tester(self) -> None:
        before_task(self.fixture.root, "tester")
        self._author_tests()
        after_task(
            self.fixture.root,
            "tester",
            json.dumps({"summary": "测试脚本已准备", "open_issues": []}),
        )

    def test_declared_test_script_can_be_added_after_code_gate(self) -> None:
        self._through_code()
        self._through_tester()

        self.assertTrue(status(self.fixture.root)["gates"]["code"])
        delivery = verify_delivery(self.fixture.root)

        self.assertTrue(delivery["ok"])
        self.assertTrue(delivery["runtime_reset"]["preview_stop"]["stopped"])
        self.assertTrue(delivery["runtime_reset"]["port_release"]["ok"])
        self.assertTrue(delivery["runtime_reset"]["test_start"]["ok"])
        self.assertTrue(delivery["runtime_reset"]["test_health"]["ok"])
        self.assertTrue(delivery["cleanup"]["port_release"]["ok"])
        self.assertIn(
            "test_source_fingerprint",
            delivery["binding"],
        )

    def test_test_stage_rejects_undeclared_test_script(self) -> None:
        self._through_code()
        self._through_tester()
        (self.fixture.root / "tests" / "extra_test.py").write_text(
            "assert True\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            SdlcError,
            "只允许修改 Spec 声明的测试脚本",
        ):
            verify_delivery(self.fixture.root)

    def test_tester_subagent_context_and_handoff_are_test_only(self) -> None:
        self._through_code()
        dispatched = before_task(self.fixture.root, "tester")
        manifest = read_markdown_record(
            self.fixture.root / dispatched["context_pack"]["paths"][0]
        )
        self.assertEqual(manifest["role"], "tester")
        self.assertEqual(manifest["brief"]["test_ids"], ["T-0001"])
        self.assertEqual(
            manifest["brief"]["allowed_paths"],
            ["tests/functional/T-0001.functional.ts"],
        )
        self._author_tests()

        handoff = after_task(
            self.fixture.root,
            "tester",
            json.dumps({"summary": "Playwright 脚本已准备", "open_issues": []}),
        )

        self.assertEqual(
            handoff["handoff"]["changed_files"],
            ["tests/functional/T-0001.functional.ts"],
        )

    def test_tester_write_guard_rejects_business_source(self) -> None:
        self._through_code()
        execute(self.fixture.root, "task-before", {
            "role": "tester",
            "owner_pid": os.getpid(),
        })

        checked = execute(self.fixture.root, "write-check", {
            "path": "tests/functional/T-0001.functional.ts",
            "owner_pid": os.getpid(),
        })
        self.assertEqual(checked["role"], "tester")
        with self.assertRaisesRegex(
            SdlcError,
            "tester 只能修改 Spec 声明的测试脚本",
        ):
            execute(self.fixture.root, "write-check", {
                "path": "src/feature.py",
                "owner_pid": os.getpid(),
            })

    def test_coder_handoff_changed_files_are_derived_from_git_diff(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())
        before_task(self.fixture.root, "coder")
        (self.fixture.root / "src" / "feature.py").write_text("x=1\n", encoding="utf-8")
        bad = {
            "summary": "fixture implementation",
            "open_issues": [],
        }
        result = validate_coder_handoff(self.fixture.root, json.dumps(bad))
        self.assertEqual(result["handoff"]["changed_files"], ["src/feature.py"])

    def test_coder_handoff_rejects_empty_change_set(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())
        before_task(self.fixture.root, "coder")

        with self.assertRaisesRegex(SdlcError, "未产生允许的业务改动"):
            validate_coder_handoff(self.fixture.root, json.dumps({
                "summary": "仅完成分析，尚未实现",
                "open_issues": ["尚未开始编码"],
            }))

        self.assertFalse(
            (
                self.fixture.root
                / ".sdlc-pipeline/state/records/coder-handoff.json"
            ).exists()
        )

    def test_task_cancel_is_exposed_by_cli_and_aborts_coder_attempt(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())
        execute(self.fixture.root, "task-before", {
            "role": "coder",
            "owner_pid": os.getpid(),
        })

        result = subprocess.run(
            [
                sys.executable,
                str(REPO / "scripts/sdlc.py"),
                "task-cancel",
                "--root",
                str(self.fixture.root),
            ],
            input=json.dumps({"reason": "regression cancellation"}),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["cancelled"])
        self.assertEqual(journal_status(self.fixture.root)["running_attempts"], [])

    def test_test_gate_rejects_code_changed_after_compile(self) -> None:
        self._through_code()
        (self.fixture.root / "src" / "feature.py").write_text(
            "def feature(): return 'changed'\n", encoding="utf-8"
        )
        with self.assertRaises(SdlcError):
            run_test_plan(self.fixture.root)

    def test_test_execution_cannot_be_reused_after_test_plan_changes(self) -> None:
        self._through_code()
        self._author_tests()
        execution = run_test_plan(self.fixture.root)
        payload = spec_payload()
        payload["test_plan"]["items"][0]["expected"] = "更新后的退出码为 0"
        publish_spec(self.fixture.root, payload)
        with self.assertRaisesRegex(SdlcError, "测试执行证据.*当前 test-plan"):
            execute_tests(self.fixture.root)

    def test_delivery_executes_shared_selector_once(self) -> None:
        from copy import deepcopy

        init_project(self.fixture.root)
        payload = spec_payload()
        second = deepcopy(payload["test_plan"]["items"][0])
        second["id"] = "T-0002"
        payload["test_plan"]["items"].append(second)
        publish_spec(self.fixture.root, payload)
        before_task(self.fixture.root, "coder")
        (self.fixture.root / "src" / "feature.py").write_text(
            "def feature(): return 'ok'\n",
            encoding="utf-8",
        )
        validate_coder_handoff(
            self.fixture.root,
            json.dumps({"summary": "fixture", "open_issues": []}),
        )
        compile_restart_verify(self.fixture.root)
        (self.fixture.root / "tests" / "functional" / "T-0001.functional.ts").write_text(
            "from src.feature import feature\nassert feature() == 'ok'\n",
            encoding="utf-8",
        )

        execution = run_test_plan(self.fixture.root)

        self.assertEqual(len(execution["results"]), 2)
        self.assertEqual(
            execution["results"][0]["log"],
            execution["results"][1]["log"],
        )
        self.assertEqual(
            execution["results"][1]["reused_execution_from"],
            "T-0001",
        )

    def test_status_exposes_lifecycle_test_keys_and_invalidates_stale_candidate(
        self,
    ) -> None:
        self._through_code()
        self._author_tests()
        execution = run_test_plan(self.fixture.root)
        execute_tests(self.fixture.root)
        current = status(self.fixture.root)
        self.assertTrue(current["preview"]["running"])
        self.assertEqual(
            current["preview"]["access_url"],
            f"http://127.0.0.1:{self.fixture.port}",
        )
        self.assertEqual(
            current["lifecycle_tests"]["available"],
            ["functional"],
        )
        self.assertEqual(
            current["lifecycle_tests"]["commands"]["functional"]["argv"][-1],
            "print('functional pass')",
        )
        self.assertTrue(current["gates"]["test"])

        payload = spec_payload()
        payload["test_plan"]["items"][0]["expected"] = "更新后的退出码为 0"
        publish_spec(self.fixture.root, payload)
        stale = status(self.fixture.root)
        self.assertFalse(stale["gates"]["code"])
        self.assertFalse(stale["gates"]["test"])

    def test_full_init_spec_code_test_version(self) -> None:
        self._through_code()
        self._through_tester()
        delivery = verify_delivery(self.fixture.root)
        results = load_test_results(self.fixture.root, delivery["test_results"])
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
        manifest = parent_manifest(self.fixture.root)
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

    def test_verify_delivery_reuses_success_for_same_fingerprint(self) -> None:
        self._through_code()
        self._through_tester()
        first = verify_delivery(self.fixture.root)
        second = verify_delivery(self.fixture.root)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["version"], second["version"])

    def test_verify_delivery_does_not_reuse_failed_evidence(self) -> None:
        self._through_code()
        self._through_tester()
        first = verify_delivery(self.fixture.root)
        failed = {**first, "ok": False}
        write_evidence_record(
            self.fixture.root,
            "delivery",
            failed,
            state="failed",
            title="Failed delivery evidence",
        )

        second = verify_delivery(self.fixture.root)

        self.assertFalse(second["cached"])
        self.assertTrue(second["ok"])

    def test_v11_unit_preflight_runs_before_runtime_and_skips_runtime(self) -> None:
        self.fixture.use_lifecycle_v11()
        init_project(self.fixture.root)
        payload = spec_payload()
        payload["test_plan"]["items"][0].update({
            "level": "unit",
            "preconditions": "已编译",
            "input": "执行 unit",
            "command": "unit",
            "selector": "tests/unit/T-0001.unit.py",
        })
        publish_spec(self.fixture.root, payload)
        before_task(self.fixture.root, "coder")
        (self.fixture.root / "src" / "feature.py").write_text(
            "def feature(): return 'ok'\n", encoding="utf-8"
        )
        validate_coder_handoff(self.fixture.root, json.dumps({
            "summary": "fixture implementation", "open_issues": [],
        }))
        compile_restart_verify(self.fixture.root)
        before_task(self.fixture.root, "tester")
        (self.fixture.root / "tests" / "unit" / "T-0001.unit.py").write_text(
            "from src.feature import feature\nassert feature() == 'ok'\n",
            encoding="utf-8",
        )
        after_task(self.fixture.root, "tester", json.dumps({
            "summary": "unit test ready", "open_issues": [],
        }))

        with patch("sdlc_core.lifecycle.start") as start_runtime:
            delivery = verify_delivery(self.fixture.root)

        self.assertTrue(delivery["ok"])
        self.assertFalse(delivery["runtime_reset"]["required"])
        self.assertTrue(delivery["runtime_reset"]["test_start"]["skipped"])
        self.assertEqual(len(delivery["preflight"]["commands"]), 1)
        start_runtime.assert_not_called()

class ReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ProjectFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_dirty_baseline_detects_second_edit_to_existing_dirty_path(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())
        feature = self.fixture.root / "src/feature.py"
        test_file = self.fixture.root / "tests/functional/T-0001.functional.ts"
        feature.write_text("value = 'before'\n", encoding="utf-8")
        test_file.write_text("def test_feature(): assert True\n", encoding="utf-8")
        before_task(self.fixture.root, "coder")
        feature.write_text("value = 'after'\n", encoding="utf-8")
        handoff = {
            "summary": "fixture implementation",
            "open_issues": [],
        }

        result = validate_coder_handoff(
            self.fixture.root, json.dumps(handoff)
        )

        self.assertEqual(result["diff"]["changed_paths"], ["src/feature.py"])
        self.assertEqual(
            result["diff"]["fingerprints"][0]["sha256"], sha256_file(feature)
        )

    def test_cli_unexpected_exception_uses_structured_error_envelope(self) -> None:
        from sdlc_core import cli

        with patch("sdlc_core.cli.execute", side_effect=RuntimeError("boom")), patch(
            "sys.argv", ["sdlc.py", "status", "--root", str(self.fixture.root)]
        ), patch("sys.stdin", io.StringIO("{}")), patch("sys.stdout", io.StringIO()) as stdout:
            exit_code = cli.main()

        response = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(response["ok"], False)
        self.assertEqual(response["error_type"], "RuntimeError")
        self.assertEqual(response["error"], "boom")

    def test_coder_retry_reuses_original_spec_baseline(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())
        first = before_task(self.fixture.root, "coder")
        feature = self.fixture.root / "src/feature.py"
        feature.write_text("value = 'retry'\n", encoding="utf-8")

        retry = before_task(self.fixture.root, "coder")
        handoff = {
            "summary": "fixture implementation",
            "open_issues": [],
        }
        result = validate_coder_handoff(
            self.fixture.root, json.dumps(handoff)
        )

        self.assertEqual(first["baseline"], "created")
        self.assertEqual(retry["baseline"], "reused")
        self.assertEqual(
            result["diff"]["changed_paths"],
            ["src/feature.py"],
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
            / ".sdlc-pipeline/state/runs"
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

    def test_failed_test_run_can_reenter_code_for_explicit_rework(self) -> None:
        failed = begin_attempt(
            self.fixture.root,
            phase="test",
            step="verify_delivery",
            operation="lifecycle",
            payload={"action": "verify_delivery"},
        )
        finish_attempt(
            self.fixture.root,
            failed,
            state="failed",
            error="functional assertion failed",
        )

        rework = begin_attempt(
            self.fixture.root,
            phase="code",
            step="compile_restart_verify",
            operation="lifecycle",
            payload={"action": "compile_restart_verify"},
        )

        current = journal_status(self.fixture.root)
        self.assertEqual(rework["phase"], "code")
        self.assertEqual(current["phase"], "code")
        self.assertEqual(current["state"], "running")
        self.assertEqual(current["last_failure"]["repeat_count"], 1)

    def test_status_reconciles_abandoned_attempt_without_next_action(self) -> None:
        abandoned = begin_attempt(
            self.fixture.root,
            phase="code",
            step="coder-dispatch",
            operation="task-before",
            payload={"role": "coder"},
        )
        path = (
            self.fixture.root
            / ".sdlc-pipeline/state/runs"
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

        current = journal_status(self.fixture.root)

        recovered = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(recovered["state"], "aborted")
        self.assertEqual(current["state"], "aborted")
        self.assertEqual(current["running_attempts"], [])

    def test_attempt_has_no_wall_clock_deadline(self) -> None:
        attempt = begin_attempt(
            self.fixture.root,
            phase="code",
            step="coder-dispatch",
            operation="task-before",
            payload={"role": "coder"},
        )

        current = journal_status(self.fixture.root)

        self.assertNotIn("deadline_at", attempt)
        self.assertEqual(current["state"], "running")
        self.assertNotIn("deadline_at", current["running_attempts"][0])

    def test_tooling_configs_are_predeclared_non_business_changes(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())

        result = validate_write_path(
            self.fixture.root,
            str(self.fixture.root / "vitest.config.ts"),
        )
        context = build_context_pack(self.fixture.root, "coder")
        manifest = read_markdown_record(
            self.fixture.root / context["paths"][0]
        )

        self.assertTrue(result["ok"])
        self.assertIn("vitest.config.ts", manifest["brief"]["tooling_paths"])
        self.assertIn("eslint.config.mjs", manifest["brief"]["tooling_paths"])

    def test_init_applies_tooling_ignores_after_template_import(self) -> None:
        vitest = self.fixture.root / "vitest.config.ts"
        eslint = self.fixture.root / "eslint.config.mjs"
        vitest.write_text(
            "export default { test: { exclude: ['node_modules/**'] } }\n",
            encoding="utf-8",
        )
        eslint.write_text(
            "export default [{ ignores: ['node_modules/**'] }]\n",
            encoding="utf-8",
        )

        report = init_project(self.fixture.root)

        self.assertTrue(report["tooling_ignore"]["ok"])
        for path in (vitest, eslint):
            text = path.read_text(encoding="utf-8")
            self.assertIn(".opencode/**", text)
            self.assertIn(".sdlc-pipeline/**", text)

    def test_result_ok_false_is_recorded_as_failed(self) -> None:
        with patch("sdlc_core.cli._execute", return_value={
            "ok": False,
            "error": "functional assertion failed",
        }):
            result = execute(self.fixture.root, "lifecycle", {
                "action": "verify_delivery",
            })

        self.assertFalse(result["ok"])
        current = journal_status(self.fixture.root)
        self.assertEqual(current["state"], "failed")
        self.assertIn("functional assertion failed", current["last_error"])

    def test_incomplete_candidate_approval_does_not_create_or_block_attempt(self) -> None:
        init_project(self.fixture.root)
        before = journal_status(self.fixture.root)

        with self.assertRaisesRegex(SdlcError, "approve 缺少必填字段: content_hash"):
            execute(self.fixture.root, "spec-candidate", {
                "action": "approve",
                "candidate_id": "SC-000001",
                "confirmed": True,
            })

        after = journal_status(self.fixture.root)
        self.assertEqual(after.get("attempt_count", 0), before.get("attempt_count", 0))
        self.assertNotEqual(after.get("state"), "blocked")

    def test_coder_dispatch_has_heartbeat_and_terminal_handoff(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())

        started = execute(self.fixture.root, "task-before", {
            "role": "coder",
            "owner_pid": os.getpid(),
        })
        running = journal_status(self.fixture.root)
        write_check = execute(self.fixture.root, "write-check", {
            "path": str(self.fixture.root / "src/feature.py"),
            "owner_pid": os.getpid(),
        })

        self.assertNotIn("deadline_seconds", started)
        self.assertNotIn("deadline_at", started)
        self.assertEqual(len(running["running_attempts"]), 1)
        self.assertNotIn("deadline_at", running["running_attempts"][0])
        self.assertTrue(write_check["heartbeat"]["ok"])
        self.assertIn("last_heartbeat_at", write_check["heartbeat"])
        self.assertEqual(write_check["path"], "src/feature.py")

        (self.fixture.root / "src/feature.py").write_text(
            "value = 1\n", encoding="utf-8"
        )
        execute(self.fixture.root, "task-after", {
            "role": "coder",
            "output": json.dumps({"summary": "done", "open_issues": []}),
        })

        self.assertEqual(journal_status(self.fixture.root)["running_attempts"], [])

    def test_coder_dispatch_has_no_requirement_count_time_budget(self) -> None:
        init_project(self.fixture.root)
        blueprint = spec_payload()
        requirement = blueprint["requirements"]["items"][0]
        design = blueprint["design"]["items"][0]
        verification = blueprint["test_plan"]["items"][0]
        for number in range(2, 7):
            requirement_copy = deepcopy(requirement)
            requirement_copy["id"] = f"R-{number:04d}"
            requirement_copy["title"] = f"功能切片 {number}"
            blueprint["requirements"]["items"].append(requirement_copy)
            design["requirement_ids"].append(requirement_copy["id"])
            verification["requirement_ids"].append(requirement_copy["id"])
        publish_spec(self.fixture.root, blueprint)

        started = execute(self.fixture.root, "task-before", {
            "role": "coder",
            "owner_pid": os.getpid(),
        })

        self.assertNotIn("deadline_seconds", started)
        self.assertNotIn("deadline_at", started)
        self.assertNotIn(
            "deadline_at",
            journal_status(self.fixture.root)["running_attempts"][0],
        )

    def test_handoff_ignores_agent_authored_mapping_fields(self) -> None:
        init_project(self.fixture.root)
        publish_spec(self.fixture.root, spec_payload())
        before_task(self.fixture.root, "coder")
        feature = self.fixture.root / "src/feature.py"
        test_file = self.fixture.root / "tests/functional/T-0001.functional.ts"
        feature.write_text("value = 1\n", encoding="utf-8")
        test_file.write_text("def test_feature(): assert True\n", encoding="utf-8")
        handoff = {
            "summary": "fixture implementation",
            "design_to_code": {"D-0001": ["src/fake.py"]},
            "test_to_files": {"T-0001": ["tests/functional/T-0001.functional.ts"]},
            "changed_files": ["src/feature.py", "tests/functional/T-0001.functional.ts"],
            "open_issues": [],
        }
        with self.assertRaisesRegex(SdlcError, "不允许的字段"):
            validate_coder_handoff(self.fixture.root, json.dumps(handoff))

    def test_spec_baseline_is_authoritative_without_current_mirror(self) -> None:
        published = publish_spec(self.fixture.root, spec_payload())
        pointer = json.loads(
            (self.fixture.root / "docs/sdlc/current.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(pointer["baseline_id"], published["baseline_id"])
        mirror = self.fixture.root / "docs/sdlc/current/requirements/R-0001.json"
        self.assertFalse(mirror.exists())

        loaded = load_current_spec(self.fixture.root)

        self.assertEqual(loaded["requirements"]["items"][0]["id"], "R-0001")
        self.assertFalse(mirror.exists())

    def test_external_binary_source_uses_controlled_metadata_extractor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            external = Path(temporary) / "system-info.png"
            external.write_bytes(b"\x89PNG\r\n\x1a\nfixture")

            ingested = ingest_source(self.fixture.root, {
                "kind": "file",
                "uri": str(external),
                "media_type": "image/png",
                "allow_external_copy": True,
            })

        self.assertEqual(ingested["extractor"]["name"], "sdlc-binary-metadata")
        self.assertIn("blob_ref", ingested["asset"])
        metadata = query_source(
            self.fixture.root,
            ingested["source_id"],
            ingested["anchors"][0]["anchor"],
        )
        self.assertIn("不包含视觉语义", metadata["text"])

    def test_external_text_source_is_ingested_once_as_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            external = Path(temporary) / "prototype.html"
            external.write_text("<main>Home prototype</main>\n", encoding="utf-8")

            ingested = ingest_source(self.fixture.root, {
                "kind": "file",
                "uri": str(external),
                "media_type": "text/html",
                "allow_external_copy": True,
            })

        asset = ingested["asset"]
        copied = self.fixture.root / ingested["content_ref"]
        self.assertTrue(copied.is_file())
        self.assertEqual(asset["original_uri"], str(external.resolve()))
        self.assertNotIn("blob_ref", asset)
        self.assertTrue(ingested["canonical_path"].endswith("index.json"))

    def test_file_source_path_alias_is_normalized_to_uri(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            external = Path(temporary) / "protocol.md"
            external.write_text("设备协议\n", encoding="utf-8")
            ingested = ingest_source(self.fixture.root, {
                "kind": "file",
                "source": str(external),
                "media_type": "text/markdown",
                "allow_external_copy": True,
            })

        self.assertEqual(ingested["source"], str(external.resolve()))
        self.assertTrue((self.fixture.root / ingested["content_ref"]).is_file())

    def test_source_query_returns_only_requested_anchor(self) -> None:
        source = ingest_source(self.fixture.root, {
            "kind": "inline",
            "content": "设备管理系统信息",
            "segments": [
                {"anchor": "feature:device", "text": "设备管理"},
                {"anchor": "field:system", "text": "系统信息"},
            ],
        })

        result = query_source(
            self.fixture.root,
            source["source_id"],
            "field:system",
        )

        self.assertEqual(result["text"], "系统信息")
        self.assertEqual(result["anchor"], "field:system")
        self.assertNotIn("设备管理", result["text"])

    def test_cli_accepts_source_query_operation(self) -> None:
        source = ingest_source(self.fixture.root, {
            "kind": "inline",
            "content": "设备管理系统信息",
        })
        core = REPO / "scripts" / "sdlc.py"
        result = subprocess.run(
            [sys.executable, str(core), "source-query", "--root", str(self.fixture.root)],
            input=json.dumps({"source_id": source["source_id"], "anchor": "text:1"}),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["text"], "设备管理系统信息")

    def test_large_unstructured_source_has_bounded_query_anchors(self) -> None:
        content = ("设备管理协议行\n" * (MAX_SOURCE_SEGMENT_CHARS // 6 + 10))
        source = ingest_source(self.fixture.root, {
            "kind": "inline",
            "content": content,
        })

        self.assertGreater(len(source["anchors"]), 1)
        self.assertEqual(source["anchors"][0]["anchor"], "text:1")
        second = query_source(self.fixture.root, source["source_id"], "text:2")
        self.assertFalse(second["truncated"])
        self.assertLessEqual(len(second["text"]), MAX_SOURCE_SEGMENT_CHARS)

    def test_command_deadline_terminates_child_process_tree(self) -> None:
        pid_file = self.fixture.root / "child.pid"
        code = (
            "import subprocess,sys,time,pathlib;"
            "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
            f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid));"
            "time.sleep(60)"
        )

        with self.assertRaisesRegex(SdlcError, "已终止进程树"):
            run_command(
                [sys.executable, "-c", code],
                cwd=self.fixture.root,
                timeout=1,
            )

        child_pid = int(pid_file.read_text(encoding="utf-8"))
        time.sleep(0.2)
        self.assertFalse(pid_alive(child_pid))

    def test_journal_idempotency_and_spec_work_resume(self) -> None:
        payload = {
            "action": "probe",
            "idempotency_key": "probe-tools-0001",
        }
        first = execute(self.fixture.root, "lifecycle", payload)
        second = execute(self.fixture.root, "lifecycle", payload)
        self.assertEqual(first, second)
        self.assertEqual(journal_status(self.fixture.root)["attempt_count"], 1)

        execute(self.fixture.root, "publish", {
            "kind": "spec-work",
            "payload": {
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
        self.assertTrue(current["spec_work"]["active"])
        self.assertNotIn("answer", json.dumps(current["spec_work"], ensure_ascii=False))
        recovered = execute(self.fixture.root, "spec-work-query", {})
        self.assertEqual(recovered["work"]["decisions"][0]["answer"], "需要")
        self.assertEqual(journal_status(self.fixture.root)["phase"], "spec")

    def test_spec_work_normalizes_tool_style_source_reference(self) -> None:
        source = ingest_source(self.fixture.root, {
            "kind": "inline",
            "source": "用户需求",
            "content": "需要离线支持。",
            "segments": [{
                "anchor": "requirement:offline",
                "text": "需要离线支持。",
            }],
        })

        execute(self.fixture.root, "publish", {
            "kind": "spec-work",
            "payload": {
                "question": {
                    "id": "Q-0001",
                    "prompt": "是否需要离线支持？",
                    "answer": "需要",
                    "status": "resolved",
                    "rationale": "现场网络不稳定",
                },
                "source_refs": [{
                    "source_id": source["source_id"],
                    "anchor": "requirement:offline",
                }],
            },
        })

        spec_work = status(self.fixture.root)["spec_work"]
        self.assertEqual(
            spec_work["source_refs"],
            [f"{source['source_id']}#requirement:offline"],
        )

    def test_hard_policy_produces_machine_violation(self) -> None:
        rules = self.fixture.root / ".sdlc-pipeline/runtime/rules"
        rules.mkdir(exist_ok=True)
        shutil.copy2(REPO / "rules/typescript.md", rules / "typescript.md")
        shutil.copy2(
            REPO / "rules/typescript.policy.json",
            rules / "typescript.policy.json",
        )
        write_json(
            self.fixture.root
            / ".sdlc-pipeline/contracts/active-rules.json",
            {
            "schema_version": "1.0",
            "template_id": "fixture",
            "source": "test",
            "rules": [{
                "id": "typescript",
                "path": ".sdlc-pipeline/runtime/rules/typescript.md",
                "sha256": sha256_file(rules / "typescript.md"),
                "policy_path": ".sdlc-pipeline/runtime/rules/typescript.policy.json",
                "policy_sha256": sha256_file(rules / "typescript.policy.json"),
                "classification": ["guidance", "hard", "executable"],
            }],
            },
        )
        (self.fixture.root / "src/unsafe.ts").write_text(
            "const value: any = 1\n", encoding="utf-8"
        )
        report = evaluate_hard_policies(self.fixture.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["violations"][0]["policy"], "typescript:no-explicit-any")

    def test_pid_identity_mismatch_refuses_to_kill(self) -> None:
        path = self.fixture.root / ".sdlc-pipeline/state/process.json"
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
