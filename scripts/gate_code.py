#!/usr/bin/env python3
"""H1: 进入编码前门禁 (G2)。

PreToolUse,matcher=Agent。仅当派发的是编码 agent(subagent_type 含 coder)时校验:
- requirement-spec 存在,且矩阵中每个 R 都有 D 映射(R→D 闭合)
- design-doc 必填章节齐(架构/模块划分/接口数据模型)

不通过 → permissionDecision: deny,理由为事实陈述(约束 #1)。
通过 → allow(放行由默认决定处理,输出空 JSON 不阻断)。
"""
import sys

import _lib  # type: ignore


def main() -> int:
    hook = _lib.read_hook_input()
    # matcher 只按工具名;非 Agent 或非 coder 不归本脚本管
    if hook.get("tool_name") != "Agent" or not _lib.is_coder(hook):
        _lib.emit({})
        return 0

    facts: list[str] = []
    if not _lib.is_initialized(hook):
        facts.append("项目未初始化(CLAUDE.md 缺 @docs/existing-framework.md)")
    if not _lib.product_exists(hook, _lib.REQUIREMENT_FILE):
        facts.append("docs/requirement-spec.md 不存在")
    if not _lib.product_exists(hook, _lib.DESIGN_FILE):
        facts.append("docs/design-doc.md 不存在")
    else:
        _, missing = _lib.design_sections_present(hook)
        if missing:
            facts.append(f'design-doc 缺少章节:{", ".join(missing)}')
    matrix = _lib.parse_matrix(hook)
    r_ids = _lib.requirement_ids(hook)
    matrix_r_ids = set(matrix.r_ids())
    if not matrix.rows:
        facts.append("追溯矩阵不存在、为空或不可解析")
    else:
        missing_r = [r for r in r_ids if r not in matrix_r_ids]
        if missing_r:
            facts.append(f"追溯矩阵缺少需求行:{', '.join(missing_r)}")
        if not matrix.r_to_d_closed():
            facts.append(f"追溯矩阵需求→设计有 {sum(1 for r in matrix.rows if r.get('R') and not r.get('D'))} 条未映射")

    if facts:
        state = _lib.derive_state(hook)
        reason = ";".join(facts) + f"。当前派生阶段:{state.phase}。"
        _lib.emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        })
        return 0

    _lib.emit({})
    return 0


if __name__ == "__main__":
    sys.exit(main())
