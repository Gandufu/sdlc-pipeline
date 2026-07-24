#!/usr/bin/env python3
"""H2: 进入测试前门禁 (G4)。

PreToolUse,matcher=Agent。仅当派发的是测试 agent(subagent_type 含 tester)时校验:
- G3 已通过:矩阵 D→C 全映射 + 编译 pass

不通过 → permissionDecision: deny,事实陈述。
"""
import sys

import _lib  # type: ignore
import _run_state  # type: ignore


def main() -> int:
    hook = _lib.read_hook_input()
    if hook.get("tool_name") != "Agent" or not _lib.is_tester(hook):
        _lib.emit({})
        return 0

    facts: list[str] = []
    matrix = _lib.parse_matrix(hook)
    if not matrix.rows:
        facts.append("追溯矩阵不存在或为空")
    else:
        if not matrix.d_to_c_closed():
            unmapped = sum(1 for r in matrix.rows if r.get("D") and not r.get("C"))
            facts.append(f"编码 agent 交接块 设计→代码追溯 未闭合({unmapped} 条 D 未映射)")
        state = _lib.derive_state(hook)
        if state.compiled != "pass":
            facts.append("编码 agent 编译未通过(compiled≠pass)")

    if facts:
        state = _lib.derive_state(hook)
        reason = "上一门禁未通过:" + ";".join(facts) + f"。当前派生阶段:{state.phase}。"
        _lib.emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        })
        return 0

    _run_state.update(_lib.project_dir(hook), phase="tester_spawning")
    _lib.emit({})
    return 0


if __name__ == "__main__":
    sys.exit(main())
