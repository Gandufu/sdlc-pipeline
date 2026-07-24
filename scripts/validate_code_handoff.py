#!/usr/bin/env python3
"""H3: 编码 agent 交接块校验与矩阵 merge。

两种入口模式(由 argv[1] 指定):
- subagentstop (H3a): 编码 agent 退出前自纠正。交接块不合规 → decision:block,
  以事实陈述注入子代理,agent 当场修正再退出;最多 MAX_RETRIES 次,超限放行并标注。
- posttooluse  (H3b): 编码 agent 已退出。parse 交接块 → merge D→C 进矩阵 +
  写编译状态 → 向主会话注入处理摘要(additionalContext)。

交接块格式见 skills/code/references/handoff-format.md。
"""
import os
import sys

import _lib  # type: ignore

MODE = sys.argv[1] if len(sys.argv) > 1 else "posttooluse"


def _find_handoff_text(hook: dict) -> str:
    """委托 _lib.extract_handoff_text(兼容 PostToolUse / SubagentStop JSONL)。"""
    return _lib.extract_handoff_text(hook)


def _validate(hook: dict, handoff: dict | None) -> list[str]:
    """返回事实陈述式问题列表;空=合规。"""
    if not handoff:
        return ["交接块未找到或不可 parse(需 <!-- HANDOFF:code ... -->)"]
    facts = []
    if handoff.get("compiled") != "pass":
        facts.append(f"compiled={handoff.get('compiled', '缺失')},未通过")
    trace = handoff.get("trace") or {}
    if not trace:
        facts.append("trace(D→C 映射)缺失")
    matrix = _lib.parse_matrix(hook)
    known_d = set(matrix.d_ids())
    for row in matrix.rows:
        d = row.get("D")
        if d and d not in trace:
            facts.append(f"{d} 未给出 C 映射")
    for d in trace:
        if d not in known_d:
            facts.append(f"trace 含未知 D-id:{d}")
    root = _lib.project_dir(hook)
    declared: set[str] = set()
    for f in handoff.get("files") or []:
        normalized = _lib.normalize_project_relative_path(hook, f)
        if not normalized:
            facts.append(f"files 路径越界或不是项目相对路径:{f}")
            continue
        declared.add(normalized)
        if normalized == "docs" or normalized.startswith("docs/"):
            facts.append(f"coder 不可修改 docs/:{normalized}")
        if not os.path.isfile(os.path.join(root, normalized)):
            facts.append(f"files 列出但磁盘不存在:{f}")
    if not declared:
        facts.append("files 为空")
    changed = _lib.git_changed_files(hook)
    if changed is not None:
        # requirement/design/matrix 由主会话和 hooks 拥有，不属于 coder 的 files 范围。
        # 这些阶段产物可在进入 /code 时尚未提交，不能污染源码真实性比对。
        changed = {path for path in changed if not _lib.is_docs_path(hook, path)}
    if changed is not None and declared != changed:
        missing = sorted(changed - declared)
        extra = sorted(declared - changed)
        if missing:
            facts.append(f"files 漏报 git 改动:{', '.join(missing)}")
        if extra:
            facts.append(f"files 多报非 git 改动:{', '.join(extra)}")
    return facts


def main() -> int:
    hook = _lib.read_hook_input()
    if not _lib.is_coder(hook):
        _lib.emit({})
        return 0

    text = _find_handoff_text(hook)
    handoff = _lib.parse_handoff(text)
    facts = _validate(hook, handoff)
    session_id = hook.get("session_id", "session")

    if MODE == "subagentstop":
        if not facts:
            _lib.reset_retries(session_id, "coder")
            _lib.emit({"decision": "approve"})
            return 0
        n = _lib.bump_retries(session_id, "coder")
        if n > _lib.MAX_RETRIES:
            # 防死循环:放行退出,交由 H3b 摘要标注人工介入
            _lib.emit({"decision": "approve"})
            return 0
        reason = "交接块不合规:" + ";".join(facts) + f"。(自纠正 {n}/{_lib.MAX_RETRIES})"
        _lib.emit({"decision": "block", "reason": reason})
        return 0

    # posttooluse (H3b): merge 矩阵 + 注入主会话摘要
    if not facts and handoff:
        trace = handoff.get("trace") or {}
        status = "编码完成,编译通过"
        _lib.merge_trace_into_matrix(hook, trace, status)
        state = _lib.derive_state(hook)
        d_total = len([r for r in _lib.parse_matrix(hook).rows if r.get("D")])
        d_mapped = len([r for r in _lib.parse_matrix(hook).rows if r.get("C")])
        summary = (
            f"编码 agent 已退出。交接块格式:合规。"
            f"编译:通过。追溯 D→C:{d_mapped}/{d_total},已 merge 入矩阵。"
            f"派生阶段:{state.phase}。"
        )
    else:
        note = ""
        if _lib.get_retries(session_id, "coder") > _lib.MAX_RETRIES:
            note = f"交接块经 {_lib.MAX_RETRIES} 次自纠正仍未合规,需人工介入。"
        summary = "编码 agent 已退出。交接块不合规:" + ";".join(facts) + ("。" + note if note else "。")

    _lib.reset_retries(session_id, "coder")
    _lib.emit(_lib.additional_context(hook, summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
