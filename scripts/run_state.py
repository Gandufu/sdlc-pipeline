#!/usr/bin/env python3
"""管理/查询一次 /code 运行现场；所有输出均为 JSON，便于人工和自动化排查。"""
from __future__ import annotations

import argparse
import json
import os
import sys

import _run_state


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start")
    start.add_argument("--project-root", required=True)
    start.add_argument("--execution-root", required=True)
    start.add_argument("--mode", choices=("worktree", "current"), required=True)

    status = sub.add_parser("status")
    status.add_argument("--project-root", default=os.getcwd())

    verify = sub.add_parser("verify-merge")
    verify.add_argument("--project-root", required=True)
    verify.add_argument("--target-root", required=True)

    abandon = sub.add_parser("abandon")
    abandon.add_argument("--project-root", required=True)

    args = parser.parse_args()
    if args.command == "start":
        try:
            record, resumed = _run_state.start(args.project_root, args.execution_root, args.mode)
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps({"ok": True, "resumed": resumed, "run": record}, ensure_ascii=False))
        return 0
    if args.command == "status":
        record = _run_state.load(args.project_root)
        registered_root = os.path.realpath(str((record or {}).get("execution_root") or ""))
        worktrees = _run_state.worktrees(args.project_root)
        unregistered = [path for path in worktrees if path != os.path.realpath(args.project_root)
                        and path != registered_root]
        print(json.dumps({
            "ok": True,
            "run": record,
            "worktrees": worktrees,
            "unregistered_worktrees": unregistered,
        }, ensure_ascii=False))
        return 0
    if args.command == "verify-merge":
        ok, mismatches = _run_state.verify_target(args.project_root, args.target_root)
        if ok:
            _run_state.update(args.project_root, phase="complete", merged_target=os.path.realpath(args.target_root))
        print(json.dumps({"ok": ok, "mismatches": mismatches}, ensure_ascii=False))
        return 0 if ok else 1
    if args.command == "abandon":
        record = _run_state.update(args.project_root, phase="abandoned")
        print(json.dumps({"ok": record is not None, "run": record}, ensure_ascii=False))
        return 0 if record else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
