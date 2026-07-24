#!/usr/bin/env python3
"""SubagentStart:把宿主分配的 agent_id 绑定到当前 SDLC 运行角色。"""
from __future__ import annotations

import sys

import _lib
import _run_state


def main() -> int:
    hook = _lib.read_hook_input()
    record = _run_state.find_for_hook(hook)
    if not record:
        _lib.emit({})
        return 0
    phase = str(record.get("phase") or "")
    agent_id = hook.get("agent_id")
    agent_type = hook.get("agent_type")
    if phase in {"coding", "coder_spawning"}:
        _run_state.update(
            str(record.get("execution_root") or hook.get("cwd") or ""),
            phase="coding",
            coder_agent_id=agent_id,
            coder_agent_type=agent_type,
        )
    elif phase in {"testing", "tester_spawning"}:
        _run_state.update(
            str(record.get("execution_root") or hook.get("cwd") or ""),
            phase="testing",
            tester_agent_id=agent_id,
            tester_agent_type=agent_type,
        )
    _lib.emit({})
    return 0


if __name__ == "__main__":
    sys.exit(main())
