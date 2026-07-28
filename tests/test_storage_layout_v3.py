from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from sdlc_core.artifacts import load_current_spec  # noqa: E402
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
                "level": "unit",
                "test_key": "unit",
                "selector": "tests/test_feature.py",
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

        self.assertEqual(pointer["state"], "ready")
        self.assertLess((candidate_root / "index.json").stat().st_size, MAX_INDEX_BYTES)
        self.assertNotIn("设备管理员可以查看设备系统信息", json.dumps(revision))
        for group in ("requirements", "designs", "verification"):
            for item in revision[group]:
                self.assertTrue(item["content_ref"].endswith(".md"))
                self.assertIsInstance(
                    read_markdown_record(self.fixture.root / item["content_ref"]),
                    dict,
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
