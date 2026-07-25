from __future__ import annotations

import importlib.util
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

    def test_install_preserves_unmanaged_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            custom = target / ".opencode" / "commands" / "custom.md"
            custom.parent.mkdir(parents=True)
            custom.write_text("mine", encoding="utf-8")
            installer.install(target)
            self.assertEqual(custom.read_text(encoding="utf-8"), "mine")

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
            with patch.object(raw, "_clone_distribution", return_value=REPO) as clone:
                result = raw.install_from_repository(
                    target, False, "https://example.invalid/sdlc-pipeline.git", "main"
                )
            clone.assert_called_once()
            self.assertTrue(result["ok"])
            self.assertTrue((target / ".sdlc-pipeline/scripts/sdlc.py").exists())

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

    def test_builtin_init_fills_the_current_plugin_project(self) -> None:
        import sys

        sys.path.insert(0, str(REPO / "scripts"))
        from sdlc_core.bootstrap import bootstrap

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            installer.install(project)
            expected_report = {"status": "pass", "tools": {"missing": []}}
            with patch(
                "sdlc_core.bootstrap._create_builtin_git_baseline",
                return_value="baseline-sha",
            ), patch("sdlc_core.lifecycle.init_project", return_value=expected_report):
                result = bootstrap(project, template="spring-boot-full")
            self.assertTrue(result["ok"])
            self.assertEqual(result["project_root"], str(project.resolve()))
            self.assertEqual(result["source"], {
                "kind": "builtin", "template": "spring-boot-full"
            })
            self.assertEqual(result["git_baseline"], "baseline-sha")
            self.assertTrue((project / "pom.xml").exists())
            self.assertTrue((project / ".sdlc-pipeline/lifecycle.json").exists())

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

    def test_templates_have_valid_hash_contracts(self) -> None:
        import sys

        sys.path.insert(0, str(REPO / "scripts"))
        from sdlc_core.lifecycle import load_contract
        from sdlc_core.trace import verify_scaffold

        for name in ("spring-boot-full", "heli-terminal-client"):
            root = REPO / "templates" / name
            self.assertTrue(verify_scaffold(root)["ok"], name)
            contract = load_contract(root)
            self.assertEqual(
                set(contract["tests"]),
                {"unit", "integration", "e2e", "lint", "static_analysis"},
            )

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

    def test_desktop_project_assets_are_discoverable(self) -> None:
        self.assertTrue((REPO / ".opencode/plugins/sdlc-pipeline.js").exists())
        self.assertTrue((REPO / ".opencode/skills/sdlc-pipeline/SKILL.md").exists())
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
        self.assertNotIn("<repo> <ref> <target>", init_command)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_plugin_javascript_syntax(self) -> None:
        subprocess.run(
            ["node", "--check", str(REPO / ".opencode/plugins/sdlc-pipeline.js")],
            check=True,
            capture_output=True,
            text=True,
        )

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
