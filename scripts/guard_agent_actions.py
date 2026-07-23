#!/usr/bin/env python3
"""限制插件 coder/tester agent 的写入边界。

Claude Code 的 agent tools 字段只能限制工具种类，不能限制 Write/Edit 的路径。
本 PreToolUse hook 提供确定性补强：
- tester: 禁止 Write/Edit/Bash，保持 fresh-eye 只读；
- coder: 禁止 Write/Edit docs/，并拒绝任何显式引用 docs/ 的 Bash 命令。

coder 通过变量间接修改 docs/ 的情况由 H3 的 git diff 文件集复校兜底。
"""
from __future__ import annotations

import os
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


def main() -> int:
    hook = _lib.read_hook_input()
    tool = str(hook.get("tool_name") or "")
    if not (_lib.is_coder(hook) or _lib.is_tester(hook)):
        _lib.emit({})
        return 0

    if _lib.is_tester(hook) and tool in {"Write", "Edit", "Bash"}:
        _deny(f"tester agent 为只读走查角色，不具备 {tool} 权限")
        return 0

    if not _lib.is_coder(hook):
        _lib.emit({})
        return 0

    tool_input = hook.get("tool_input") or {}
    if tool in {"Write", "Edit"}:
        file_path = str(tool_input.get("file_path") or "")
        if not file_path:
            _deny(f"coder agent 的 {tool} 缺少 file_path，无法确认写入边界")
            return 0
        if _lib.is_docs_path(hook, file_path):
            _deny(f"coder agent 不可修改 docs/: {file_path}")
            return 0

    if tool == "Bash":
        command = str(tool_input.get("command") or "").replace("\\", "/").lower()
        if "docs/" in command or "/docs" in command:
            _deny("coder agent 的 Bash 命令显式引用 docs/，写入边界无法保证")
            return 0

    _lib.emit({})
    return 0


if __name__ == "__main__":
    sys.exit(main())
