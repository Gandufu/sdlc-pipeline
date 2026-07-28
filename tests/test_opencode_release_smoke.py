from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "opencode_release_smoke", REPO / "scripts" / "run_opencode_release_smoke.py"
)
assert SPEC and SPEC.loader
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class OpenCodeReleaseSmokeTests(unittest.TestCase):
    def test_windows_uses_directly_spawnable_cmd_shim(self) -> None:
        self.assertEqual(smoke.default_opencode_executable("nt"), "opencode.cmd")
        self.assertEqual(smoke.default_opencode_executable("posix"), "opencode")

    def test_code_stage_asserts_native_coder_dispatch_and_delivery_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs = root / "logs"
            logs.mkdir()
            (logs / "04-sdlc-code.jsonl").write_text(
                '{"subagent_type":"sdlc-coder"}\n', encoding="utf-8"
            )
            runs = root / ".sdlc-pipeline" / "runs"
            attempts = runs / "journal" / "RUN-TEST" / "attempts" / "code"
            attempts.mkdir(parents=True)
            (attempts / "A000001.json").write_text(json.dumps({
                "step": "task-before:coder",
                "operation": "task-before",
                "state": "succeeded",
            }), encoding="utf-8")
            (runs / "coder-handoff.json").write_text(json.dumps({
                "summary": "implemented R-0001",
                "changed_files": ["src/feature.ts", "tests/feature.test.ts"],
            }), encoding="utf-8")
            (runs / "code-evidence.json").write_text(json.dumps({
                "ok": True,
                "compile": {"ok": True},
                "artifact_evidence": {"ok": True},
                "policy": {"ok": True, "verifiers": [
                    {"id": "lint", "ok": True},
                    {"id": "static-analysis", "ok": True},
                ]},
            }), encoding="utf-8")

            report = smoke.assert_code_stage(root, logs)

        self.assertTrue(report["ok"])
        self.assertEqual(report["task_target"], "sdlc-coder")
        self.assertEqual(report["task_before_after"], "succeeded")
        self.assertEqual(report["handoff_changed_files"], 2)

    def test_raw_opencode_tool_error_is_not_hidden_by_final_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            logs = Path(temporary)
            (logs / "02-sdlc-spec.jsonl").write_text(
                json.dumps({
                    "type": "tool_use",
                    "part": {
                        "tool": "sdlc_put_design",
                        "state": {
                            "status": "error",
                            "error": "unknown extension point",
                        },
                    },
                }) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(smoke.SmokeError, "tool error"):
                smoke.assert_no_raw_tool_errors(logs)

    def test_spec_argument_must_be_persisted_as_source_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / ".sdlc-pipeline" / "runs" / "sources"
            sources.mkdir(parents=True)
            (sources / "SRC-TEST.json").write_text(json.dumps({
                "source_id": "SRC-TEST",
                "content": "需求标记 SMOKE_ARGUMENT_PROBE_7F3A",
            }), encoding="utf-8")

            source = smoke.assert_spec_argument_source(
                root, "SMOKE_ARGUMENT_PROBE_7F3A"
            )
            self.assertEqual(source["source_id"], "SRC-TEST")
            with self.assertRaisesRegex(smoke.SmokeError, "Source Envelope"):
                smoke.assert_spec_argument_source(root, "missing-marker")
