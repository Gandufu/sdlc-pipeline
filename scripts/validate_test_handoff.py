#!/usr/bin/env python3
"""H4: 测试 agent 交接块校验与矩阵 merge。

两种入口模式(由 argv[1] 指定):
- subagentstop (H4a): 测试 agent 退出前自纠正。review-findings 两轴(standards/spec)
  必须都非空 + MVP 全链 R→D→C 闭合;不合规 → block 事实陈述,最多 MAX_RETRIES 次。
- posttooluse  (H4b): 测试 agent 已退出。复校通过后向矩阵标注走查状态 +
  向主会话注入摘要(additionalContext)。

交接块格式见 skills/code/references/handoff-format.md(双轴 review-findings)。
"""
import re
import sys

import _lib  # type: ignore

MODE = sys.argv[1] if len(sys.argv) > 1 else "posttooluse"


def _find_handoff_text(hook: dict) -> str:
    """委托 _lib.extract_handoff_text(兼容 PostToolUse / SubagentStop JSONL)。"""
    return _lib.extract_handoff_text(hook)


def _validate(hook: dict, handoff: dict | None) -> list[str]:
    if not handoff:
        return ["交接块未找到或不可 parse(需 <!-- HANDOFF:test ... -->)"]
    facts = []
    standards = handoff.get("standards") or []
    spec = handoff.get("spec") or []
    if not standards:
        facts.append("review-findings.standards 为空(走查 standards 轴未完成)")
    if not spec:
        facts.append("review-findings.spec 为空(走查 spec 轴未完成)")
    matrix = _lib.parse_matrix(hook)
    if not matrix.rows or not (matrix.r_to_d_closed() and matrix.d_to_c_closed()):
        facts.append("MVP 全链 R→D→C 未闭合")
    valid_severity = {"high", "medium", "low"}
    known_r = set(matrix.r_ids())
    known_c = set()
    for row in matrix.rows:
        known_c.update(re.findall(r"\bC\d+\b", row.get("C", "")))
    for axis, findings in (("standards", standards), ("spec", spec)):
        for index, finding in enumerate(findings, start=1):
            prefix = f"{axis}[{index}]"
            if finding.get("severity") not in valid_severity:
                facts.append(f"{prefix}.severity 非 high/medium/low")
            if not finding.get("target"):
                facts.append(f"{prefix}.target 缺失")
            elif known_c and not (set(re.findall(r"\bC\d+\b", finding["target"])) & known_c):
                facts.append(f"{prefix}.target 未引用已知 C-id")
            if not finding.get("issue"):
                facts.append(f"{prefix}.issue 缺失")
            if axis == "spec":
                requirement = finding.get("requirement")
                if not requirement:
                    facts.append(f"{prefix}.requirement 缺失")
                elif requirement not in known_r:
                    facts.append(f"{prefix}.requirement 不是已知 R-id:{requirement}")
    return facts


def main() -> int:
    hook = _lib.read_hook_input()
    if not _lib.is_tester(hook):
        _lib.emit({})
        return 0

    text = _find_handoff_text(hook)
    handoff = _lib.parse_handoff(text)
    facts = _validate(hook, handoff)
    session_id = hook.get("session_id", "session")

    if MODE == "subagentstop":
        if not facts:
            _lib.reset_retries(session_id, "tester")
            _lib.emit({"decision": "approve"})
            return 0
        n = _lib.bump_retries(session_id, "tester")
        if n > _lib.MAX_RETRIES:
            _lib.emit({"decision": "approve"})
            return 0
        reason = "交接块不合规:" + ";".join(facts) + f"。(自纠正 {n}/{_lib.MAX_RETRIES})"
        _lib.emit({"decision": "block", "reason": reason})
        return 0

    # posttooluse (H4b)
    if not facts and handoff:
        matrix = _lib.parse_matrix(hook)
        all_findings = (handoff.get("standards") or []) + (handoff.get("spec") or [])
        blocking = any(f.get("severity") in ("high", "medium") for f in all_findings)
        for row in matrix.rows:
            # 保留"编译通过"标记(编译是既成事实,G4 门禁已保证走查前 compiled=pass),
            # 否则 derive_state 会因丢失编译标记而误判阶段。
            row["状态"] = "走查发现阻塞,编译通过" if blocking else "走查通过,编译通过"
        _lib.write_matrix(hook, matrix)
        spec = handoff.get("spec") or []
        deviate = sum(1 for s in spec if s.get("severity") in ("high", "medium"))
        phase = "测试未通过" if blocking else "闭环"
        summary = (
            f"测试 agent 已退出。走查:发现 {len(spec)} 处 spec 记录(高/中 {deviate})。"
            f"全链追溯(MVP R→D→C):闭合,已标注走查状态。派生阶段:{phase}。"
        )
    else:
        note = ""
        if _lib.get_retries(session_id, "tester") > _lib.MAX_RETRIES:
            note = f"交接块经 {_lib.MAX_RETRIES} 次自纠正仍未合规,需人工介入。"
        summary = "测试 agent 已退出。交接块不合规:" + ";".join(facts) + ("。" + note if note else "。")

    _lib.reset_retries(session_id, "tester")
    _lib.emit(_lib.additional_context(hook, summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
