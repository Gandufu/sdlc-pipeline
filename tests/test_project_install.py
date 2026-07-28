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
    contracts = root / ".sdlc-pipeline"
    contracts.mkdir()
    lifecycle_text = "{}\n"
    (contracts / "lifecycle.json").write_text(lifecycle_text, encoding="utf-8")
    scaffold = {
        "schema_version": "1.0",
        "template_id": template_id,
        "template_version": "1.0.0",
        "key_files": [],
        "protected_paths": [
            ".sdlc-pipeline/lifecycle.json",
            ".sdlc-pipeline/scaffold.json",
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
    def test_installs_opencode_surface_with_taskless_tester(self) -> None:
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
                path.relative_to(target / ".sdlc-pipeline/templates").as_posix()
                for path in (target / ".sdlc-pipeline/templates").rglob("*")
                if path.is_file()
            )
            self.assertEqual(installed_templates, ["manifest.json"])

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
                target / ".sdlc-pipeline/schemas/feature-contract.schema.json",
                target / ".sdlc-pipeline/schemas/spec.schema.json",
                target / ".sdlc-pipeline/scripts/sdlc_core/feature_contracts.py",
            ]
            for path in obsolete:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("obsolete", encoding="utf-8")

            installer.install(target, force=True)

            self.assertTrue(all(not path.exists() for path in obsolete))
            self.assertTrue(installer.install(target, force=True)["ok"])

    def test_installed_runtime_can_install_another_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first = base / "first"
            second = base / "second"
            first.mkdir()
            second.mkdir()
            installer.install(first)
            runtime_installer = first / ".sdlc-pipeline/scripts/install_project.py"
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
            self.assertTrue((target / ".sdlc-pipeline/scripts/sdlc.py").exists())

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
            self.assertTrue((project / ".sdlc-pipeline/lifecycle.json").exists())

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
            contracts = remote / ".sdlc-pipeline"
            contracts.mkdir()
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
            self.assertTrue((project / ".sdlc-pipeline/lifecycle.json").exists())

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
        self.assertEqual(files, ["manifest.json"])

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

    def test_coder_budget_and_adr_sequence_are_documented_consistently(self) -> None:
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        coder = (REPO / ".opencode/agents/sdlc-coder.md").read_text(
            encoding="utf-8"
        )
        adr_names = sorted(path.name for path in (REPO / "docs/adr").glob("*.md"))

        self.assertIn("最多 16 个 agent steps", readme)
        self.assertIn("steps: 16", coder)
        self.assertEqual(
            adr_names,
            [
                "0001-opencode-first.md",
                "0002-external-template-assets.md",
                "0003-schema-v2-candidates.md",
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

    def test_plugin_has_narrow_tools_without_experimental_injection(self) -> None:
        text = (REPO / ".opencode/plugins/sdlc-pipeline.js").read_text(encoding="utf-8")
        for name in (
            "sdlc_status", "sdlc_ingest_source", "sdlc_save_checkpoint",
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

    def test_agent_permission_matrix(self) -> None:
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")
        coder = (REPO / ".opencode/agents/sdlc-coder.md").read_text(encoding="utf-8")
        tester = (REPO / ".opencode/agents/sdlc-tester.md").read_text(encoding="utf-8")
        test_command = (REPO / ".opencode/commands/sdlc-test.md").read_text(encoding="utf-8")
        plugin = (REPO / ".opencode/plugins/sdlc-pipeline.js").read_text(encoding="utf-8")
        self.assertIn('"sdlc-coder": allow', main)
        self.assertIn("edit: allow", coder)
        self.assertIn("bash: deny", coder)
        self.assertIn('"*": deny', tester)
        self.assertNotIn('"sdlc-coder": allow', tester)
        self.assertIn("sdlc_lifecycle: allow", tester)
        self.assertIn("agent: sdlc-tester", test_command)
        self.assertIn('"sdlc-tester": ["verify_delivery"]', plugin)
        self.assertFalse((REPO / ".opencode/agents/sdlc-executor.md").exists())

    def test_spec_details_have_one_reference_source_of_truth(self) -> None:
        command = (REPO / ".opencode/commands/sdlc-spec.md").read_text(encoding="utf-8")
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")
        reference = (REPO / "references/spec-interview.md").read_text(encoding="utf-8")
        self.assertIn("references/spec-interview.md", command)
        self.assertNotIn("feature-contract.schema.json", command + main)
        self.assertIn("Schema v2", reference)
        self.assertIn("R/D/T/AC", reference)

    def test_checkpoint_guidance_uses_the_schema_payload(self) -> None:
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")
        reference = (REPO / "references/spec-interview.md").read_text(encoding="utf-8")
        plugin = (REPO / ".opencode/plugins/sdlc-pipeline.js").read_text(
            encoding="utf-8"
        )

        for text in (main, reference, plugin):
            self.assertIn("Q-0001", text)
            self.assertIn("state", text)
            self.assertIn("question", text)
        self.assertIn("status\":\"resolved", reference)
        self.assertIn("rationale", reference)
        self.assertIn("SRC-XXXXXXXXXXXX#anchor", reference + plugin)

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
        self.assertIn("code 阶段不运行依赖项目启动的 functional 测试", adapter)
        self.assertIn("steps: 16", coder)
        self.assertIn("temperature: 0.1", coder)
        self.assertIn('".sdlc-pipeline/scripts/**": deny', coder)
        self.assertIn("CODER_DEADLINE_SECONDS = 5 * 60", plugin)
        self.assertIn("output.args.prompt =", plugin)
        self.assertNotIn("output.args.prompt = `${output.args.prompt", plugin)
        self.assertIn("第 4 次工具调用前", coder)
        self.assertNotIn('output.args.command = "实现当前已发布', plugin)
        self.assertIn('"write-check"', plugin)
        cancel_index = plugin.index('await invoke(fallbackRoot, "task-cancel"')
        abort_index = plugin.index("await client.session.abort")
        self.assertLess(cancel_index, abort_index)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_coder_task_hook_keeps_short_objective_without_generic_command(self) -> None:
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
                "if sys.argv[1] == 'task-before':\n"
                "    print(json.dumps({'ok': True, 'context_pack': {'paths': ['.sdlc-pipeline/runs/context/coder-manifest.json'], 'characters': 1, 'resource_count': 1}, 'instruction': '只读取必要文件'}))\n"
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
                "import(process.argv[1]).then(async m => {"
                "const plugin = await m.SdlcPipelinePlugin({directory: process.argv[2], worktree: '/'});"
                "const output = {args: {description: '实现 R-0001 应用外壳', prompt: '调用方上下文不得复制', subagent_type: 'sdlc-coder'}};"
                "await plugin['tool.execute.before']({tool: 'task', sessionID: 'ses-test', callID: 'call-test'}, output);"
                "console.log(JSON.stringify(output.args));"
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
            args = json.loads(result.stdout)
            self.assertNotIn("command", args)
            self.assertIn("本次任务目标：实现 R-0001 应用外壳", args["prompt"])
            self.assertNotIn("调用方上下文不得复制", args["prompt"])

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
                root / ".sdlc-pipeline" / "runs" / "journal" / "RUN-TEST"
                / "attempts" / "spec"
            )
            attempts.mkdir(parents=True)
            for index in range(1, 15):
                failed = index == 1
                (attempts / f"A{index:06d}.json").write_text(
                    json.dumps({
                        "attempt_id": f"A{index:06d}",
                        "phase": "spec",
                        "step": "validate",
                        "state": "failed" if failed else "succeeded",
                        "started_at": f"2026-01-01T00:00:{index:02d}+00:00",
                        "finished_at": f"2026-01-01T00:00:{index:02d}+00:00",
                        "error": "early schema failure" if failed else None,
                        "result": None if failed else {"ok": True},
                    }),
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
        self.assertIn("逻辑测试键", text)
        self.assertIn("unit", text)
        self.assertIn("integration", text)

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
            core = target / ".sdlc-pipeline" / "scripts" / "sdlc.py"
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
