#!/usr/bin/env python3
"""把主会话写好的阶段产物临时文件原子发布到 docs/ 正式路径。"""
from __future__ import annotations

import argparse
import os
import sys


ALLOWED_TARGETS = {
    "requirement-spec.md",
    "design-doc.md",
    "traceability-matrix.md",
}


def _within(root: str, path: str) -> bool:
    try:
        return os.path.commonpath([root, path]) == root
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    root = os.path.realpath(args.project_root)
    docs = os.path.realpath(os.path.join(root, "docs"))
    source = os.path.realpath(args.source if os.path.isabs(args.source) else os.path.join(root, args.source))
    target = os.path.realpath(args.target if os.path.isabs(args.target) else os.path.join(root, args.target))
    if not (_within(docs, source) and _within(docs, target)):
        print("source/target 必须位于项目 docs/ 内", file=sys.stderr)
        return 2
    if os.path.basename(target) not in ALLOWED_TARGETS:
        print("target 不是允许的阶段产物", file=sys.stderr)
        return 2
    if not source.endswith(".sdlc-tmp") or not os.path.isfile(source):
        print("source 必须是已存在的 .sdlc-tmp 文件", file=sys.stderr)
        return 2
    os.makedirs(docs, exist_ok=True)
    os.replace(source, target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
