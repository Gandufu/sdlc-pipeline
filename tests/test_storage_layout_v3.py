from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from sdlc_core.artifacts import load_current_spec  # noqa: E402
from sdlc_core.artifact_documents import (  # noqa: E402
    markdown_file_sha256,
    markdown_sha256,
    read_artifact_document,
    render_artifact_document,
)
from sdlc_core.common import SdlcError  # noqa: E402
from sdlc_core.records import (  # noqa: E402
    MAX_INDEX_BYTES,
    read_compact_index,
    read_markdown_record,
)
from sdlc_core.sources import ingest_source, load_source  # noqa: E402
from sdlc_core.spec_candidates import (  # noqa: E402
    begin_candidate,
    candidate_status,
    load_candidate_revision,
    put_design,
    put_requirement,
    put_verification,
    validate_candidate,
)
from sdlc_core.spec_publisher import approve_and_promote  # noqa: E402
from tests.test_pipeline import ProjectFixture  # noqa: E402


class StorageLayoutV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ProjectFixture()
        receipt = ingest_source(
            self.fixture.root,
            {
                "kind": "inline",
                "source": "用户需求",
                "content": "设备管理员可以查看设备系统信息。",
                "segments": [{
                    "anchor": "requirement:system-info",
                    "text": "设备管理员可以查看设备系统信息。",
                }],
            },
        )
        self.source_ref = {
            "source_id": receipt["source_id"],
            "anchor": "requirement:system-info",
        }

    def tearDown(self) -> None:
        self.fixture.close()

    def _ready_candidate(self) -> tuple[str, dict]:
        created = begin_candidate(
            self.fixture.root,
            title="设备管理",
            source_refs=[self.source_ref],
        )
        candidate_id = created["candidate_id"]
        put_requirement(
            self.fixture.root,
            candidate_id,
            {
                "feature_id": "F-0001",
                "title": "查看系统信息",
                "goal": "管理员能够查看设备系统信息",
                "actor": "设备管理员",
                "scope": ["src", "tests"],
                "non_goals": ["修改系统信息"],
                "source_refs": [self.source_ref],
                "main_flow": ["进入系统信息页", "查看系统信息"],
                "alternate_flows": [],
                "acceptance_criteria": [{
                    "given": "设备在线",
                    "when": "管理员打开系统信息页",
                    "then": "展示系统信息",
                    "source_refs": [self.source_ref],
                }],
                "supersedes": None,
            },
        )
        put_design(
            self.fixture.root,
            candidate_id,
            {
                "title": "系统信息模块",
                "requirement_ids": ["R-0001"],
                "modules": [{
                    "name": "system-info",
                    "responsibility": "读取并展示系统信息",
                    "seam": "feature",
                }],
                "interfaces": [],
                "data_contracts": [],
                "extension_points": ["feature"],
                "decisions": ["复用 feature extension point"],
            },
        )
        put_verification(
            self.fixture.root,
            candidate_id,
            {
                "requirement_ids": ["R-0001"],
                "design_ids": ["D-0001"],
                "acceptance_criteria_ids": ["AC-R-0001-01"],
                "level": "functional",
                "test_key": "functional",
                "selector": "tests/functional/T-0001.functional.ts",
                "preconditions": "项目可编译",
                "expected": "断言系统信息可见",
                "mandatory": True,
            },
        )
        return candidate_id, validate_candidate(self.fixture.root, candidate_id)

    def test_candidate_revisions_are_indexes_to_markdown_not_content_json(self) -> None:
        candidate_id, ready = self._ready_candidate()
        candidate_root = (
            self.fixture.root
            / ".sdlc-pipeline"
            / "work"
            / "candidates"
            / candidate_id
        )
        pointer = read_compact_index(candidate_root / "index.json")
        revision = load_candidate_revision(
            self.fixture.root, candidate_id, ready["revision"]
        )
        encoded_revision = json.dumps(revision, ensure_ascii=False)

        self.assertEqual(pointer["state"], "ready")
        self.assertLess((candidate_root / "index.json").stat().st_size, MAX_INDEX_BYTES)
        self.assertNotIn("设备管理员可以查看设备系统信息", encoded_revision)
        self.assertNotIn('"title"', encoded_revision)
        self.assertNotIn('"goal"', encoded_revision)
        for group in ("requirements", "designs", "verification"):
            for item in revision[group]:
                self.assertTrue(item["content_ref"].endswith(".md"))
                document = self.fixture.root / item["content_ref"]
                self.assertIsInstance(
                    read_artifact_document(document, group), dict
                )
                self.assertNotIn("```json", document.read_text(encoding="utf-8"))
                self.assertEqual(item["sha256"], markdown_file_sha256(document))

    def test_verification_selector_is_generated_and_normalized(self) -> None:
        cases = [
            (None, "tests/functional/T-0001.functional.ts"),
            ("", "tests/functional/T-0001.functional.ts"),
            (
                r"tests\functional\system-info.functional.ts",
                "tests/functional/system-info.functional.ts",
            ),
        ]
        for supplied, expected in cases:
            created = begin_candidate(
                self.fixture.root,
                title="设备管理",
                source_refs=[self.source_ref],
            )
            verification = {
                "requirement_ids": ["R-0001"],
                "design_ids": ["D-0001"],
                "acceptance_criteria_ids": ["AC-R-0001-01"],
                "level": "functional",
                "test_key": "functional",
                "preconditions": "项目可编译",
                "expected": "断言系统信息可见",
                "mandatory": True,
            }
            if supplied is not None:
                verification["selector"] = supplied

            written = put_verification(
                self.fixture.root,
                created["candidate_id"],
                verification,
            )
            revision = load_candidate_revision(
                self.fixture.root,
                created["candidate_id"],
                written["revision"],
            )
            self.assertEqual(
                revision["verification"][0]["selector"],
                expected,
            )

    def test_approval_freezes_self_contained_markdown_baseline(self) -> None:
        candidate_id, ready = self._ready_candidate()
        published = approve_and_promote(
            self.fixture.root,
            candidate_id=candidate_id,
            content_hash=ready["content_hash"],
            confirmed=True,
        )
        baseline = (
            self.fixture.root
            / "docs"
            / "sdlc"
            / "baselines"
            / published["baseline_id"]
        )
        self.assertTrue((baseline / "requirements/R-0001.md").is_file())
        self.assertTrue((baseline / "sources").is_dir())
        self.assertFalse((self.fixture.root / "docs/sdlc/current").exists())

        shutil.rmtree(self.fixture.root / ".sdlc-pipeline/work")
        loaded = load_current_spec(self.fixture.root)
        self.assertEqual(loaded["requirements"]["items"][0]["id"], "R-0001")

    def test_candidate_publication_removes_temporary_spec_work(self) -> None:
        from sdlc_core.cli import execute

        execute(self.fixture.root, "publish", {
            "kind": "spec-work",
            "payload": {
                "question": {
                    "id": "Q-0001",
                    "prompt": "系统信息是否自动刷新？",
                    "answer": "需要",
                    "status": "resolved",
                    "rationale": "用户需看到当前设备状态",
                },
            },
        })
        candidate_id, ready = self._ready_candidate()

        published = execute(self.fixture.root, "spec-candidate", {
            "action": "approve",
            "candidate_id": candidate_id,
            "content_hash": ready["content_hash"],
            "confirmed": True,
        })

        self.assertTrue(published["spec_work_cleanup"]["deleted"])
        self.assertFalse(any(
            (self.fixture.root / ".sdlc-pipeline/work/runs").glob("*/spec-work.md")
        ))
        self.assertFalse(
            (
                self.fixture.root
                / ".sdlc-pipeline/work/candidates"
                / candidate_id
            ).exists()
        )
        receipt = read_compact_index(
            self.fixture.root
            / ".sdlc-pipeline/state/publications"
            / f"{candidate_id}.json"
        )
        self.assertEqual(receipt["cleanup_state"], "deleted")
        baseline = (
            self.fixture.root
            / "docs/sdlc/baselines"
            / published["baseline_id"]
        )
        self.assertTrue((baseline / "decisions/Q-0001.md").is_file())

        repeated = execute(self.fixture.root, "spec-candidate", {
            "action": "approve",
            "candidate_id": candidate_id,
            "content_hash": ready["content_hash"],
            "confirmed": True,
        })
        self.assertTrue(repeated["idempotent"])
        self.assertEqual(repeated["baseline_id"], published["baseline_id"])

    def test_status_retries_pending_publication_cleanup(self) -> None:
        from sdlc_core.cli import execute
        from sdlc_core.status import status

        candidate_id, ready = self._ready_candidate()
        with patch(
            "sdlc_core.spec_publisher.shutil.rmtree",
            side_effect=OSError("locked"),
        ):
            published = execute(self.fixture.root, "spec-candidate", {
                "action": "approve",
                "candidate_id": candidate_id,
                "content_hash": ready["content_hash"],
                "confirmed": True,
            })
        self.assertTrue(published["candidate_cleanup"]["cleanup_pending"])

        current = status(self.fixture.root)
        self.assertEqual(current["publication_cleanup"]["retried"], 1)
        self.assertEqual(current["publication_cleanup"]["pending"], 0)
        receipt = read_compact_index(
            self.fixture.root
            / ".sdlc-pipeline/state/publications"
            / f"{candidate_id}.json"
        )
        self.assertEqual(receipt["cleanup_state"], "deleted")

    def test_approval_rejects_decisions_changed_after_validation(self) -> None:
        from sdlc_core.cli import execute

        def save(answer: str) -> None:
            execute(self.fixture.root, "publish", {
                "kind": "spec-work",
                "payload": {
                    "question": {
                        "id": "Q-0001",
                        "prompt": "是否自动刷新？",
                        "answer": answer,
                        "status": "resolved",
                        "rationale": "这是可观察行为",
                    },
                },
            })

        save("进入页面时刷新")
        candidate_id, ready = self._ready_candidate()
        save("仅手动刷新")
        with self.assertRaisesRegex(SdlcError, "决策已变化"):
            execute(self.fixture.root, "spec-candidate", {
                "action": "approve",
                "candidate_id": candidate_id,
                "content_hash": ready["content_hash"],
                "confirmed": True,
            })

        refreshed = validate_candidate(self.fixture.root, candidate_id)
        published = execute(self.fixture.root, "spec-candidate", {
            "action": "approve",
            "candidate_id": candidate_id,
            "content_hash": refreshed["content_hash"],
            "confirmed": True,
        })
        decision = (
            self.fixture.root
            / "docs/sdlc/baselines"
            / published["baseline_id"]
            / "decisions/Q-0001.md"
        ).read_text(encoding="utf-8")
        self.assertIn("仅手动刷新", decision)
        self.assertNotIn("进入页面时刷新", decision)

    def test_native_artifact_round_trip_and_normalized_hash(self) -> None:
        requirement = {
            "schema_version": "3.0",
            "id": "R-0001",
            "feature_id": "F-0001",
            "title": "系统信息",
            "goal": "展示设备信息",
            "actor": "管理员",
            "scope": ["读取信息"],
            "non_goals": [],
            "source_refs": [self.source_ref],
            "decision_ids": ["Q-0001"],
            "main_flow": ["进入页面", "展示信息"],
            "alternate_flows": [{
                "name": "设备离线",
                "steps": ["展示连接错误"],
            }],
            "acceptance_criteria": [{
                "id": "AC-R-0001-01",
                "given": "设备在线",
                "when": "打开页面",
                "then": "显示系统信息",
                "source_refs": [self.source_ref],
            }],
            "supersedes": None,
        }
        path = self.fixture.root / "requirement.md"
        rendered = render_artifact_document("requirements", requirement)
        path.write_text(rendered, encoding="utf-8")
        self.assertEqual(
            read_artifact_document(path, "requirements"), requirement
        )
        crlf = rendered.replace("\n", "\r\n").replace(
            "## 目标\r\n", "## 目标   \r\n"
        )
        self.assertEqual(markdown_sha256(rendered), markdown_sha256(crlf))

    def test_design_and_verification_native_markdown_round_trip(self) -> None:
        design = {
            "schema_version": "3.0",
            "id": "D-0001",
            "title": "系统信息模块",
            "requirement_ids": ["R-0001"],
            "decision_ids": ["Q-0001"],
            "modules": [{
                "name": "system-info",
                "responsibility": "读取并展示系统信息",
                "seam": "feature",
            }],
            "interfaces": [{
                "name": "GET /system/version",
                "input": "Bearer token",
                "output": "SystemInfo",
                "errors": ["10007：未授权"],
            }],
            "data_contracts": [{
                "name": "SystemInfo",
                "fields": [{
                    "name": "model",
                    "type": "string",
                    "required": True,
                    "source_ref": "SRC-000000000000#text:1",
                }],
            }],
            "extension_points": ["feature"],
            "decisions": ["复用 feature extension point"],
        }
        verification = {
            "schema_version": "3.0",
            "id": "T-0001",
            "requirement_ids": ["R-0001"],
            "design_ids": ["D-0001"],
            "acceptance_criteria_ids": ["AC-R-0001-01"],
            "level": "functional",
            "test_key": "functional",
            "selector": "tests/functional/system-info.functional.ts",
            "preconditions": "应用已启动并连接设备",
            "expected": "页面显示系统信息",
            "mandatory": True,
            "test_basis": "acceptance",
            "intent": "验证用户可观察结果",
            "coverage": "覆盖在线设备主流程",
        }
        for group, value in (
            ("designs", design),
            ("verification", verification),
        ):
            path = self.fixture.root / f"{group}.md"
            path.write_text(
                render_artifact_document(group, value),
                encoding="utf-8",
            )
            self.assertEqual(read_artifact_document(path, group), value)

    def test_native_artifact_rejects_old_structured_record_and_heading_drift(
        self,
    ) -> None:
        old = self.fixture.root / "old.md"
        old.write_text(
            "# R-0001 old\n\n## Structured record\n\n"
            "<!-- sdlc-record:begin -->\n```json\n{}\n```\n"
            "<!-- sdlc-record:end -->\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(SdlcError, "frontmatter"):
            read_artifact_document(old, "requirements")

        candidate_id, ready = self._ready_candidate()
        revision = load_candidate_revision(
            self.fixture.root, candidate_id, ready["revision"]
        )
        record = revision["requirements"][0]
        path = self.fixture.root / record["content_ref"]
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace("## 目标", "## 角色", 1),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(SdlcError, "标题"):
            read_artifact_document(path, "requirements")

    def test_source_index_contains_only_offsets_hashes_and_references(self) -> None:
        source_root = next(
            (self.fixture.root / ".sdlc-pipeline/work/sources").iterdir()
        )
        index = read_compact_index(source_root / "index.json")
        encoded = json.dumps(index, ensure_ascii=False)
        self.assertNotIn("设备管理员可以查看设备系统信息", encoded)
        self.assertTrue(index["content_ref"].endswith("content.md"))
        self.assertEqual(index["anchors"][0]["anchor"], "requirement:system-info")

    def test_source_markdown_round_trips_trailing_newlines_exactly(self) -> None:
        content = "第一行\n第二行\n\n"
        receipt = ingest_source(
            self.fixture.root,
            {"kind": "inline", "source": "whitespace", "content": content},
        )
        loaded = load_source(self.fixture.root, receipt["source_id"])
        self.assertEqual(loaded["content"], content)

    def test_invalid_hash_does_not_publish(self) -> None:
        candidate_id, ready = self._ready_candidate()
        with self.assertRaisesRegex(SdlcError, "hash 不匹配"):
            approve_and_promote(
                self.fixture.root,
                candidate_id=candidate_id,
                content_hash="0" * 64,
                confirmed=True,
            )
        self.assertFalse((self.fixture.root / "docs/sdlc/current.json").exists())
        self.assertEqual(candidate_status(self.fixture.root)["state"], "ready")
