from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from .common import SdlcError, read_json


_ANNOTATIONS = {
    "$schema",
    "$id",
    "title",
    "description",
    "default",
    "examples",
}
_SUPPORTED = _ANNOTATIONS | {
    "$defs",
    "$ref",
    "type",
    "required",
    "properties",
    "additionalProperties",
    "propertyNames",
    "items",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minLength",
    "enum",
    "const",
    "pattern",
    "minimum",
    "maximum",
    "oneOf",
    "allOf",
    "if",
    "then",
    "else",
}


def schema_root(project_root: Path) -> Path:
    installed = project_root / ".sdlc-pipeline" / "runtime" / "schemas"
    if installed.is_dir():
        return installed
    distribution = Path(__file__).resolve().parents[2] / "schemas"
    if distribution.is_dir():
        return distribution
    raise SdlcError("找不到 SDLC JSON Schema 目录")


def validate_schema_instance(
    project_root: Path,
    schema_name: str,
    instance: Any,
) -> None:
    """Validate against the repository schema using its supported Draft 2020 subset.

    The validator fails closed when a schema uses an unsupported assertion keyword,
    so schema evolution cannot silently bypass runtime validation.
    """
    path = schema_root(project_root) / schema_name
    schema = read_json(path)
    if not isinstance(schema, dict):
        raise SdlcError(f"JSON Schema 必须是对象: {path}")
    expanded = _expand_local_refs(
        schema,
        document_path=path.resolve(),
        schemas_root=schema_root(project_root).resolve(),
        documents={path.resolve(): schema},
        stack=(),
    )
    _validate(instance, expanded, expanded, "$")


def check_schema_documents(project_root: Path) -> list[str]:
    """Parse every installed schema and resolve all local references without I/O outside it."""
    root = schema_root(project_root).resolve()
    checked: list[str] = []
    documents: dict[Path, dict[str, Any]] = {}
    for path in sorted(root.rglob("*.schema.json")):
        schema = read_json(path)
        if not isinstance(schema, dict):
            raise SdlcError(f"JSON Schema 必须是对象: {path}")
        documents[path.resolve()] = schema
    for path, schema in documents.items():
        _expand_local_refs(
            schema,
            document_path=path,
            schemas_root=root,
            documents=documents,
            stack=(),
        )
        checked.append(path.relative_to(root).as_posix())
    return checked


def _expand_local_refs(
    node: Any,
    *,
    document_path: Path,
    schemas_root: Path,
    documents: dict[Path, dict[str, Any]],
    stack: tuple[tuple[Path, str], ...],
) -> Any:
    if isinstance(node, list):
        return [
            _expand_local_refs(
                item,
                document_path=document_path,
                schemas_root=schemas_root,
                documents=documents,
                stack=stack,
            )
            for item in node
        ]
    if not isinstance(node, dict):
        return node
    reference = node.get("$ref")
    if reference is not None:
        if not isinstance(reference, str):
            raise SdlcError(f"JSON Schema $ref 必须是字符串: {reference!r}")
        file_part, marker, fragment = reference.partition("#")
        if file_part:
            if "://" in file_part or Path(file_part).is_absolute():
                raise SdlcError(f"禁止网络或绝对路径 JSON Schema $ref: {reference!r}")
            target_path = (document_path.parent / file_part).resolve()
            try:
                target_path.relative_to(schemas_root)
            except ValueError as exc:
                raise SdlcError(f"JSON Schema $ref 越出 schemas 根目录: {reference!r}") from exc
            target_document = documents.get(target_path)
            if target_document is None:
                target_document = read_json(target_path)
                if not isinstance(target_document, dict):
                    raise SdlcError(f"JSON Schema 必须是对象: {target_path}")
                documents[target_path] = target_document
        else:
            target_path = document_path
            target_document = documents[document_path]
        pointer = f"#{fragment}" if marker else "#"
        key = (target_path, pointer)
        if key in stack:
            raise SdlcError(f"JSON Schema $ref 存在循环: {reference!r}")
        target = _resolve_pointer(target_document, pointer)
        expanded = _expand_local_refs(
            copy.deepcopy(target),
            document_path=target_path,
            schemas_root=schemas_root,
            documents=documents,
            stack=(*stack, key),
        )
        siblings = {name: value for name, value in node.items() if name != "$ref"}
        if siblings:
            return {
                "allOf": [
                    expanded,
                    _expand_local_refs(
                        siblings,
                        document_path=document_path,
                        schemas_root=schemas_root,
                        documents=documents,
                        stack=stack,
                    ),
                ]
            }
        return expanded
    return {
        name: _expand_local_refs(
            value,
            document_path=document_path,
            schemas_root=schemas_root,
            documents=documents,
            stack=stack,
        )
        for name, value in node.items()
    }


