#!/usr/bin/env python3
"""限制插件 coder/tester agent 的写入边界。

Claude Code 的 agent tools 字段只能限制工具种类，不能限制 Write/Edit 的路径。
本 PreToolUse hook 提供确定性补强：
- tester: 禁止 Write/Edit/Bash，保持 fresh-eye 只读；
- coder: 禁止 Write/Edit docs/，并拒绝显式修改 docs/ 的 Bash 命令；
  Get-Content/cat/rg/git diff 等只读检查可以读取阶段文档。

coder 通过变量间接修改 docs/ 的情况由 H3 的 git diff 文件集复校兜底。
"""
from __future__ import annotations

import os
import re
import sys

import _lib  # type: ignore


def _deny(reason: str) -> None:
    _lib.emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    })


def _bash_may_mutate_docs(command: str) -> bool:
    """保守识别显式 docs 写入；未识别的间接写入仍由 H3 diff 兜底。"""
    normalized = command.replace("\\", "/").lower()
    enters_docs = re.search(
        r"(?:^|[;&|]\s*)cd\s+(?:['\"]?[^;&|]*?/)?docs(?:['\"]?)(?:\s|$|[;&|])",
        normalized,
    )
    references_docs = "docs/" in normalized or "/docs" in normalized or bool(enters_docs)
    if not references_docs:
        return False

    return _bash_has_mutation_signal(normalized)


def _bash_has_mutation_signal(command: str) -> bool:
    """识别常见 shell/PowerShell 文件变更信号。"""
    normalized = command.replace("\\", "/").lower()
    redirects_output = bool(re.search(r"(?<![0-9])>{1,2}", normalized))
    mutator = re.search(
        r"(?:^|[;&|]\s*|\s)"
        r"(?:rm|rmdir|del|erase|mv|move|cp|copy|touch|mkdir|"
        r"remove-item|move-item|copy-item|set-content|add-content|out-file|"
        r"new-item|clear-content|rename-item|tee|sed\s+-i|perl\s+-pi)"
        r"(?:\s|$)",
        normalized,
    )
    return redirects_output or bool(mutator)


def main() -> int:
    hook = _lib.read_hook_input()
    raw_tool = str(hook.get("tool_name") or "")
    tool = "Edit" if raw_tool == "apply_patch" else raw_tool
    if not (_lib.is_coder(hook) or _lib.is_tester(hook)):
        _lib.emit({})
        return 0

    if _lib.is_tester(hook) and tool in {"Write", "Edit"}:
        _deny(f"tester agent 为只读走查角色，不具备 {raw_tool or tool} 权限")
        return 0
    if _lib.is_tester(hook) and tool == "Bash":
        command = str((hook.get("tool_input") or {}).get("command") or "")
        if _bash_has_mutation_signal(command):
            _deny("tester agent 的 Bash 命令包含文件变更信号，只读边界无法保证")
        else:
            _lib.emit({})
        return 0

    if not _lib.is_coder(hook):
        _lib.emit({})
        return 0

    tool_input = hook.get("tool_input") or {}
    if raw_tool == "apply_patch":
        command = str(tool_input.get("command") or tool_input.get("patch") or "")
        paths = re.findall(
            r"^\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\s*$|^\*\*\* Move to:\s*(.+?)\s*$",
            command,
            re.MULTILINE,
        )
        flattened = [left or right for left, right in paths]
        if not flattened:
            _deny("coder agent 的 apply_patch 无法解析目标路径，写入边界无法保证")
            return 0
        for file_path in flattened:
            if _lib.is_docs_path(hook, file_path):
                _deny(f"coder agent 不可修改 docs/: {file_path}")
                return 0
        _lib.emit({})
        return 0

    if tool in {"Write", "Edit"}:
        file_path = str(tool_input.get("file_path") or "")
        if not file_path:
            _deny(f"coder agent 的 {tool} 缺少 file_path，无法确认写入边界")
            return 0
        if _lib.is_docs_path(hook, file_path):
            _deny(f"coder agent 不可修改 docs/: {file_path}")
            return 0

    if tool == "Bash":
        command = str(tool_input.get("command") or "")
        if _bash_may_mutate_docs(command):
            _deny("coder agent 的 Bash 命令可能修改 docs/，写入边界无法保证")
            return 0

    _lib.emit({})
    return 0


if __name__ == "__main__":
    sys.exit(main())
