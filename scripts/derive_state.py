#!/usr/bin/env python3
"""H5/H6/H7: 通用派生状态注入主会话。

从产物存在性 + 矩阵实时派生"当前阶段 + 未完成步骤"(无 state 文件,设计文档 §4.1),
以事实陈述注入主会话(additionalContext)。

三个入口(H5 PostToolUse docs 写入 / H6 SessionStart / H7 PreCompact)共用同一份派生逻辑。
注入文本只陈述事实,不写命令式(约束 #1)。
"""
import sys

import _lib  # type: ignore


def main() -> int:
    hook = _lib.read_hook_input()

    # H5 专用过滤:仅当 Write|Edit 命中 docs/**/*.md 才注入
    tool_name = hook.get("tool_name", "")
    event = hook.get("hook_event_name", "")
    if event == "PostToolUse" and tool_name in ("Write", "Edit"):
        fp = ((hook.get("tool_input") or {}).get("file_path") or "")
        if "/docs/" not in fp.replace("\\", "/") and not fp.replace("\\", "/").startswith("docs/"):
            _lib.emit({})
            return 0

    state = _lib.derive_state(hook)
    _lib.emit(_lib.additional_context(hook, state.render()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
