from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from sdlc_core.common import SdlcError  # noqa: E402
from sdlc_core.lifecycle_contract import (  # noqa: E402
    normalize_test_selector,
    suite_requires_runtime,
    validate_test_selector,
)


class LifecycleContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "tests" / "functional").mkdir(parents=True)
        (self.root / "tests" / "App.test.tsx").write_text(
            "export {};\n", encoding="utf-8"
        )
        (self.root / "tests" / "functional" / "T-0001.functional.ts").write_text(
            "export {};\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_v11_accepts_only_selector_matching_declared_suite_pattern(self) -> None:
        contract = {
            "schema_version": "1.1",
            "tests": {
                "unit": {
                    "allow_selector": True,
                    "selector_patterns": ["tests/*.test.tsx"],
                    "requires_runtime": False,
                },
            },
        }

        self.assertEqual(
            validate_test_selector(
                self.root,
                contract,
                "unit",
                "tests/App.test.tsx",
            ),
            "tests/App.test.tsx",
        )
        self.assertFalse(suite_requires_runtime(contract, "unit"))
        with self.assertRaisesRegex(SdlcError, "selector 不匹配"):
            normalize_test_selector(
                contract,
                "unit",
                "tests/functional/T-0001.functional.ts",
            )

    def test_v10_keeps_functional_default_and_runtime_requirement(self) -> None:
        contract = {
            "schema_version": "1.0",
            "tests": {"functional": {"allow_selector": True}},
        }

        self.assertEqual(
            normalize_test_selector(contract, "functional", None, test_id="T-0001"),
            "tests/functional/T-0001.functional.ts",
        )
        self.assertTrue(suite_requires_runtime(contract, "functional"))

    def test_v11_rejects_missing_or_out_of_project_selector(self) -> None:
        contract = {
            "schema_version": "1.1",
            "tests": {
                "unit": {
                    "allow_selector": True,
                    "selector_patterns": ["tests/*.test.tsx"],
                    "requires_runtime": False,
                },
            },
        }

        with self.assertRaisesRegex(SdlcError, "必须显式声明 selector"):
            normalize_test_selector(contract, "unit", None, test_id="T-0001")
        with self.assertRaisesRegex(SdlcError, "项目内路径"):
            normalize_test_selector(contract, "unit", "../outside.test.tsx")


if __name__ == "__main__":
    unittest.main()
