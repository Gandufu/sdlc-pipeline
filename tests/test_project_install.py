from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "install_project", REPO / "scripts" / "install_project.py"
)
assert SPEC and SPEC.loader
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


def create_remote_template(root: Path, template_id: str = "electron-scaffold") -> str:
    root.mkdir()
    (root / "app.txt").write_text("registered template\n", encoding="utf-8")
    contracts = root / ".sdlc-pipeline" / "contracts"
    contracts.mkdir(parents=True)
    lifecycle_text = "{}\n"
    (contracts / "lifecycle.json").write_text(lifecycle_text, encoding="utf-8")
    scaffold = {
        "schema_version": "1.0",
        "template_id": template_id,
        "template_version": "1.0.0",
        "key_files": [],
        "protected_paths": [
            ".sdlc-pipeline/contracts/lifecycle.json",
            ".sdlc-pipeline/contracts/scaffold.json",
        ],
        "extension_points": [{"id": "app", "path": "app.txt"}],
        "allowed_paths": ["app.txt"],
        "lifecycle_hash": hashlib.sha256(lifecycle_text.encode("utf-8")).hexdigest(),
        "capabilities": ["test"],
    }
    (contracts / "scaffold.json").write_text(
        json.dumps(scaffold, indent=2) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Tests",
            "-c",
            "user.email=tests@example.invalid",
            "commit",
            "-qm",
            "template",
        ],
        cwd=root,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class InstallerTests(unittest.TestCase):
    def test_installs_opencode_surface_with_tester_subagent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            result = installer.install(target)
            self.assertTrue(result["ok"])
            self.assertEqual(result["host"], "opencode")
            agents = sorted(path.name for path in (target / ".opencode/agents").glob("*.md"))
            self.assertEqual(
                agents,
                ["sdlc-coder.md", "sdlc-main.md", "sdlc-tester.md"],
            )
            commands = sorted(path.name for path in (target / ".opencode/commands").glob("*.md"))
            self.assertEqual(
                commands,
                ["sdlc-code.md", "sdlc-init.md", "sdlc-spec.md", "sdlc-test.md"],
            )
            self.assertFalse((target / ".claude").exists())
            self.assertFalse((target / ".codex").exists())
            self.assertTrue(
                (
                    target
                    / ".opencode/skills/extract-project-template/SKILL.md"
                ).is_file()
            )
            installed_templates = sorted(
                path.relative_to(
                    target / ".sdlc-pipeline/runtime/templates"
                ).as_posix()
                for path in (
                    target / ".sdlc-pipeline/runtime/templates"
                ).rglob("*")
                if path.is_file()
            )
            self.assertEqual(installed_templates, [
                "artifacts/decision.template.md",
                "artifacts/design.template.md",
                "artifacts/requirement.template.md",
                "artifacts/verification.template.md",
                "manifest.json",
            ])
            self.assertFalse((target / ".sdlc-pipeline/opencode").exists())
            self.assertFalse((target / ".sdlc-pipeline/runs").exists())
            self.assertFalse((target / ".sdlc-pipeline/scripts").exists())
            self.assertFalse((target / "docs/sdlc").exists())
            self.assertTrue(
                (
                    target
                    / ".sdlc-pipeline/runtime/scripts/sdlc.py"
                ).is_file()
            )

    def test_install_preserves_unmanaged_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            custom = target / ".opencode" / "commands" / "custom.md"
            custom.parent.mkdir(parents=True)
            custom.write_text("mine", encoding="utf-8")
            installer.install(target)
            self.assertEqual(custom.read_text(encoding="utf-8"), "mine")

    def test_install_does_not_copy_distribution_node_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            installer.install(target)
            copied = target / ".sdlc-pipeline" / "opencode" / "node_modules"
            self.assertFalse(copied.exists())

    def test_install_self_checks_contracts_and_injects_tool_ignores(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            vitest = target / "vitest.config.ts"
            eslint = target / "eslint.config.mjs"
            vitest.write_text(
                "export default { test: { exclude: ['node_modules/**'] } }\n",
                encoding="utf-8",
            )
            eslint.write_text(
                "export default [{ ignores: ['node_modules/**'] }]\n",
                encoding="utf-8",
            )

            result = installer.install(target)

            self.assertTrue(result["contract_self_check"]["ok"])
            self.assertEqual(result["tooling_ignore"]["unresolved"], [])
            for path in (vitest, eslint):
                text = path.read_text(encoding="utf-8")
                self.assertIn(".opencode/**", text)
                self.assertIn(".sdlc-pipeline/**", text)

    def test_force_upgrade_refreshes_active_rule_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            installer.install(target)
            contracts = target / ".sdlc-pipeline" / "contracts"
            contracts.mkdir(parents=True)
            (contracts / "lifecycle.json").write_text("{}\n", encoding="utf-8")
            (contracts / "scaffold.json").write_text(
                json.dumps({"template_id": "sdlc-electron-scaffold"}) + "\n",
                encoding="utf-8",
            )
            (contracts / "active-rules.json").write_text(
                json.dumps({
                    "schema_version": "1.0",
                    "template_id": "sdlc-electron-scaffold",
                    "source": "stale",
                    "rules": [{
                        "id": "typescript",
                        "path": ".sdlc-pipeline/runtime/rules/typescript.md",
                        "sha256": "0" * 64,
                        "classification": ["guidance"],
                    }],
                }) + "\n",
                encoding="utf-8",
            )

            result = installer.install(target, force=True)

            self.assertIsNotNone(result["active_rules"])
            active = json.loads(
                (contracts / "active-rules.json").read_text(encoding="utf-8")
            )
            for rule in active["rules"]:
                rule_path = target / rule["path"]
                self.assertEqual(
                    rule["sha256"],
                    hashlib.sha256(rule_path.read_bytes()).hexdigest(),
                )

    def test_install_adds_plugin_sdk_dependency_and_preserves_existing_dependencies(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            package_path = target / ".opencode" / "package.json"
            package_path.parent.mkdir(parents=True)
            package_path.write_text(
                json.dumps(
                    {
                        "private": True,
                        "dependencies": {"existing-plugin-dependency": "^1.0.0"},
                    }
                ),
                encoding="utf-8",
            )

            installer.install(target)

            package = json.loads(package_path.read_text(encoding="utf-8"))
            self.assertTrue(package["private"])
            self.assertEqual(package["type"], "module")
            self.assertEqual(
                package["dependencies"]["existing-plugin-dependency"], "^1.0.0"
            )
            self.assertEqual(
                package["dependencies"]["@opencode-ai/plugin"],
                installer.OPENCODE_PLUGIN_VERSION,
            )

    def test_reinstall_requires_force(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            installer.install(target)
            with self.assertRaises(ValueError):
                installer.install(target)

    def test_force_upgrade_removes_all_obsolete_managed_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            installer.install(target)
            obsolete = [
                target / ".opencode/agents/sdlc-executor.md",
                target
                / ".sdlc-pipeline/runtime/schemas/feature-contract.schema.json",
                target / ".sdlc-pipeline/runtime/schemas/spec.schema.json",
                target
                / ".sdlc-pipeline/runtime/schemas/interactions/spec-checkpoint.schema.json",
                target
                / ".sdlc-pipeline/runtime/scripts/sdlc_core/feature_contracts.py",
            ]
            for path in obsolete:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("obsolete", encoding="utf-8")

            installer.install(target, force=True)

            self.assertTrue(all(not path.exists() for path in obsolete))
            self.assertTrue(
                (target / ".sdlc-pipeline/runtime/schemas/interactions/spec-work.schema.json").is_file()
            )
            self.assertTrue(installer.install(target, force=True)["ok"])

    def test_installed_runtime_can_install_another_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first = base / "first"
            second = base / "second"
            first.mkdir()
            second.mkdir()
            installer.install(first)
            runtime_installer = (
                first
                / ".sdlc-pipeline/runtime/scripts/install_project.py"
            )
            spec = importlib.util.spec_from_file_location("runtime_installer", runtime_installer)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertTrue(module.install(second)["ok"])
            self.assertTrue((second / ".opencode/plugins/sdlc-pipeline.js").exists())

    def test_downloaded_installer_fetches_complete_distribution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            raw_script = base / "install_project.py"
            shutil.copy2(REPO / "scripts" / "install_project.py", raw_script)
            spec = importlib.util.spec_from_file_location("raw_installer", raw_script)
            assert spec and spec.loader
            raw = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(raw)
            self.assertFalse(raw.is_distribution(raw.PLUGIN_ROOT))
            target = base / "project"
            target.mkdir()
            prepared = {
                "manager": "npm",
                "package": "@opencode-ai/plugin",
                "version": "1.18.5",
            }
            with patch.object(
                raw, "_clone_distribution", return_value=REPO
            ) as clone, patch.object(
                raw,
                "prepare_opencode_plugin_dependencies",
                return_value=prepared,
            ):
                result = raw.install_from_repository(
                    target, False, "https://example.invalid/sdlc-pipeline.git", "main"
                )
            clone.assert_called_once()
            self.assertTrue(result["ok"])
            self.assertEqual(result["plugin_dependencies"], prepared)
            self.assertTrue(
                (
                    target / ".sdlc-pipeline/runtime/scripts/sdlc.py"
                ).exists()
            )

    def test_downloaded_installer_can_load_without_file_global(self) -> None:
        source = (REPO / "scripts" / "install_project.py").read_text(
            encoding="utf-8"
        )
        namespace = {"__name__": "downloaded_installer"}

        exec(compile(source, "<downloaded-installer>", "exec"), namespace)

        self.assertIsInstance(namespace["PLUGIN_ROOT"], Path)

    def test_downloaded_installer_main_uses_repository_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            raw_script = base / "install_project.py"
            shutil.copy2(REPO / "scripts" / "install_project.py", raw_script)
            spec = importlib.util.spec_from_file_location("raw_installer_main", raw_script)
            assert spec and spec.loader
            raw = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(raw)
            output = io.StringIO()
            with patch.object(raw, "install_from_repository", return_value={"ok": True}) as fallback, patch.object(
                sys, "argv", [str(raw_script), "--target", str(base)]
            ), patch("sys.stdout", output):
                self.assertEqual(raw.main(), 0)
            fallback.assert_called_once_with(
                Path(base), False, raw.DEFAULT_REPOSITORY, raw.DEFAULT_REF
            )
            self.assertIn('"ok": true', output.getvalue())

    def test_complete_install_prepares_plugin_dependency_without_manual_step(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            prepared = {
                "manager": "npm",
                "package": "@opencode-ai/plugin",
                "version": "1.18.5",
            }
            with patch.object(
                installer,
                "prepare_opencode_plugin_dependencies",
                return_value=prepared,
            ) as prepare:
                result = installer.install_complete(target)

            prepare.assert_called_once_with(target.resolve())
            self.assertEqual(result["plugin_dependencies"], prepared)

    def test_registered_init_resolves_metadata_and_preserves_template_history(self) -> None:
        import sys

        sys.path.insert(0, str(REPO / "scripts"))
        from sdlc_core.bootstrap import bootstrap

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            remote = base / "remote-template"
            source_sha = create_remote_template(remote)
            project = base / "project"
            project.mkdir()
            installer.install(project)
            expected_report = {"status": "pass", "tools": {"missing": []}}
            with patch(
                "sdlc_core.bootstrap.resolve_template_source",
                return_value={
                    "id": "electron-scaffold",
                    "source": {
                        "kind": "git",
                        "repository": str(remote),
                        "ref": "HEAD",
                    },
                },
            ), patch("sdlc_core.lifecycle.init_project", return_value=expected_report):
                result = bootstrap(project, template="electron-scaffold")
            self.assertTrue(result["ok"])
            self.assertEqual(result["project_root"], str(project.resolve()))
            self.assertEqual(result["source"], {
                "kind": "registry",
                "template": "electron-scaffold",
                "repository": str(remote),
                "ref": "HEAD",
                "commit": source_sha,
            })
            self.assertEqual(result["git_baseline"], source_sha)
            self.assertEqual(
                (project / "app.txt").read_text(encoding="utf-8"),
                "registered template\n",
            )
            self.assertTrue(
                (
                    project
                    / ".sdlc-pipeline/contracts/lifecycle.json"
                ).exists()
            )

    def test_adapter_only_workspace_is_not_an_existing_project(self) -> None:
        sys.path.insert(0, str(REPO / "scripts"))
        from sdlc_core.cli import execute
        from sdlc_core.common import SdlcError

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            installer.install(project)
            with self.assertRaisesRegex(
                SdlcError,
                "仅安装了 SDLC adapter.*模板数据源 ID",
            ):
                execute(project, "lifecycle", {"action": "init"})

    def test_registered_init_resumes_after_template_gate_failure(self) -> None:
        sys.path.insert(0, str(REPO / "scripts"))
        from sdlc_core.bootstrap import bootstrap

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            remote = base / "remote-template"
            source_sha = create_remote_template(remote)
            project = base / "project"
            project.mkdir()
            installer.install(project)
            reports = [
                {"status": "failed", "tools": {"missing": []}},
                {"status": "pass", "tools": {"missing": []}},
            ]
            with patch(
                "sdlc_core.bootstrap.resolve_template_source",
                return_value={
                    "id": "electron-scaffold",
                    "source": {
                        "kind": "git",
                        "repository": str(remote),
                        "ref": "HEAD",
                    },
                },
            ), patch("sdlc_core.lifecycle.init_project", side_effect=reports):
                first = bootstrap(project, template="electron-scaffold")
                second = bootstrap(project, template="electron-scaffold")
            self.assertFalse(first["ok"])
            self.assertTrue(second["ok"])
            self.assertTrue(second["resumed"])
            self.assertEqual(second["files_imported"], [])
            self.assertEqual(second["git_baseline"], source_sha)

    def test_github_init_imports_into_current_project_and_preserves_history(self) -> None:
        import sys

        sys.path.insert(0, str(REPO / "scripts"))
        from sdlc_core.bootstrap import bootstrap

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            remote = base / "remote-template"
            project = base / "project"
            remote.mkdir()
            (remote / "app.txt").write_text("remote template\n", encoding="utf-8")
            contracts = remote / ".sdlc-pipeline" / "contracts"
            contracts.mkdir(parents=True)
            (contracts / "lifecycle.json").write_text("{}\n", encoding="utf-8")
            (contracts / "scaffold.json").write_text("{}\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=remote, check=True)
            subprocess.run(["git", "add", "-A"], cwd=remote, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Tests", "-c", "user.email=tests@example.invalid",
                 "commit", "-qm", "template"],
                cwd=remote,
                check=True,
            )
            source_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=remote, check=True,
                capture_output=True, text=True,
            ).stdout.strip()
            project.mkdir()
            installer.install(project)
            expected_report = {"status": "pass", "tools": {"missing": []}}
            with patch("sdlc_core.lifecycle.init_project", return_value=expected_report):
                result = bootstrap(project, github=str(remote), ref="HEAD")
            self.assertTrue(result["ok"])
            self.assertEqual(result["project_root"], str(project.resolve()))
            self.assertEqual(result["git_baseline"], source_sha)
            self.assertTrue((project / ".git").exists())
            self.assertEqual((project / "app.txt").read_text(encoding="utf-8"), "remote template\n")
            self.assertTrue(
                (
                    project
                    / ".sdlc-pipeline/contracts/lifecycle.json"
                ).exists()
            )

    def test_templates_directory_contains_metadata_only(self) -> None:
        registry = json.loads(
            (REPO / "templates" / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(registry["schema_version"], "1.0")
        self.assertEqual(
            [item["id"] for item in registry["templates"]],
            ["sdlc-electron-scaffold"],
        )
        self.assertEqual(
            registry["templates"][0]["source"],
            {
                "kind": "git",
                "repository": "https://github.com/Gandufu/sdlc-electron-scaffold.git",
                "ref": "main",
            },
        )
        files = sorted(
            path.relative_to(REPO / "templates").as_posix()
            for path in (REPO / "templates").rglob("*")
            if path.is_file()
        )
        self.assertEqual(files, [
            "artifacts/decision.template.md",
            "artifacts/design.template.md",
            "artifacts/requirement.template.md",
            "artifacts/verification.template.md",
            "manifest.json",
        ])

    def test_remote_checkouts_disable_git_line_ending_conversion(self) -> None:
        installer_source = (REPO / "scripts/install_project.py").read_text(
            encoding="utf-8"
        )
        bootstrap_source = (REPO / "scripts/sdlc_core/bootstrap.py").read_text(
            encoding="utf-8"
        )
        expected = '"git", "-c", "core.autocrlf=false"'
        self.assertIn(expected, installer_source)
        self.assertIn(expected, bootstrap_source)

    def test_all_json_schemas_are_valid_json(self) -> None:
        schemas = list((REPO / "schemas").rglob("*.schema.json"))
        self.assertGreaterEqual(len(schemas), 6)
        for path in schemas:
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_distribution_versions_are_aligned(self) -> None:
        package = json.loads((REPO / "package.json").read_text(encoding="utf-8"))
        core_version = {}
        exec(
            (REPO / "scripts/sdlc_core/__init__.py").read_text(encoding="utf-8"),
            core_version,
        )
        self.assertEqual(package["version"], installer.VERSION)
        self.assertEqual(core_version["__version__"], installer.VERSION)
        self.assertIn(
            f"当前版本：`{installer.VERSION}`",
            (REPO / "README.md").read_text(encoding="utf-8"),
        )

    def test_agent_lifetime_and_adr_sequence_are_documented_consistently(self) -> None:
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        coder = (REPO / ".opencode/agents/sdlc-coder.md").read_text(
            encoding="utf-8"
        )
        adr_names = sorted(path.name for path in (REPO / "docs/adr").glob("*.md"))

        self.assertIn("不使用固定秒数或 agent 轮次上限", readme)
        self.assertNotIn("steps:", coder)
        self.assertEqual(
            adr_names,
            [
                "0001-opencode-first.md",
                "0002-external-template-assets.md",
                "0003-storage-layout-v3.md",
                "0004-native-markdown-artifacts.md",
                "0005-separate-code-controls-from-functional-tests.md",
                "0006-contract-driven-test-suites-and-preflight.md",
            ],
        )

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_plugin_selects_configured_python_or_platform_default(self) -> None:
        plugin = REPO / ".opencode/plugins/sdlc-pipeline.js"
        script = (
            "import(process.argv[1]).then(m => console.log(JSON.stringify(["
            "m.pythonExecutable({SDLC_PYTHON: 'sdlc-python'}, 'linux'),"
            "m.pythonExecutable({PYTHON: 'configured-python'}, 'linux'),"
            "m.pythonExecutable({}, 'linux'),"
            "m.pythonExecutable({}, 'win32')"
            "])))"
        )
        result = subprocess.run(
            ["node", "-e", script, plugin.as_uri()],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            ["sdlc-python", "configured-python", "python3", "python"],
        )

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_plugin_returns_bounded_source_receipt(self) -> None:
        plugin = REPO / ".opencode/plugins/sdlc-pipeline.js"
        script = (
            "import(process.argv[1]).then(m => console.log(JSON.stringify("
            "m.sourceReceipt({ok:true,envelope:{source_id:'SRC-TEST',kind:'file',"
            "source:'external.md',uri:'.sdlc-pipeline/work/sources/test.md',"
            "media_type:'text/plain',sha256:'hash',content:'x'.repeat(20000),"
            "segments:[{anchor:'text:1',text:'x'.repeat(20000),sha256:'segment'}]}}))))"
        )
        result = subprocess.run(
            ["node", "-e", script, plugin.as_uri()],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["source_id"], "SRC-TEST")
        self.assertEqual(receipt["anchors"][0]["characters"], 20000)
        self.assertLessEqual(len(receipt["anchors"][0]["preview"]), 160)
        self.assertNotIn("content", receipt)
        self.assertIn("do not read", receipt["next_action"])

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_plugin_allows_coder_bounded_source_query_but_rejects_tester(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            plugin_path = target / ".opencode" / "plugins" / "sdlc-pipeline.js"
            plugin_path.parent.mkdir(parents=True)
            shutil.copy2(REPO / ".opencode/plugins/sdlc-pipeline.js", plugin_path)
            core = (
                target
                / ".sdlc-pipeline"
                / "runtime"
                / "scripts"
                / "sdlc.py"
            )
            core.parent.mkdir(parents=True)
            core.write_text(
                "import json, sys\n"
                "payload = json.load(sys.stdin)\n"
                "print(json.dumps({"
                "'ok': True, 'operation': sys.argv[1], **payload, "
                "'text': 'bounded source text'"
                "}))\n",
                encoding="utf-8",
            )
            sdk = target / ".opencode" / "node_modules" / "@opencode-ai" / "plugin"
            sdk.mkdir(parents=True)
            (sdk / "package.json").write_text(
                json.dumps({
                    "name": "@opencode-ai/plugin",
                    "type": "module",
                    "exports": "./index.js",
                }),
                encoding="utf-8",
            )
            (sdk / "index.js").write_text(
                "const schema = () => ({ optional() { return this }, describe() { return this } })\n"
                "export const tool = (input) => input\n"
                "tool.schema = { enum: schema, string: schema, boolean: schema, "
                "object: schema, array: schema }\n",
                encoding="utf-8",
            )
            script = (
                "import(process.argv[1]).then(async m => {"
                "const plugin = await m.SdlcPipelinePlugin({"
                "directory: process.argv[2], worktree: process.argv[2]"
                "});"
                "const query = plugin.tool.sdlc_query_source;"
                "const coder = JSON.parse(await query.execute("
                "{source_id: 'SRC-000000000001', anchor: 'text:1'}, "
                "{agent: 'sdlc-coder', directory: process.argv[2]}"
                "));"
                "let testerError = '';"
                "try {"
                "await query.execute("
                "{source_id: 'SRC-000000000001', anchor: 'text:1'}, "
                "{agent: 'sdlc-tester', directory: process.argv[2]}"
                ");"
                "} catch (error) { testerError = String(error.message || error); }"
                "const begin = plugin.tool.sdlc_begin_rework;"
                "const reworkArgs = {origin: 'manual_preview', "
                "classification: 'implementation', summary: 'bug', "
                "expected: 'expected', actual: 'actual', "
                "reproduction_steps: ['open preview'], affected_ids: ['R-0001'], "
                "source_refs: [{source_id: 'SRC-000000000001', anchor: 'text:1'}], "
                "evidence_refs: []};"
                "const rework = JSON.parse(await begin.execute(reworkArgs, "
                "{agent: 'sdlc-main', directory: process.argv[2]}));"
                "let coderReworkError = '';"
                "try { await begin.execute(reworkArgs, "
                "{agent: 'sdlc-coder', directory: process.argv[2]}); "
                "} catch (error) { coderReworkError = String(error.message || error); }"
                "console.log(JSON.stringify({coder, testerError, rework, coderReworkError}));"
                "}).catch(e => { console.error(e); process.exit(1) })"
            )
            result = subprocess.run(
                ["node", "-e", script, plugin_path.as_uri(), str(target)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["coder"]["requester"], "sdlc-coder")
        self.assertEqual(output["coder"]["text"], "bounded source text")
        self.assertEqual(output["rework"]["operation"], "rework")
        self.assertEqual(
            output["rework"]["source_refs"],
            ["SRC-000000000001#text:1"],
        )
        self.assertIn(
            "sdlc_begin_rework is not available to agent sdlc-coder",
            output["coderReworkError"],
        )
        self.assertIn(
            "sdlc_query_source is not available to agent sdlc-tester",
            output["testerError"],
        )

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_plugin_normalizes_file_source_path_alias(self) -> None:
        plugin = REPO / ".opencode/plugins/sdlc-pipeline.js"
        script = (
            "import(process.argv[1]).then(m => console.log(JSON.stringify("
            "m.sourcePayload({source_type:'file',source:'C:/TEMP/protocol.md',"
            "allow_external_copy:true}))))"
        )
        result = subprocess.run(
            ["node", "-e", script, plugin.as_uri()],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "kind": "file",
            "uri": "C:/TEMP/protocol.md",
            "allow_external_copy": True,
        })
        directory_script = (
            "import(process.argv[1]).then(m => console.log(JSON.stringify("
            "m.sourcePayload({source_type:'directory',"
            "source:'C:/TEMP/prototype',allow_external_copy:true}))))"
        )
        directory_result = subprocess.run(
            ["node", "-e", directory_script, plugin.as_uri()],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(directory_result.returncode, 0, directory_result.stderr)
        self.assertEqual(json.loads(directory_result.stdout), {
            "kind": "directory",
            "uri": "C:/TEMP/prototype",
            "allow_external_copy": True,
        })
        self.assertIn(
            '["inline", "file", "directory", "url", "document"]',
            plugin.read_text(encoding="utf-8"),
        )

    def test_source_guidance_preserves_file_formats_and_directory_bundles(
        self,
    ) -> None:
        plugin = (REPO / ".opencode/plugins/sdlc-pipeline.js").read_text(
            encoding="utf-8"
        )
        command = (REPO / ".opencode/commands/sdlc-spec.md").read_text(
            encoding="utf-8"
        )
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(
            encoding="utf-8"
        )
        readme = (REPO / "README.md").read_text(encoding="utf-8")

        for text in (plugin, command, main, readme):
            self.assertIn("保持原格式", text)
            self.assertIn("directory", text)
        self.assertIn("asset_ref", plugin)
        self.assertIn("asset anchor", command)
        self.assertIn("manifest.json", readme)
        self.assertNotIn("图片等二进制文件默认保存受控元数据和原件", plugin)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_plugin_rejects_incomplete_approval_before_core_invocation(self) -> None:
        plugin = REPO / ".opencode/plugins/sdlc-pipeline.js"
        script = (
            "import(process.argv[1]).then(m => console.log(JSON.stringify("
            "m.approvalPayload({candidate_id:'SC-000001',confirmed:true}))))"
        )
        result = subprocess.run(
            ["node", "-e", script, plugin.as_uri()],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], "invalid_approval_arguments")
        self.assertIn("content_hash", payload["error"])
        plugin_text = plugin.read_text(encoding="utf-8")
        self.assertIn("const approval = approvalPayload(args)", plugin_text)
        self.assertIn("if (!approval.ok)", plugin_text)

    def test_plugin_has_narrow_tools_without_experimental_injection(self) -> None:
        text = (REPO / ".opencode/plugins/sdlc-pipeline.js").read_text(encoding="utf-8")
        for name in (
            "sdlc_status", "sdlc_ingest_source", "sdlc_save_spec_work",
            "sdlc_query_spec_work",
            "sdlc_begin_rework",
            "sdlc_begin_candidate", "sdlc_put_requirement", "sdlc_put_design",
            "sdlc_put_verification", "sdlc_validate_candidate",
            "sdlc_approve_candidate",
            "sdlc_lifecycle", "sdlc_finalize",
        ):
            self.assertIn(name, text)
        self.assertNotIn("sdlc_publish_contract", text)
        self.assertNotIn("idempotency_key", text)
        self.assertNotIn("experimental.chat.messages.transform", text)
        self.assertNotIn("config.skills.paths", text)
        self.assertIn("sdlc-tester", text)

    def test_rework_tool_exposes_complete_feedback_contract_to_main_only(self) -> None:
        plugin = (REPO / ".opencode/plugins/sdlc-pipeline.js").read_text(
            encoding="utf-8"
        )
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")
        coder = (REPO / ".opencode/agents/sdlc-coder.md").read_text(encoding="utf-8")
        tester = (REPO / ".opencode/agents/sdlc-tester.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("sdlc_begin_rework: allow", main)
        self.assertNotIn("sdlc_begin_rework: allow", coder)
        self.assertNotIn("sdlc_begin_rework: allow", tester)
        self.assertIn('sdlc_begin_rework: tool({', plugin)
        for field in (
            "origin",
            "classification",
            "summary",
            "expected",
            "actual",
            "reproduction_steps",
            "affected_ids",
            "source_refs",
            "evidence_refs",
        ):
            self.assertIn(f"{field}:", plugin)
        self.assertIn('"rework"', plugin)

    def test_agent_permission_matrix(self) -> None:
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")
        coder = (REPO / ".opencode/agents/sdlc-coder.md").read_text(encoding="utf-8")
        tester = (REPO / ".opencode/agents/sdlc-tester.md").read_text(encoding="utf-8")
        test_command = (REPO / ".opencode/commands/sdlc-test.md").read_text(encoding="utf-8")
        plugin = (REPO / ".opencode/plugins/sdlc-pipeline.js").read_text(encoding="utf-8")
        self.assertIn('"sdlc-coder": allow', main)
        self.assertIn("sdlc_query_source: allow", main)
        self.assertIn('"*": allow', coder)
        self.assertIn('"tests/**": deny', coder)
        self.assertGreaterEqual(coder.count('"tests/**": deny'), 2)
        self.assertIn("bash: deny", coder)
        self.assertIn('"*": deny', tester)
        self.assertNotIn('"sdlc-coder": allow', tester)
        self.assertIn('"tests/**": allow', tester)
        self.assertIn("Playwright", tester)
        self.assertIn("按语义匹配请求而非数组下标", tester)
        self.assertIn("可观察的业务结果", tester)
        self.assertIn("不得用类型、非空、成功/失败任选分支", tester)
        self.assertIn("最终回复必须是下列单个、裸的 JSON 对象", tester)
        self.assertIn("preflight_unit_test_paths", tester)
        self.assertIn("替代 mock、启动服务或绑定其地址/端口", tester)
        self.assertIn("mode: subagent", tester)
        self.assertIn("sdlc_lifecycle: deny", tester)
        self.assertIn('"sdlc-tester": allow', main)
        self.assertIn("agent: sdlc-main", test_command)
        self.assertIn("task", test_command)
        self.assertIn("外部服务响应、错误情境与可观察结果", test_command)
        self.assertIn("Spec 缺口", test_command)
        self.assertIn("output_recovery", test_command)
        self.assertIn('"sdlc-tester": "tester"', plugin)
        self.assertNotIn('"sdlc-tester": ["verify_delivery"]', plugin)
        self.assertFalse((REPO / ".opencode/agents/sdlc-executor.md").exists())

    def test_spec_details_have_one_reference_source_of_truth(self) -> None:
        command = (REPO / ".opencode/commands/sdlc-spec.md").read_text(encoding="utf-8")
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")
        reference = (REPO / "references/spec-interview.md").read_text(encoding="utf-8")
        skill = (REPO / ".opencode/skills/sdlc-pipeline/SKILL.md").read_text(
            encoding="utf-8"
        )
        for text in (command, main, skill):
            self.assertIn(
                ".sdlc-pipeline/runtime/references/spec-interview.md",
                text,
            )
        self.assertIn("$ARGUMENTS", command)
        self.assertIn("不得丢弃", command)
        self.assertNotIn("feature-contract.schema.json", command + main)
        self.assertIn("Storage Layout v3", reference)
        self.assertIn("R/D/T/AC", reference)
        self.assertIn("固定响应值、错误触发方式", reference)
        self.assertIn("不能只写“字段存在”", reference)

    def test_code_command_stops_before_test_lifecycle(self) -> None:
        command = (REPO / ".opencode/commands/sdlc-code.md").read_text(
            encoding="utf-8"
        )
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("不得调用任何", command)
        self.assertIn("sdlc_lifecycle", command)
        self.assertIn("/sdlc-test", command)
        self.assertIn("不得调用", main)
        self.assertIn("sdlc-tester", main)

    def test_code_command_allows_explicit_rework_after_failed_test(self) -> None:
        command = (REPO / ".opencode/commands/sdlc-code.md").read_text(
            encoding="utf-8"
        )
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")

        self.assertIn("$ARGUMENTS", command)
        self.assertIn("sdlc_begin_rework", command)
        self.assertIn("automated_test", command)
        self.assertIn("implementation", command)
        self.assertIn("run.rework_started", main)
        self.assertIn("结构化 Feedback", main)
        self.assertIn("完整 code gate", main)

    def test_spec_command_requires_controlled_rework_after_failed_test(self) -> None:
        command = (REPO / ".opencode/commands/sdlc-spec.md").read_text(
            encoding="utf-8"
        )
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")
        plugin = (REPO / ".opencode/plugins/sdlc-pipeline.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("sdlc_begin_rework", command)
        self.assertIn("test_contract", command)
        self.assertIn("spec_published", main)
        self.assertNotIn("sdlc_rework_spec_after_test_failure", plugin)
        self.assertNotIn('"spec-rework"', plugin)

    def test_spec_guidance_requires_complete_acceptance_criteria_payload(self) -> None:
        command = (REPO / ".opencode/commands/sdlc-spec.md").read_text(
            encoding="utf-8"
        )
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")
        plugin = (REPO / ".opencode/plugins/sdlc-pipeline.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("acceptance_criteria", command)
        self.assertIn("given", command)
        self.assertIn("`acceptance_criteria` 是**必填且非空**数组", main)
        self.assertIn("不可省略整个数组", plugin)

    def test_code_command_allows_one_failed_code_gate_retry(self) -> None:
        command = (REPO / ".opencode/commands/sdlc-code.md").read_text(
            encoding="utf-8"
        )
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")

        self.assertIn("last_failure.class=code", command)
        self.assertIn("last_failure.repeat_count=1", command)
        self.assertIn("journal.recoverable", command)
        self.assertIn("同一 code phase", command)
        self.assertIn("state=failed, phase=code", main)
        self.assertIn("repeat_count=1", main)
        self.assertIn("第二次相同失败", main)

    def test_spec_work_guidance_uses_structured_arguments(self) -> None:
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")
        reference = (REPO / "references/spec-interview.md").read_text(encoding="utf-8")
        plugin = (REPO / ".opencode/plugins/sdlc-pipeline.js").read_text(
            encoding="utf-8"
        )

        for text in (main, reference):
            self.assertIn("Q-0001", text)
            self.assertIn("question", text)
        self.assertIn("specQuestion", plugin)
        self.assertIn("question", plugin)
        self.assertIn("status\":\"resolved", reference)
        self.assertIn("rationale", reference)
        self.assertIn("SRC-XXXXXXXXXXXX#anchor", reference + plugin)
        self.assertIn("sdlc_save_spec_work", plugin)
        self.assertNotIn("JSON.parse(args.payload)", plugin)

    def test_design_guidance_binds_extension_points_to_scaffold(self) -> None:
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")
        reference = (REPO / "references/spec-interview.md").read_text(encoding="utf-8")
        plugin = (REPO / ".opencode/plugins/sdlc-pipeline.js").read_text(
            encoding="utf-8"
        )

        for text in (main, reference, plugin):
            self.assertIn("scaffold.json", text)
            self.assertIn("extension_points", text)

    def test_spec_generation_requires_chinese_formal_documents(self) -> None:
        reference = (REPO / "references/spec-interview.md").read_text(encoding="utf-8")
        self.assertIn("默认中文", reference)

    def test_team_boundary_and_adapter_portability_are_documented(self) -> None:
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        adr = (REPO / "docs/adr/0001-opencode-first.md").read_text(
            encoding="utf-8"
        )
        boundaries = (REPO / "docs/operational-boundaries.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("宿主 adapter", readme)
        self.assertIn("宿主 adapter", adr)
        self.assertIn("不要手动切换 agent", boundaries)
        self.assertIn("@ 调用", boundaries)

    def test_spec_grilling_is_single_question_recommended_choice_workflow(self) -> None:
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")
        reference = (REPO / "references/spec-interview.md").read_text(encoding="utf-8")
        self.assertIn("通常在三题内", reference)
        self.assertIn("可以继续", reference)
        self.assertIn("question: allow", main)

    def test_template_registry_declares_framework_specific_rules(self) -> None:
        manifest = json.loads(
            (REPO / "templates/manifest.json").read_text(encoding="utf-8")
        )
        template = manifest["templates"][0]
        self.assertEqual(
            template["rules"],
            ["typescript", "electron", "react"],
        )
        self.assertNotIn("java", template["rules"])
        schema = json.loads(
            (REPO / "schemas/template-registry.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn(
            "rules",
            schema["properties"]["templates"]["items"]["required"],
        )
        extractor = (
            REPO / ".opencode/skills/extract-project-template/SKILL.md"
        ).read_text(encoding="utf-8")
        contract = (
            REPO
            / ".opencode/skills/extract-project-template/references/template-contract.md"
        ).read_text(encoding="utf-8")
        for text in (extractor, contract):
            self.assertIn("rules", text)
        self.assertNotIn("--github", contract)

    def test_coder_is_explicitly_routed_away_from_test_lifecycle_actions(self) -> None:
        coder = (REPO / ".opencode/agents/sdlc-coder.md").read_text(encoding="utf-8")
        plugin = (REPO / ".opencode/plugins/sdlc-pipeline.js").read_text(encoding="utf-8")
        adapter = (REPO / "scripts/sdlc_core/adapter.py").read_text(encoding="utf-8")
        self.assertNotIn("focused_check", coder)
        self.assertNotIn('"sdlc-coder": ["focused_check"]', plugin)
        self.assertIn("coder 只实现业务代码", adapter)
        self.assertNotIn("登记的 functional 文件", adapter)
        self.assertNotIn("steps:", coder)
        self.assertIn("temperature: 0.1", coder)
        self.assertIn(
            '".sdlc-pipeline/runtime/scripts/**": deny', coder
        )
        self.assertNotIn("deadlineSeconds", plugin)
        self.assertNotIn("taskDeadlines", plugin)
        self.assertNotIn("client.session.abort", plugin)
        self.assertIn("output.args.prompt =", plugin)
        self.assertNotIn("output.args.prompt = `${output.args.prompt", plugin)
        self.assertIn("第 4 次工具调用前", coder)
        self.assertIn("as any", coder)
        self.assertIn("as any", adapter)
        self.assertNotIn("@playwright/mcp", plugin)
        self.assertNotIn('output.args.command = "实现当前已发布', plugin)
        self.assertIn('"write-check"', plugin)
        self.assertNotIn('await invoke(fallbackRoot, "task-cancel"', plugin)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_coder_task_hook_keeps_short_objective_without_generic_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            plugin_path = target / ".opencode" / "plugins" / "sdlc-pipeline.js"
            plugin_path.parent.mkdir(parents=True)
            shutil.copy2(REPO / ".opencode/plugins/sdlc-pipeline.js", plugin_path)
            core = (
                target
                / ".sdlc-pipeline"
                / "runtime"
                / "scripts"
                / "sdlc.py"
            )
            core.parent.mkdir(parents=True)
            core.write_text(
                "import json, sys\n"
                "payload = json.load(sys.stdin)\n"
                "if sys.argv[1] == 'task-before':\n"
                "    print(json.dumps({'ok': True, 'context_pack': {'paths': ['.sdlc-pipeline/work/records/context/coder.md'], 'characters': 1, 'resource_count': 1}, 'instruction': '只读取必要文件'}))\n"
                "else:\n"
                "    print(json.dumps({'ok': True}))\n",
                encoding="utf-8",
            )
            sdk = target / ".opencode" / "node_modules" / "@opencode-ai" / "plugin"
            sdk.mkdir(parents=True)
            (sdk / "package.json").write_text(
                json.dumps({"name": "@opencode-ai/plugin", "type": "module", "exports": "./index.js"}),
                encoding="utf-8",
            )
            (sdk / "index.js").write_text(
                "const schema = () => ({ optional() { return this }, describe() { return this } })\n"
                "export const tool = (input) => input\n"
                "tool.schema = { enum: schema, string: schema, boolean: schema, object: schema, array: schema }\n",
                encoding="utf-8",
            )
            script = (
                "const originalSetTimeout = global.setTimeout;"
                "const delays = [];"
                "global.setTimeout = (callback, milliseconds, ...args) => {"
                "delays.push(milliseconds);"
                "return originalSetTimeout(callback, 60000, ...args);"
                "};"
                "import(process.argv[1]).then(async m => {"
                "const plugin = await m.SdlcPipelinePlugin({directory: process.argv[2], worktree: '/'});"
                "const output = {args: {description: '实现 R-0001 应用外壳', prompt: '调用方上下文不得复制', subagent_type: 'sdlc-coder'}};"
                "await plugin['tool.execute.before']({tool: 'task', sessionID: 'ses-test', callID: 'call-test'}, output);"
                "console.log(JSON.stringify({args: output.args, delays}));"
                "}).catch(e => { console.error(e); process.exit(1) })"
            )
            result = subprocess.run(
                ["node", "-e", script, plugin_path.as_uri(), str(target)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            args = output["args"]
            self.assertNotIn("command", args)
            self.assertIn("本次任务目标：实现 R-0001 应用外壳", args["prompt"])
            self.assertNotIn("调用方上下文不得复制", args["prompt"])
            self.assertNotIn(600_000, output["delays"])

    def test_evidence_collector_keeps_early_failure_summary(self) -> None:
        collector_spec = importlib.util.spec_from_file_location(
            "collect_opencode_evidence",
            REPO / "scripts" / "collect_opencode_evidence.py",
        )
        assert collector_spec and collector_spec.loader
        collector = importlib.util.module_from_spec(collector_spec)
        collector_spec.loader.exec_module(collector)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            attempts = (
                root / ".sdlc-pipeline" / "state" / "runs" / "RUN-TEST"
                / "attempts" / "spec"
            )
            attempts.mkdir(parents=True)
            for index in range(1, 15):
                failed = index == 1
                error_ref = (
                    f".sdlc-pipeline/evidence/errors/RUN-TEST/"
                    f"A{index:06d}.md"
                    if failed else None
                )
                (attempts / f"A{index:06d}.json").write_text(
                    json.dumps({
                        "attempt_id": f"A{index:06d}",
                        "phase": "spec",
                        "step": "validate",
                        "state": "failed" if failed else "succeeded",
                        "started_at": f"2026-01-01T00:00:{index:02d}+00:00",
                        "finished_at": f"2026-01-01T00:00:{index:02d}+00:00",
                        "error_ref": error_ref,
                        "result_ref": (
                            None if failed else
                            f".sdlc-pipeline/work/runs/RUN-TEST/attempts/"
                            f"A{index:06d}-result.md"
                        ),
                    }),
                    encoding="utf-8",
                )
                if failed:
                    error_path = root / error_ref
                    error_path.parent.mkdir(parents=True, exist_ok=True)
                    error_path.write_text(
                        "# Error\n\n<!-- sdlc-record:begin -->\n"
                        "```json\n"
                        '{"message":"early schema failure"}\n'
                        "```\n<!-- sdlc-record:end -->\n",
                        encoding="utf-8",
                    )

            evidence = collector.collect(root)

            self.assertNotIn(
                "A000001",
                [item["attempt_id"] for item in evidence["latest_journal_attempts"]],
            )
            self.assertEqual(evidence["journal_failure_summary"]["total"], 1)
            self.assertEqual(evidence["journal_failure_summary"]["groups"], [{
                "phase": "spec",
                "step": "validate",
                "state": "failed",
                "error": "early schema failure",
                "count": 1,
                "first_attempt_id": "A000001",
                "last_attempt_id": "A000001",
            }])

    def test_spec_guidance_distinguishes_test_key_from_shell_command(self) -> None:
        text = (REPO / "references/spec-interview.md").read_text(encoding="utf-8")
        self.assertIn("测试键由项目 lifecycle 合约声明", text)
        self.assertIn("functional", text)
        self.assertIn("unit", text)

    def test_desktop_project_assets_are_discoverable(self) -> None:
        self.assertTrue((REPO / ".opencode/plugins/sdlc-pipeline.js").exists())
        self.assertTrue((REPO / ".opencode/skills/sdlc-pipeline/SKILL.md").exists())
        package = json.loads(
            (REPO / ".opencode/package.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            package["dependencies"]["@opencode-ai/plugin"],
            installer.OPENCODE_PLUGIN_VERSION,
        )
        for name in ("sdlc-main", "sdlc-coder", "sdlc-tester"):
            self.assertTrue((REPO / f".opencode/agents/{name}.md").exists())

    def test_init_is_parameterless_idempotent_and_user_selects_registry_template(
        self,
    ) -> None:
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        init_command = (
            REPO / ".opencode/commands/sdlc-init.md"
        ).read_text(encoding="utf-8")
        self.assertIn("只执行 `/sdlc-init`", readme)
        self.assertIn("raw.githubusercontent.com/Gandufu/sdlc-pipeline", readme)
        self.assertNotIn("<SDLC_PIPELINE_ROOT>", readme)
        self.assertIn("第一步调用 `sdlc_status`", init_command)
        self.assertIn("init_state.completed", init_command)
        self.assertIn("templates", init_command)
        self.assertIn("明确选择", init_command)
        self.assertIn("即使只有一个候选", init_command)
        self.assertNotIn("$ARGUMENTS", init_command)
        self.assertNotIn("--github", init_command)
        self.assertNotIn("安装 OpenCode", init_command)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_plugin_javascript_syntax(self) -> None:
        subprocess.run(
            ["node", "--check", str(REPO / ".opencode/plugins/sdlc-pipeline.js")],
            check=True,
            capture_output=True,
            text=True,
        )

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_coder_task_hook_validates_handoff_then_runs_code_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            plugin_path = target / ".opencode" / "plugins" / "sdlc-pipeline.js"
            plugin_path.parent.mkdir(parents=True)
            shutil.copy2(REPO / ".opencode/plugins/sdlc-pipeline.js", plugin_path)
            core = (
                target
                / ".sdlc-pipeline"
                / "runtime"
                / "scripts"
                / "sdlc.py"
            )
            core.parent.mkdir(parents=True)
            core.write_text(
                "import json, sys\n"
                "from pathlib import Path\n"
                "root = Path(sys.argv[sys.argv.index('--root') + 1])\n"
                "payload = json.load(sys.stdin)\n"
                "with (root / 'operations.jsonl').open('a', encoding='utf-8') as handle:\n"
                "    handle.write(json.dumps({'operation': sys.argv[1], 'payload': payload}) + '\\n')\n"
                "print(json.dumps({'ok': True}))\n",
                encoding="utf-8",
            )
            sdk = target / ".opencode" / "node_modules" / "@opencode-ai" / "plugin"
            sdk.mkdir(parents=True)
            (sdk / "package.json").write_text(
                json.dumps({"name": "@opencode-ai/plugin", "type": "module", "exports": "./index.js"}),
                encoding="utf-8",
            )
            (sdk / "index.js").write_text(
                "const schema = () => ({ optional() { return this }, describe() { return this } })\n"
                "export const tool = (input) => input\n"
                "tool.schema = { enum: schema, string: schema, boolean: schema, "
                "object: schema, array: schema }\n",
                encoding="utf-8",
            )
            script = (
                "import(process.argv[1]).then(async m => {"
                "const plugin = await m.SdlcPipelinePlugin({directory: process.argv[2], worktree: '/'});"
                "await plugin['tool.execute.after']({tool: 'task', args: {subagent_type: 'sdlc-coder'}}, {output: '{}'})"
                "}).catch(e => { console.error(e); process.exit(1) })"
            )
            result = subprocess.run(
                ["node", "-e", script, plugin_path.as_uri(), str(target)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            operations = [
                json.loads(line)
                for line in (target / "operations.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [item["operation"] for item in operations],
                ["task-after", "lifecycle"],
            )
            self.assertEqual(
                operations[1]["payload"]["action"],
                "compile_restart_verify",
            )
            self.assertEqual(operations[0]["payload"]["role"], "coder")

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_tester_task_hook_validates_handoff_then_runs_delivery_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            plugin_path = target / ".opencode" / "plugins" / "sdlc-pipeline.js"
            plugin_path.parent.mkdir(parents=True)
            shutil.copy2(REPO / ".opencode/plugins/sdlc-pipeline.js", plugin_path)
            core = (
                target
                / ".sdlc-pipeline"
                / "runtime"
                / "scripts"
                / "sdlc.py"
            )
            core.parent.mkdir(parents=True)
            core.write_text(
                "import json, sys\n"
                "from pathlib import Path\n"
                "root = Path(sys.argv[sys.argv.index('--root') + 1])\n"
                "payload = json.load(sys.stdin)\n"
                "with (root / 'operations.jsonl').open('a', encoding='utf-8') as handle:\n"
                "    handle.write(json.dumps({'operation': sys.argv[1], 'payload': payload}) + '\\n')\n"
                "print(json.dumps({'ok': True}))\n",
                encoding="utf-8",
            )
            sdk = target / ".opencode" / "node_modules" / "@opencode-ai" / "plugin"
            sdk.mkdir(parents=True)
            (sdk / "package.json").write_text(
                json.dumps({"name": "@opencode-ai/plugin", "type": "module", "exports": "./index.js"}),
                encoding="utf-8",
            )
            (sdk / "index.js").write_text(
                "const schema = () => ({ optional() { return this }, describe() { return this } })\n"
                "export const tool = (input) => input\n"
                "tool.schema = { enum: schema, string: schema, boolean: schema, "
                "object: schema, array: schema }\n",
                encoding="utf-8",
            )
            script = (
                "import(process.argv[1]).then(async m => {"
                "const plugin = await m.SdlcPipelinePlugin({directory: process.argv[2], worktree: '/'});"
                "await plugin['tool.execute.after']({tool: 'task', args: {subagent_type: 'sdlc-tester'}}, {output: '{}'})"
                "}).catch(e => { console.error(e); process.exit(1) })"
            )
            result = subprocess.run(
                ["node", "-e", script, plugin_path.as_uri(), str(target)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            operations = [
                json.loads(line)
                for line in (target / "operations.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual(
                [item["operation"] for item in operations],
                ["task-after", "lifecycle"],
            )
            self.assertEqual(operations[0]["payload"]["role"], "tester")
            self.assertEqual(
                operations[1]["payload"]["action"],
                "verify_delivery",
            )

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_removed_executor_cannot_execute_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            plugin_path = target / ".opencode" / "plugins" / "sdlc-pipeline.js"
            plugin_path.parent.mkdir(parents=True)
            shutil.copy2(REPO / ".opencode/plugins/sdlc-pipeline.js", plugin_path)
            core = target / ".sdlc-pipeline" / "scripts" / "sdlc.py"
            core.parent.mkdir(parents=True)
            core.write_text(
                "import json, sys\n"
                "payload = json.load(sys.stdin)\n"
                "print(json.dumps({'ok': True, 'action': payload.get('action')}))\n",
                encoding="utf-8",
            )
            sdk = target / ".opencode" / "node_modules" / "@opencode-ai" / "plugin"
            sdk.mkdir(parents=True)
            (sdk / "package.json").write_text(
                json.dumps({
                    "name": "@opencode-ai/plugin",
                    "type": "module",
                    "exports": "./index.js",
                }),
                encoding="utf-8",
            )
            (sdk / "index.js").write_text(
                "const schema = () => ({ optional() { return this }, describe() { return this } })\n"
                "export const tool = (input) => input\n"
                "tool.schema = { enum: schema, string: schema, boolean: schema, "
                "object: schema, array: schema }\n",
                encoding="utf-8",
            )
            script = (
                "import(process.argv[1]).then(async m => {"
                "const plugin = await m.SdlcPipelinePlugin({directory: process.argv[2], worktree: '/'});"
                "const lifecycle = plugin.tool.sdlc_lifecycle;"
                "try {"
                "await lifecycle.execute({action: 'execute_test_plan'}, {agent: 'sdlc-executor'});"
                "process.exit(2);"
                "} catch (error) {"
                "if (!String(error).includes('cannot run lifecycle execute_test_plan')) throw error;"
                "}"
                "}).catch(e => { console.error(e); process.exit(1) })"
            )
            result = subprocess.run(
                ["node", "-e", script, plugin_path.as_uri(), str(target)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_plugin_ignores_filesystem_root_worktree_when_project_core_exists(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            plugin_path = target / ".opencode" / "plugins" / "sdlc-pipeline.js"
            plugin_path.parent.mkdir(parents=True)
            shutil.copy2(REPO / ".opencode/plugins/sdlc-pipeline.js", plugin_path)
            core = target / ".sdlc-pipeline" / "scripts" / "sdlc.py"
            core.parent.mkdir(parents=True)
            core.write_text("print('fixture')\n", encoding="utf-8")
            sdk = (
                target
                / ".opencode"
                / "node_modules"
                / "@opencode-ai"
                / "plugin"
            )
            sdk.mkdir(parents=True)
            (sdk / "package.json").write_text(
                json.dumps(
                    {
                        "name": "@opencode-ai/plugin",
                        "type": "module",
                        "exports": "./index.js",
                    }
                ),
                encoding="utf-8",
            )
            (sdk / "index.js").write_text(
                "const schema = () => ({"
                "optional() { return this }, describe() { return this }"
                "})\n"
                "export const tool = (input) => input\n"
                "tool.schema = { enum: schema, string: schema, boolean: schema, "
                "object: schema, array: schema }\n",
                encoding="utf-8",
            )
            script = (
                "import(process.argv[1]).then(m => {"
                "console.log(m.resolveProjectRoot({"
                "directory: process.argv[2], worktree: '/'"
                "}))"
                "}).catch(e => { console.error(e); process.exit(1) })"
            )
            result = subprocess.run(
                ["node", "-e", script, plugin_path.as_uri(), str(target)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(result.stdout.strip()).resolve(), target)

    def test_installation_marker_identifies_desktop_compatible_opencode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            installer.install(target)
            marker = json.loads((
                target / ".sdlc-pipeline/installation.json"
            ).read_text(encoding="utf-8"))
            self.assertEqual(marker["host"], "opencode")
            self.assertTrue(marker["desktop_compatible"])


if __name__ == "__main__":
    unittest.main()
