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
            state = root / ".sdlc-pipeline" / "state"
            attempts = state / "runs" / "RUN-TEST" / "attempts" / "code"
            attempts.mkdir(parents=True)
            (attempts / "A000001.json").write_text(json.dumps({
                "step": "task-before:coder",
                "operation": "task-before",
                "state": "succeeded",
            }), encoding="utf-8")
            handoff = {
                "summary": "implemented R-0001",
                "changed_files": ["src/feature.ts", "tests/feature.test.ts"],
            }
            handoff_md = (
                root / ".sdlc-pipeline/work/records/coder-handoff.md"
            )
            handoff_md.parent.mkdir(parents=True)
            handoff_md.write_text(
                "# Handoff\n\n<!-- sdlc-record:begin -->\n```json\n"
                + json.dumps(handoff)
                + "\n```\n<!-- sdlc-record:end -->\n",
                encoding="utf-8",
            )
            handoff_index = state / "records" / "coder-handoff.json"
            handoff_index.parent.mkdir(parents=True)
            handoff_index.write_text(
                json.dumps({
                    "content_ref": (
                        ".sdlc-pipeline/work/records/coder-handoff.md"
                    ),
                }),
                encoding="utf-8",
            )
            code = {
                "ok": True,
                "compile": {"ok": True},
                "artifact_evidence": {"ok": True},
                "policy": {"ok": True, "verifiers": [
                    {"id": "lint", "ok": True},
                    {"id": "static-analysis", "ok": True},
                ]},
            }
            code_md = root / ".sdlc-pipeline/evidence/records/code.md"
            code_md.parent.mkdir(parents=True)
            code_md.write_text(
                "# Code\n\n<!-- sdlc-record:begin -->\n```json\n"
                + json.dumps(code)
                + "\n```\n<!-- sdlc-record:end -->\n",
                encoding="utf-8",
            )
            code_index = state / "evidence" / "code.json"
            code_index.parent.mkdir(parents=True)
            code_index.write_text(
                json.dumps({
                    "content_ref": (
                        ".sdlc-pipeline/evidence/records/code.md"
                    ),
                }),
                encoding="utf-8",
            )

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
            sources = (
                root / ".sdlc-pipeline" / "work" / "sources" / "SRC-TEST"
            )
            sources.mkdir(parents=True)
            (sources / "content.md").write_text(
                "# Source\n\n需求标记 SMOKE_ARGUMENT_PROBE_7F3A\n",
                encoding="utf-8",
            )
            (sources / "index.json").write_text(json.dumps({
                "source_id": "SRC-TEST",
                "content_ref": (
                    ".sdlc-pipeline/work/sources/SRC-TEST/content.md"
                ),
            }), encoding="utf-8")

            source = smoke.assert_spec_argument_source(
                root, "SMOKE_ARGUMENT_PROBE_7F3A"
            )
            self.assertEqual(source["source_id"], "SRC-TEST")
            with self.assertRaisesRegex(smoke.SmokeError, "Source Markdown"):
                smoke.assert_spec_argument_source(root, "missing-marker")
