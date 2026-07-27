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
    def test_installs_only_opencode_surface_and_two_subagents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            result = installer.install(target)
            self.assertTrue(result["ok"])
            self.assertEqual(result["host"], "opencode")
            agents = sorted(path.name for path in (target / ".opencode/agents").glob("*.md"))
            self.assertEqual(
                agents, ["sdlc-coder.md", "sdlc-executor.md", "sdlc-main.md"]
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
        schemas = list((REPO / "schemas").glob("*.schema.json"))
        self.assertGreaterEqual(len(schemas), 6)
        for path in schemas:
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_plugin_has_four_tools_without_experimental_injection(self) -> None:
        text = (REPO / ".opencode/plugins/sdlc-pipeline.js").read_text(encoding="utf-8")
        for name in ("sdlc_status", "sdlc_publish", "sdlc_lifecycle", "sdlc_finalize"):
            self.assertIn(name, text)
        self.assertNotIn("experimental.chat.messages.transform", text)
        self.assertNotIn("config.skills.paths", text)
        self.assertNotIn("sdlc-tester", text)

    def test_agent_permission_matrix(self) -> None:
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")
        coder = (REPO / ".opencode/agents/sdlc-coder.md").read_text(encoding="utf-8")
        executor = (REPO / ".opencode/agents/sdlc-executor.md").read_text(encoding="utf-8")
        self.assertIn('"sdlc-coder": allow', main)
        self.assertIn('"sdlc-executor": allow', main)
        self.assertIn("edit: allow", coder)
        self.assertIn("bash: deny", coder)
        self.assertIn("edit: deny", executor)
        self.assertIn("task: deny", executor)

    def test_spec_command_and_agent_require_schema_before_publish(self) -> None:
        command = (REPO / ".opencode/commands/sdlc-spec.md").read_text(encoding="utf-8")
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")
        for text in (command, main):
            self.assertIn(".sdlc-pipeline/schemas/spec.schema.json", text)
            self.assertIn("R-0001", text)

    def test_spec_generation_requires_chinese_formal_documents(self) -> None:
        command = (REPO / ".opencode/commands/sdlc-spec.md").read_text(encoding="utf-8")
        main = (REPO / ".opencode/agents/sdlc-main.md").read_text(encoding="utf-8")
        for text in (command, main):
            self.assertIn("正式文档使用中文", text)

    def test_coder_is_explicitly_routed_away_from_test_lifecycle_actions(self) -> None:
        coder = (REPO / ".opencode/agents/sdlc-coder.md").read_text(encoding="utf-8")
        plugin = (REPO / ".opencode/plugins/sdlc-pipeline.js").read_text(encoding="utf-8")
        adapter = (REPO / "scripts/sdlc_core/adapter.py").read_text(encoding="utf-8")
        self.assertIn("禁止调用 `run_tests` 或 `test`", coder)
        self.assertIn("coder：仅 `compile`、`health`", plugin)
        self.assertIn("coder 仅可调用 sdlc_lifecycle(action=compile 或 health)", adapter)

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
        for name in ("sdlc-main", "sdlc-coder", "sdlc-executor"):
            self.assertTrue((REPO / f".opencode/agents/{name}.md").exists())

    def test_readme_describes_current_project_init_and_github_template(self) -> None:
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        init_command = (
            REPO / ".opencode/commands/sdlc-init.md"
        ).read_text(encoding="utf-8")
        self.assertIn("项目目录内", readme)
        self.assertIn("/sdlc-init --github", readme)
        self.assertIn("raw.githubusercontent.com/Gandufu/sdlc-pipeline", readme)
        self.assertNotIn("<SDLC_PIPELINE_ROOT>", readme)
        self.assertIn("当前 OpenCode 项目根目录", init_command)
        self.assertIn("name/description/stacks/capabilities", init_command)
        self.assertIn("只有唯一匹配", init_command)
        self.assertNotIn("<repo> <ref> <target>", init_command)

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
                "tool.schema = { enum: schema, string: schema, boolean: schema }\n",
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
            self.assertEqual([item["operation"] for item in operations], ["task-after", "lifecycle"])
            self.assertEqual(operations[0]["payload"]["role"], "coder")
            self.assertEqual(
                operations[1]["payload"]["action"], "compile_restart_verify"
            )

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
                "tool.schema = { enum: schema, string: schema, boolean: schema }\n",
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
