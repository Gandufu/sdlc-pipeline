"""Contract-level test suite rules shared by Spec and lifecycle execution."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from .common import SdlcError


def _tests(contract: dict[str, Any]) -> dict[str, Any]:
    tests = contract.get("tests")
    if not isinstance(tests, dict):
        raise SdlcError("lifecycle.tests 必须是对象")
    return tests


def test_suite(contract: dict[str, Any], test_key: str) -> dict[str, Any]:
    suite = _tests(contract).get(test_key)
    if not isinstance(suite, dict):
        raise SdlcError(f"未知 lifecycle test_key: {test_key}")
    return suite


def _is_v11(contract: dict[str, Any]) -> bool:
    return contract.get("schema_version") == "1.1"


def validate_test_suites(contract: dict[str, Any]) -> None:
    """Validate semantic rules which are intentionally independent of JSON Schema."""
    tests = _tests(contract)
    if not tests:
        raise SdlcError("lifecycle.tests 至少需要声明一个测试套件")
    if _is_v11(contract) and "test_preflight" not in contract:
        raise SdlcError("lifecycle v1.1 必须声明 test_preflight")
    preflight = contract.get("test_preflight", [])
    if not isinstance(preflight, list):
        raise SdlcError("lifecycle.test_preflight 必须是数组")
    for index, command in enumerate(preflight):
        if not isinstance(command, dict):
            raise SdlcError(f"test_preflight[{index}] 必须是命令对象")
    for key, suite in tests.items():
        if not isinstance(key, str) or not key:
            raise SdlcError("lifecycle.tests 的 key 必须是非空字符串")
        if not isinstance(suite, dict):
            raise SdlcError(f"lifecycle.tests.{key} 必须是命令对象")
        if not _is_v11(contract):
            continue
        if not isinstance(suite.get("requires_runtime"), bool):
            raise SdlcError(
                f"lifecycle v1.1 tests.{key} 必须声明 requires_runtime"
            )
        if suite.get("allow_selector") is True:
            patterns = suite.get("selector_patterns")
            if (
                not isinstance(patterns, list)
                or not patterns
                or not all(isinstance(item, str) and item for item in patterns)
            ):
                raise SdlcError(
                    f"lifecycle v1.1 tests.{key} 必须声明 selector_patterns"
                )


def normalize_test_selector(
    contract: dict[str, Any],
    test_key: str,
    selector: str | None,
    *,
    test_id: str | None = None,
) -> str | None:
    """Normalize a Spec selector and enforce its contract-owned path policy."""
    suite = test_suite(contract, test_key)
    if suite.get("allow_selector") is not True:
        if selector not in (None, ""):
            raise SdlcError(f"{test_key} 不允许 selector")
        return None
    if selector is None or not selector.strip():
        if not _is_v11(contract) and test_key == "functional" and test_id:
            return f"tests/functional/{test_id}.functional.ts"
        raise SdlcError(f"{test_key} 必须显式声明 selector")
    normalized = selector.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or not normalized.startswith("tests/"):
        raise SdlcError(f"{test_key} selector 必须是 tests/ 下的项目内路径")
    if not _is_v11(contract):
        if (
            not normalized.startswith("tests/functional/")
            or not normalized.endswith(".functional.ts")
        ):
            raise SdlcError(
                f"{test_key} selector 必须是 tests/functional/ 下的 .functional.ts 项目内路径"
            )
        return normalized
    patterns = suite.get("selector_patterns")
    if not isinstance(patterns, list) or not patterns:
        raise SdlcError(f"lifecycle v1.1 tests.{test_key} 缺少 selector_patterns")
    if not any(path.match(pattern) for pattern in patterns):
        raise SdlcError(
            f"{test_key} selector 不匹配 lifecycle 声明的 selector_patterns: {normalized}"
        )
    return normalized


def validate_test_selector(
    root: Path,
    contract: dict[str, Any],
    test_key: str,
    selector: str | None,
    *,
    test_id: str | None = None,
) -> str | None:
    """Resolve a selector that is both contract-allowed and present on disk."""
    normalized = normalize_test_selector(
        contract, test_key, selector, test_id=test_id
    )
    if normalized is None:
        return None
    selector_path = root / normalized
    try:
        relative = selector_path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise SdlcError(
            f"{test_key} selector 必须是 tests/ 下的项目内路径: {normalized}"
        ) from exc
    if not selector_path.is_file() or relative.as_posix() != normalized:
        raise SdlcError(
            f"{test_key} selector 必须是已存在的 tests/ 项目内文件: {normalized}"
        )
    return normalized


def suite_requires_runtime(contract: dict[str, Any], test_key: str) -> bool:
    suite = test_suite(contract, test_key)
    if not _is_v11(contract):
        return True
    return bool(suite["requires_runtime"])


def test_plan_requires_runtime(
    contract: dict[str, Any],
    test_plan: list[dict[str, Any]],
) -> bool:
    return any(
        suite_requires_runtime(contract, item["command"])
        for item in test_plan
    )
