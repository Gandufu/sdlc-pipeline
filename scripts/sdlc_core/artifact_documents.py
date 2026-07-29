from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .common import SdlcError, atomic_write


TEMPLATE_VERSION = "1.0"
_NONE = "（无）"
_FRONTMATTER_LINE = re.compile(r"^([a-z][a-z0-9_]*):\s*(.+)$")
_TITLE_LINE = re.compile(r"^# ([RDT]-[0-9]{4})(?:\s+(.+))?$")


def normalize_markdown(text: str) -> str:
    """Return the canonical Markdown representation used by artifact hashes."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


def markdown_sha256(text: str) -> str:
    return hashlib.sha256(normalize_markdown(text).encode("utf-8")).hexdigest()


def markdown_file_sha256(path: Path) -> str:
    try:
        return markdown_sha256(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise SdlcError(f"无法读取 Markdown artifact: {path}") from exc


def write_artifact_document(path: Path, group: str, value: dict[str, Any]) -> dict[str, Any]:
    rendered = render_artifact_document(group, value)
    atomic_write(path, rendered)
    return {
        "path": path.as_posix(),
        "sha256": markdown_file_sha256(path),
        "size": path.stat().st_size,
    }


def render_artifact_document(group: str, value: dict[str, Any]) -> str:
    renderers = {
        "requirements": _render_requirement,
        "designs": _render_design,
        "verification": _render_verification,
    }
    renderer = renderers.get(group)
    if renderer is None:
        raise SdlcError(f"未知 artifact group: {group}")
    return normalize_markdown(renderer(value))


def read_artifact_document(path: Path, group: str) -> dict[str, Any]:
    if not path.is_file():
        raise SdlcError(f"缺少 Markdown artifact: {path}")
    parsers = {
        "requirements": _parse_requirement,
        "designs": _parse_design,
        "verification": _parse_verification,
    }
    parser = parsers.get(group)
    if parser is None:
        raise SdlcError(f"未知 artifact group: {group}")
    try:
        return parser(normalize_markdown(path.read_text(encoding="utf-8")))
    except SdlcError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise SdlcError(f"无法解析 Markdown artifact: {path}: {exc}") from exc


def render_candidate_document(candidate_id: str, title: str) -> str:
    frontmatter = _frontmatter({
        "schema_version": "3.0",
        "template_version": TEMPLATE_VERSION,
        "type": "candidate",
        "id": candidate_id,
    })
    return normalize_markdown(f"{frontmatter}\n# {candidate_id} {title}\n")


def read_candidate_title(path: Path) -> str:
    metadata, body = _parse_frontmatter(normalize_markdown(path.read_text(encoding="utf-8")))
    if metadata.get("type") != "candidate":
        raise SdlcError(f"Candidate Markdown type 不正确: {path}")
    first = body.splitlines()[0] if body else ""
    prefix = f"# {metadata.get('id')} "
    if not first.startswith(prefix) or not first[len(prefix):].strip():
        raise SdlcError(f"Candidate Markdown 标题不正确: {path}")
    return first[len(prefix):].strip()


def render_decision_document(decision: dict[str, Any], source_refs: list[str]) -> str:
    metadata = {
        "schema_version": "3.0",
        "template_version": TEMPLATE_VERSION,
        "type": "decision",
        "id": decision["id"],
        "source_refs": source_refs,
        "recorded_at": decision.get("recorded_at"),
    }
    return normalize_markdown(
        "\n".join([
            _frontmatter(metadata),
            f"# {decision['id']} {decision['prompt']}",
            "",
            "## 选择",
            "",
            str(decision["answer"]),
            "",
            "## 理由",
            "",
            str(decision["rationale"]),
        ])
    )


def _render_requirement(value: dict[str, Any]) -> str:
    metadata = {
        "schema_version": value["schema_version"],
        "template_version": TEMPLATE_VERSION,
        "type": "requirement",
        "id": value["id"],
        "feature_id": value["feature_id"],
        "source_refs": value["source_refs"],
        "decision_ids": value.get("decision_ids", []),
        "supersedes": value.get("supersedes"),
    }
    lines = [
        _frontmatter(metadata),
        f"# {value['id']} {value['title']}",
        "",
        "## 目标",
        "",
        value["goal"],
        "",
        "## 角色",
        "",
        value["actor"],
        "",
        "## 范围",
        "",
        *_bullets(value["scope"]),
        "",
        "## 非范围",
        "",
        *_bullets(value["non_goals"]),
        "",
        "## 主流程",
        "",
        *_numbered(value["main_flow"]),
        "",
        "## 异常流程",
        "",
    ]
    if value["alternate_flows"]:
        for flow in value["alternate_flows"]:
            lines.extend([
                f"### {flow['name']}",
                "",
                *_numbered(flow["steps"]),
                "",
            ])
    else:
        lines.extend([_NONE, ""])
    lines.extend(["## 验收标准", ""])
    for criterion in value["acceptance_criteria"]:
        lines.extend([
            f"#### {criterion['id']}",
            "",
            "##### Given",
            "",
            criterion["given"],
            "",
            "##### When",
            "",
            criterion["when"],
            "",
            "##### Then",
            "",
            criterion["then"],
            "",
            "##### Source refs",
            "",
            *_bullets([
                f"{item['source_id']}#{item['anchor']}"
                for item in criterion["source_refs"]
            ]),
            "",
        ])
    return "\n".join(lines)


def _parse_requirement(text: str) -> dict[str, Any]:
    metadata, body = _parse_frontmatter(text)
    _require_metadata(metadata, "requirement")
    title = _parse_title(body, metadata["id"])
    sections = _split_sections(
        body,
        ["目标", "角色", "范围", "非范围", "主流程", "异常流程", "验收标准"],
    )
    alternate_flows = []
    alternate = sections["异常流程"]
    if alternate != _NONE:
        for name, content in _split_subsections(alternate, 3):
            alternate_flows.append({"name": name, "steps": _parse_numbered(content)})
    criteria = []
    for index, (identifier, content) in enumerate(
        _split_subsections(sections["验收标准"], 4), 1
    ):
        expected_identifier = f"AC-{metadata['id']}-{index:02d}"
        if identifier != expected_identifier:
            raise SdlcError(f"非法 Acceptance Criteria 标题: {identifier}")
        fields = _split_named_headings(
            content, 5, ["Given", "When", "Then", "Source refs"]
        )
        criteria.append({
            "id": identifier,
            "given": fields["Given"],
            "when": fields["When"],
            "then": fields["Then"],
            "source_refs": _parse_source_ref_lines(fields["Source refs"]),
        })
    return {
        "schema_version": metadata["schema_version"],
        "id": metadata["id"],
        "feature_id": metadata["feature_id"],
        "title": title,
        "goal": sections["目标"],
        "actor": sections["角色"],
        "scope": _parse_bullets(sections["范围"]),
        "non_goals": _parse_bullets(sections["非范围"]),
        "source_refs": metadata["source_refs"],
        "decision_ids": metadata.get("decision_ids", []),
        "main_flow": _parse_numbered(sections["主流程"]),
        "alternate_flows": alternate_flows,
        "acceptance_criteria": criteria,
        "supersedes": metadata.get("supersedes"),
    }


def _render_design(value: dict[str, Any]) -> str:
    metadata = {
        "schema_version": value["schema_version"],
        "template_version": TEMPLATE_VERSION,
        "type": "design",
        "id": value["id"],
        "requirement_ids": value["requirement_ids"],
        "decision_ids": value.get("decision_ids", []),
    }
    lines = [
        _frontmatter(metadata),
        f"# {value['id']} {value['title']}",
        "",
        "## 模块",
        "",
    ]
    for module in value["modules"]:
        lines.extend([
            f"### {module['name']}",
            "",
            "#### 职责",
            "",
            module["responsibility"],
            "",
            "#### Seam",
            "",
            module["seam"],
            "",
        ])
    lines.extend(["## 接口", ""])
    if value["interfaces"]:
        for interface in value["interfaces"]:
            lines.extend([
                f"### {interface['name']}",
                "",
                "#### 输入",
                "",
                interface["input"],
                "",
                "#### 输出",
                "",
                interface["output"],
                "",
                "#### 错误",
                "",
                *_bullets(interface["errors"]),
                "",
            ])
    else:
        lines.extend([_NONE, ""])
    lines.extend(["## 数据契约", ""])
    if value["data_contracts"]:
        for contract in value["data_contracts"]:
            lines.extend([f"### {contract['name']}", ""])
            for field in contract["fields"]:
                lines.extend([
                    f"#### {field['name']}",
                    "",
                    f"- 类型：{field['type']}",
                    f"- 必填：{'true' if field['required'] else 'false'}",
                    f"- 来源：{field.get('source_ref') or _NONE}",
                    "",
                ])
    else:
        lines.extend([_NONE, ""])
    lines.extend([
        "## 扩展点",
        "",
        *_bullets(value["extension_points"]),
        "",
        "## 设计决策",
        "",
        *_bullets(value["decisions"]),
        "",
    ])
    return "\n".join(lines)


def _parse_design(text: str) -> dict[str, Any]:
    metadata, body = _parse_frontmatter(text)
    _require_metadata(metadata, "design")
    title = _parse_title(body, metadata["id"])
    sections = _split_sections(
        body, ["模块", "接口", "数据契约", "扩展点", "设计决策"]
    )
    modules = []
    for name, content in _split_subsections(sections["模块"], 3):
        fields = _split_named_headings(content, 4, ["职责", "Seam"])
        modules.append({
            "name": name,
            "responsibility": fields["职责"],
            "seam": fields["Seam"],
        })
    interfaces = []
    if sections["接口"] != _NONE:
        for name, content in _split_subsections(sections["接口"], 3):
            fields = _split_named_headings(content, 4, ["输入", "输出", "错误"])
            interfaces.append({
                "name": name,
                "input": fields["输入"],
                "output": fields["输出"],
                "errors": _parse_bullets(fields["错误"]),
            })
    data_contracts = []
    if sections["数据契约"] != _NONE:
        for name, content in _split_subsections(sections["数据契约"], 3):
            fields = []
            for field_name, field_content in _split_subsections(content, 4):
                lines = [line for line in field_content.splitlines() if line]
                values = _parse_prefixed_lines(
                    lines, {"类型": "type", "必填": "required", "来源": "source_ref"}
                )
                if values["required"] not in {"true", "false"}:
                    raise SdlcError("数据契约字段的必填值只能是 true/false")
                fields.append({
                    "name": field_name,
                    "type": values["type"],
                    "required": values["required"] == "true",
                    "source_ref": (
                        None if values["source_ref"] == _NONE else values["source_ref"]
                    ),
                })
            data_contracts.append({"name": name, "fields": fields})
    return {
        "schema_version": metadata["schema_version"],
        "id": metadata["id"],
        "title": title,
        "requirement_ids": metadata["requirement_ids"],
        "decision_ids": metadata.get("decision_ids", []),
        "modules": modules,
        "interfaces": interfaces,
        "data_contracts": data_contracts,
        "extension_points": _parse_bullets(sections["扩展点"]),
        "decisions": _parse_bullets(sections["设计决策"]),
    }


def _render_verification(value: dict[str, Any]) -> str:
    metadata = {
        "schema_version": value["schema_version"],
        "template_version": TEMPLATE_VERSION,
        "type": "verification",
        "id": value["id"],
        "requirement_ids": value["requirement_ids"],
        "design_ids": value["design_ids"],
        "acceptance_criteria_ids": value["acceptance_criteria_ids"],
        "level": value["level"],
        "test_key": value["test_key"],
        "selector": value.get("selector"),
        "mandatory": value["mandatory"],
        "test_basis": value.get("test_basis"),
    }
    return "\n".join([
        _frontmatter(metadata),
        f"# {value['id']} 验证",
        "",
        "## 验证意图",
        "",
        value.get("intent") or value["expected"],
        "",
        "## 前置条件",
        "",
        value["preconditions"],
        "",
        "## 预期结果",
        "",
        value["expected"],
        "",
        "## 覆盖说明",
        "",
        value.get("coverage") or (
            "覆盖 " + "、".join(value["acceptance_criteria_ids"])
        ),
        "",
    ])


def _parse_verification(text: str) -> dict[str, Any]:
    metadata, body = _parse_frontmatter(text)
    _require_metadata(metadata, "verification")
    _parse_title(body, metadata["id"])
    sections = _split_sections(
        body, ["验证意图", "前置条件", "预期结果", "覆盖说明"]
    )
    value = {
        "schema_version": metadata["schema_version"],
        "id": metadata["id"],
        "requirement_ids": metadata["requirement_ids"],
        "design_ids": metadata["design_ids"],
        "acceptance_criteria_ids": metadata["acceptance_criteria_ids"],
        "level": metadata["level"],
        "test_key": metadata["test_key"],
        "selector": metadata.get("selector"),
        "preconditions": sections["前置条件"],
        "expected": sections["预期结果"],
        "mandatory": metadata["mandatory"],
    }
    if metadata.get("test_basis") is not None:
        value["test_basis"] = metadata["test_basis"]
    if sections["验证意图"] != sections["预期结果"]:
        value["intent"] = sections["验证意图"]
    default_coverage = "覆盖 " + "、".join(metadata["acceptance_criteria_ids"])
    if sections["覆盖说明"] != default_coverage:
        value["coverage"] = sections["覆盖说明"]
    return value


def _frontmatter(values: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in values.items():
        if value is None and key not in {"supersedes", "selector", "test_basis"}:
            continue
        lines.append(
            f"{key}: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"
        )
    lines.append("---")
    return "\n".join(lines)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise SdlcError("Markdown artifact 缺少 frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise SdlcError("Markdown artifact frontmatter 未结束") from exc
    values: dict[str, Any] = {}
    for line in lines[1:end]:
        match = _FRONTMATTER_LINE.fullmatch(line)
        if match is None:
            raise SdlcError(f"非法 frontmatter 行: {line!r}")
        try:
            values[match.group(1)] = json.loads(match.group(2))
        except json.JSONDecodeError as exc:
            raise SdlcError(f"frontmatter 值必须是 JSON-compatible YAML: {line!r}") from exc
    return values, "\n".join(lines[end + 1:]).strip()


def _require_metadata(metadata: dict[str, Any], kind: str) -> None:
    if metadata.get("type") != kind:
        raise SdlcError(f"Markdown artifact type 必须是 {kind}")
    if metadata.get("template_version") != TEMPLATE_VERSION:
        raise SdlcError(
            f"Markdown artifact template_version 必须是 {TEMPLATE_VERSION}"
        )


def _parse_title(body: str, identifier: str) -> str:
    first = body.splitlines()[0] if body else ""
    match = _TITLE_LINE.fullmatch(first)
    if match is None or match.group(1) != identifier:
        raise SdlcError(f"Markdown artifact H1 必须以 {identifier} 开头")
    title = (match.group(2) or "").strip()
    if not title:
        raise SdlcError(f"Markdown artifact {identifier} 缺少标题")
    return title


def _split_sections(body: str, names: list[str]) -> dict[str, str]:
    lines = body.splitlines()
    positions = []
    for name in names:
        heading = f"## {name}"
        matches = [index for index, line in enumerate(lines) if line == heading]
        if len(matches) != 1:
            raise SdlcError(f"Markdown artifact 必须且只能包含一个标题: {heading}")
        positions.append(matches[0])
    if positions != sorted(positions):
        raise SdlcError(f"Markdown artifact 标题顺序不正确: {names}")
    result = {}
    for index, name in enumerate(names):
        start = positions[index] + 1
        end = positions[index + 1] if index + 1 < len(positions) else len(lines)
        content = "\n".join(lines[start:end]).strip()
        if not content:
            raise SdlcError(f"Markdown artifact 章节不能为空: {name}")
        result[name] = content
    return result


def _split_subsections(content: str, level: int) -> list[tuple[str, str]]:
    marker = "#" * level + " "
    lines = content.splitlines()
    positions = [index for index, line in enumerate(lines) if line.startswith(marker)]
    if not positions:
        raise SdlcError(f"Markdown artifact 缺少 {marker.strip()} 子标题")
    result = []
    for offset, position in enumerate(positions):
        name = lines[position][len(marker):].strip()
        end = positions[offset + 1] if offset + 1 < len(positions) else len(lines)
        body = "\n".join(lines[position + 1:end]).strip()
        if not name or not body:
            raise SdlcError(f"Markdown artifact 子标题或正文为空: {name!r}")
        result.append((name, body))
    return result


def _split_named_headings(
    content: str, level: int, names: list[str]
) -> dict[str, str]:
    sections = _split_subsections(content, level)
    actual = [name for name, _ in sections]
    if actual != names:
        raise SdlcError(f"Markdown artifact 子标题顺序不正确: {actual} != {names}")
    return dict(sections)


def _bullets(items: list[str]) -> list[str]:
    if not items:
        return [f"- {_NONE}"]
    return [f"- {_single_line(item)}" for item in items]


def _numbered(items: list[str]) -> list[str]:
    return [f"{index}. {_single_line(item)}" for index, item in enumerate(items, 1)]


def _single_line(value: Any) -> str:
    text = str(value)
    if "\n" in text or "\r" in text:
        raise SdlcError("Markdown 列表项不能包含换行")
    return text


def _parse_bullets(content: str) -> list[str]:
    lines = [line for line in content.splitlines() if line]
    if lines == [f"- {_NONE}"] or content == _NONE:
        return []
    if not lines or any(not line.startswith("- ") for line in lines):
        raise SdlcError("Markdown artifact 列表必须使用 '- '")
    return [line[2:] for line in lines]


def _parse_numbered(content: str) -> list[str]:
    lines = [line for line in content.splitlines() if line]
    values = []
    for expected, line in enumerate(lines, 1):
        prefix = f"{expected}. "
        if not line.startswith(prefix):
            raise SdlcError("Markdown artifact 有序列表必须从 1 连续编号")
        values.append(line[len(prefix):])
    return values


def _parse_source_ref_lines(content: str) -> list[dict[str, str]]:
    result = []
    for reference in _parse_bullets(content):
        source_id, separator, anchor = reference.partition("#")
        if not separator or not source_id or not anchor:
            raise SdlcError(f"非法 source ref: {reference}")
        result.append({"source_id": source_id, "anchor": anchor})
    return result


def _parse_prefixed_lines(
    lines: list[str], mapping: dict[str, str]
) -> dict[str, str]:
    result = {}
    for label, key in mapping.items():
        prefix = f"- {label}："
        matches = [line[len(prefix):] for line in lines if line.startswith(prefix)]
        if len(matches) != 1 or not matches[0]:
            raise SdlcError(f"Markdown artifact 缺少字段: {label}")
        result[key] = matches[0]
    return result
