#!/usr/bin/env python3
"""快速只读诊断：一次输出派生阶段、运行现场和 Git worktree 列表。"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import _lib
import _run_state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=os.getcwd())
    args = parser.parse_args()
    root = os.path.realpath(args.project_root)
    state = _lib.derive_state({"cwd": root})
    run = _run_state.load(root)
    worktrees = _run_state.worktrees(root)
    payload = {
        "project_root": root,
        "phase": state.phase,
        "products": state.products,
        "r_to_d_closed": state.r_to_d_closed,
        "d_to_c_closed": state.d_to_c_closed,
        "compiled": state.compiled or "unknown",
        "missing_steps": state.missing_steps,
        "run": run,
        "worktrees": worktrees,
        "unregistered_worktrees": [
            path for path in worktrees
            if path != root and path != os.path.realpath(str((run or {}).get("execution_root") or ""))
        ],
        "unfinished_artifacts": sorted(
            os.path.realpath(path)
            for path in glob.glob(os.path.join(root, "docs", "*.sdlc-tmp"))
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
