from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from sdlc_core.common import SdlcError  # noqa: E402
from sdlc_core.schema_validation import validate_schema_instance  # noqa: E402


class SchemaValidationTests(unittest.TestCase):
    def test_lifecycle_v11_enforces_nonempty_test_suites(self) -> None:
        contract = {
            "schema_version": "1.1",
            "project_type": "fixture",
            "tools": [],
            "commands": {
                name: {"argv": ["python"]}
                for name in ("install", "compile", "package", "start")
            },
            "health": [{"type": "process"}],
            "artifacts": ["out/**"],
            "test_preflight": [],
            "tests": {"unit": {"argv": ["python"]}},
        }

        validate_schema_instance(REPO, "lifecycle.schema.json", contract)

        empty_suites = deepcopy(contract)
        empty_suites["tests"] = {}
        with self.assertRaisesRegex(SdlcError, r"\$\.tests 至少需要 1 个字段"):
            validate_schema_instance(REPO, "lifecycle.schema.json", empty_suites)


if __name__ == "__main__":
    unittest.main()