def _resolve_pointer(document: dict[str, Any], pointer: str) -> Any:
    if pointer == "#":
        return document
    if not pointer.startswith("#/"):
        raise SdlcError(f"只允许 JSON Pointer fragment: {pointer!r}")
    value: Any = document
    for raw in pointer[2:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or key not in value:
            raise SdlcError(f"JSON Schema $ref 不存在: {pointer}")
        value = value[key]
    return value


def _validate(instance: Any, schema: Any, root: dict[str, Any], location: str) -> None:
    if isinstance(schema, bool):
        if not schema:
            raise SdlcError(f"{location} 被 JSON Schema 拒绝")
        return
    if not isinstance(schema, dict):
        raise SdlcError(f"非法 JSON Schema 节点: {location}")
    unknown = sorted(set(schema) - _SUPPORTED)
    if unknown:
        raise SdlcError(
            f"JSON Schema 使用了运行时未支持的关键字 {unknown}: {location}"
        )
    if "$ref" in schema:
        target = _resolve_ref(root, schema["$ref"])
        _validate(instance, target, root, location)
    if "allOf" in schema:
        for index, branch in enumerate(schema["allOf"]):
            _validate(instance, branch, root, f"{location}.allOf[{index}]")
    if "oneOf" in schema:
        matches = 0
        errors: list[str] = []
        for branch in schema["oneOf"]:
            try:
                _validate(instance, branch, root, location)
            except SdlcError as exc:
                errors.append(str(exc))
            else:
                matches += 1
        if matches != 1:
            detail = errors[0] if errors else "多个分支同时匹配"
            raise SdlcError(f"{location} 必须且只能匹配一个 oneOf 分支: {detail}")
    if "if" in schema:
        try:
            _validate(instance, schema["if"], root, location)
        except SdlcError:
            branch = schema.get("else")
        else:
            branch = schema.get("then")
        if branch is not None:
            _validate(instance, branch, root, location)

    if "const" in schema and instance != schema["const"]:
        raise SdlcError(f"{location} 必须等于 {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise SdlcError(f"{location} 不在允许值 {schema['enum']!r} 中")
    if "type" in schema and not _matches_type(instance, schema["type"]):
        raise SdlcError(f"{location} 类型必须是 {schema['type']!r}")

    if isinstance(instance, dict):
        required = schema.get("required", [])
        missing = [name for name in required if name not in instance]
        if missing:
            raise SdlcError(f"{location} 缺少 JSON Schema 字段: {missing}")
        properties = schema.get("properties", {})
        for name, value in instance.items():
            child = f"{location}.{name}"
            if name in properties:
                _validate(value, properties[name], root, child)
            else:
                additional = schema.get("additionalProperties", True)
                if additional is False:
                    raise SdlcError(f"{child} 是 JSON Schema 不允许的字段")
                if isinstance(additional, (dict, bool)):
                    _validate(value, additional, root, child)
        if "propertyNames" in schema:
            for name in instance:
                _validate(name, schema["propertyNames"], root, f"{location}.<key>")

    if isinstance(instance, list):
        if len(instance) < int(schema.get("minItems", 0)):
            raise SdlcError(f"{location} 至少需要 {schema['minItems']} 项")
        if "maxItems" in schema and len(instance) > int(schema["maxItems"]):
            raise SdlcError(f"{location} 最多允许 {schema['maxItems']} 项")
        if schema.get("uniqueItems"):
            normalized = [repr(value) for value in instance]
            if len(set(normalized)) != len(normalized):
                raise SdlcError(f"{location} 不允许重复项")
        if "items" in schema:
            for index, value in enumerate(instance):
                _validate(value, schema["items"], root, f"{location}[{index}]")

    if isinstance(instance, str):
        if len(instance) < int(schema.get("minLength", 0)):
            raise SdlcError(f"{location} 长度不能小于 {schema['minLength']}")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            raise SdlcError(f"{location} 不符合格式 {schema['pattern']}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            raise SdlcError(f"{location} 不能小于 {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            raise SdlcError(f"{location} 不能大于 {schema['maximum']}")


def _resolve_ref(root: dict[str, Any], reference: str) -> Any:
    if not isinstance(reference, str) or not reference.startswith("#/"):
        raise SdlcError(f"只允许当前文档内 JSON Schema $ref: {reference!r}")
    value: Any = root
    for raw in reference[2:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or key not in value:
            raise SdlcError(f"JSON Schema $ref 不存在: {reference}")
        value = value[key]
    return value


def _matches_type(value: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return any(_matches_type(value, item) for item in expected)
    checks = {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str),
        "boolean": lambda: isinstance(value, bool),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "null": lambda: value is None,
    }
    if expected not in checks:
        raise SdlcError(f"JSON Schema 使用了不支持的 type: {expected!r}")
    return checks[expected]()
