"""项目级安装与宿主接线的快速契约测试，不调用任何 LLM。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "scripts" / "install_project.py"
failures: list[str] = []
passes = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passes
    if condition:
        passes += 1
        print(f"PASS {name}")
    else:
        failures.append(f"{name}: {detail}")
        print(f"FAIL {name}: {detail}")


def run(*args: str, cwd: Path | None = None, input_text: str | None = None):
    return subprocess.run(
        args,
        cwd=cwd,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )


with tempfile.TemporaryDirectory(prefix="sdlc-project-install-") as temp:
    project = Path(temp)
    run("git", "init", "-q", str(project))
    result = run(
        sys.executable,
        str(INSTALLER),
        "--target",
        str(project),
        "--host",
        "all",
    )
    check("安装器成功", result.returncode == 0, result.stderr or result.stdout)

    installation = json.loads(
        (project / ".sdlc-pipeline" / "installation.json").read_text(encoding="utf-8")
    )
    check(
        "安装记录三宿主",
        installation.get("hosts") == ["claude", "codex", "opencode"],
        str(installation),
    )
    check("共享运行时存在", (project / ".sdlc-pipeline/scripts/derive_state.py").is_file())
    check("Codex 异步结果适配器存在", (project / ".sdlc-pipeline/scripts/validate_result.py").is_file())
    check(
        "运行时忽略 Python 缓存",
        "**/__pycache__/" in (project / ".sdlc-pipeline/.gitignore").read_text(encoding="utf-8"),
    )
    check("不创建项目 CODEX_HOME", not (project / ".codex-home").exists())
    check("不复制插件缓存", not (project / "plugins").exists())

    for phase in ("init", "requirement", "design", "code", "test", "verify"):
        codex_skill = project / f".agents/skills/sdlc-pipeline-{phase}/SKILL.md"
        claude_skill = project / f".claude/skills/sdlc-pipeline-{phase}/SKILL.md"
        opencode_skill = project / f".opencode/skills/sdlc-pipeline-{phase}/SKILL.md"
        for host, file in (
            ("Codex", codex_skill),
            ("Claude", claude_skill),
            ("OpenCode", opencode_skill),
        ):
            text = file.read_text(encoding="utf-8") if file.exists() else ""
            check(f"{host} {phase} frontmatter 位于首行", text.startswith("---\n"))
            check(f"{host} {phase} skill", f"name: sdlc-pipeline-{phase}" in text, text[:100])
            check(f"{host} {phase} 使用项目运行时", ".sdlc-pipeline" in text)
            check(f"{host} {phase} 无插件根变量", "${CLAUDE_PLUGIN_ROOT}" not in text)
            if phase == "design":
                check(
                    f"{host} design manifest 使用项目运行时",
                    "`.sdlc-pipeline/templates/manifest.json`" in text,
                )
            if phase == "verify":
                check(
                    f"{host} verify 非阶段验证",
                    "这是一个非阶段 skill" in text and "python tests/test_pipeline.py" in text,
                    text[:300],
                )

    codex_hooks = json.loads((project / ".codex/hooks.json").read_text(encoding="utf-8"))
    check("Codex 项目 hooks", "PreToolUse" in codex_hooks.get("hooks", {}))
    check(
        "Codex hooks 识别 Agent",
        any(
            group.get("matcher") == "Agent"
            for group in codex_hooks["hooks"]["PreToolUse"]
        ),
    )
    check(
        "Codex Windows hook 命令",
        all(
            "commandWindows" in handler
            for groups in codex_hooks["hooks"].values()
            for group in groups
            for handler in group.get("hooks", [])
        ),
    )

    claude_settings = json.loads(
        (project / ".claude/settings.json").read_text(encoding="utf-8")
    )
    check("Claude 项目 hooks 合并", "SessionStart" in claude_settings.get("hooks", {}))
    check("Claude coder agent", (project / ".claude/agents/sdlc-coder.md").is_file())

    check("OpenCode 本地 plugin", (project / ".opencode/plugins/sdlc-pipeline.js").is_file())
    check("OpenCode commands", (project / ".opencode/commands/sdlc-code.md").is_file())
    check("OpenCode verify command", (project / ".opencode/commands/sdlc-verify.md").is_file())
    tester = (project / ".opencode/agents/sdlc-tester.md").read_text(encoding="utf-8")
    check("OpenCode tester 禁止编辑", "edit: deny" in tester)
    check("OpenCode tester 禁止 shell", "bash: deny" in tester)

    syntax = run(
        "node",
        "--check",
        str(project / ".opencode/plugins/sdlc-pipeline.js"),
        cwd=project,
    )
    check("OpenCode adapter JS 语法", syntax.returncode == 0, syntax.stderr)

    state = run(
        sys.executable,
        str(project / ".sdlc-pipeline/scripts/inspect_pipeline.py"),
        "--project-root",
        str(project),
        cwd=project,
    )
    parsed = json.loads(state.stdout) if state.returncode == 0 else {}
    check(
        "安装后诊断可运行",
        state.returncode == 0 and parsed.get("phase") == "未初始化",
        state.stderr or state.stdout,
    )

    repeat = run(
        sys.executable,
        str(INSTALLER),
        "--target",
        str(project),
        "--host",
        "codex",
    )
    check("重复安装需显式 force", repeat.returncode != 0)

    forced = run(
        sys.executable,
        str(INSTALLER),
        "--target",
        str(project),
        "--host",
        "all",
        "--force",
    )
    check("force 可幂等升级", forced.returncode == 0, forced.stderr)

print(f"\n{passes} passed, {len(failures)} failed")
if failures:
    for failure in failures:
        print(f"- {failure}")
    raise SystemExit(1)
