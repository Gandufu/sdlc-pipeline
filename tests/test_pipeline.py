#!/usr/bin/env python3
"""sdlc-pipeline 校验脚本单测(设计文档 §7 必测 7 条)。

自包含,无第三方依赖:`python tests/test_pipeline.py`。
覆盖确定性机器(脚本 + 拷贝 + 解析);LLM 驱动的 skill/agent 行为不纳入。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(PLUGIN_ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import _lib  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def run_script(script: str, payload: dict, *args: str) -> dict:
    cmd = [sys.executable, os.path.join(SCRIPTS, script), *args]
    p = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8")
    try:
        return json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        return {"_raw": p.stdout, "_err": p.stderr}


def context_text(output: dict) -> str:
    return (
        output.get("hookSpecificOutput", {}).get("additionalContext")
        or output.get("systemMessage")
        or ""
    )


def make_project(tmp: str) -> str:
    docs = os.path.join(tmp, "docs")
    os.makedirs(docs, exist_ok=True)
    with open(os.path.join(tmp, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("# p\n@docs/existing-framework.md\n")
    with open(os.path.join(docs, "requirement-spec.md"), "w", encoding="utf-8") as f:
        f.write("# 需求\n| R-id | 标题 |\n| R1 | 登录 |\n| R2 | 权限 |\n")
    with open(os.path.join(docs, "design-doc.md"), "w", encoding="utf-8") as f:
        f.write("# 设计\n## 2. 架构\nx\n## 3. 模块划分\nD1 D2\n## 4. 关键接口/数据模型\nx\n")
    with open(os.path.join(docs, "traceability-matrix.md"), "w", encoding="utf-8") as f:
        f.write("| R-id (需求) | D-id (设计) | C-id | T-id | 状态 |\n|---|---|---|---|---|\n"
                "| R1 | D1 | | | |\n| R2 | D2 | | | |\n")
    return tmp


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="sdlc-")
    proj = make_project(tmp)

    print("=== 1. gate_code: 齐全→放行; 缺章节→deny ===")
    out = run_script("gate_code.py", {"cwd": proj, "tool_name": "Agent",
                                      "tool_input": {"subagent_type": "x:coder"}})
    check("齐全放行", out == {}, f"got {out}")
    # 破坏 design-doc 章节
    with open(os.path.join(proj, "docs", "design-doc.md"), "w", encoding="utf-8") as f:
        f.write("# 设计\n无必填章节\n")
    out = run_script("gate_code.py", {"cwd": proj, "tool_name": "Agent",
                                      "tool_input": {"subagent_type": "x:coder"}})
    deny = out.get("hookSpecificOutput", {}).get("permissionDecision")
    check("缺章节deny", deny == "deny", f"got {out}")
    check("deny理由事实陈述(无'请'/'先')", "请" not in out.get("hookSpecificOutput", {}).get("permissionDecisionReason", ""), "")
    make_project(proj)  # 恢复

    print("=== 2. gate_code 空矩阵 + gate_test H3 未过→deny ===")
    os.remove(os.path.join(proj, "docs", "traceability-matrix.md"))
    out = run_script("gate_code.py", {"cwd": proj, "tool_name": "Agent",
                                      "tool_input": {"subagent_type": "x:coder"}})
    check("空矩阵deny", out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", f"got {out}")
    make_project(proj)
    out = run_script("gate_test.py", {"cwd": proj, "tool_name": "Agent",
                                      "tool_input": {"subagent_type": "x:tester"}})
    check("D→C未闭合deny", out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", f"got {out}")

    print("=== 3. validate_code_handoff: 当前 Agent/SubagentStop payload + merge ===")
    os.makedirs(os.path.join(proj, "src", "auth"), exist_ok=True)
    for fn in ("AuthController.java", "RbacService.java"):
        with open(os.path.join(proj, "src", "auth", fn), "w", encoding="utf-8") as f:
            f.write("// x")
    handoff = ("<!-- HANDOFF:code agent=c status=done -->\ncompiled: pass\nfiles:\n"
               "  - src/auth/AuthController.java\n  - src/auth/RbacService.java\ntrace:\n"
               "  D1: [C7 AuthController]\n  D2: [C8 RbacService]\nopen-issues: []\n<!-- /HANDOFF -->")
    out = run_script("validate_code_handoff.py",
                     {"cwd": proj, "hook_event_name": "SubagentStop", "agent_type": "sdlc-pipeline:coder",
                      "session_id": "subagent-current", "last_assistant_message": handoff},
                     "subagentstop")
    check("当前SubagentStop字段可识别", out.get("decision") == "approve", f"got {out}")
    out = run_script("validate_code_handoff.py",
                     {"cwd": proj, "hook_event_name": "PostToolUse", "tool_name": "Agent", "session_id": "t",
                      "tool_input": {"subagent_type": "x:coder"},
                      "tool_response": {"result": handoff}}, "posttooluse")
    check("merge后摘要合规", "合规" in context_text(out), f"got {out}")
    check("PostToolUse使用hookSpecificOutput", out.get("hookSpecificOutput", {}).get("hookEventName") == "PostToolUse", f"got {out}")
    m = _lib.parse_matrix({"cwd": proj})
    check("D→C已merge", m.d_to_c_closed(), "")
    make_project(proj)
    out = run_script(
        "validate_code_handoff.py",
        {"cwd": proj, "hook_event_name": "PostToolUse", "tool_name": "Agent",
         "session_id": "agent-content-array",
         "tool_input": {"subagent_type": "x:coder"},
         "tool_response": {
             "status": "completed",
             "content": [
                 {"type": "text", "text": f"核对完成。\n```markdown\n{handoff}\n```"},
                 {"type": "text", "text": "agentId: agent-123"},
             ],
         }},
        "posttooluse",
    )
    check("Claude Code 2.1 Agent content数组可提取交接块",
          "交接块格式:合规" in context_text(out), f"got {out}")
    if shutil.which("git"):
        git_proj = make_project(tempfile.mkdtemp(prefix="sdlc-git-"))
        subprocess.run(["git", "init", "-q", git_proj], check=True)
        subprocess.run(["git", "-C", git_proj, "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", git_proj, "config", "user.name", "SDLC Test"], check=True)
        subprocess.run(["git", "-C", git_proj, "add", "."], check=True)
        subprocess.run(["git", "-C", git_proj, "commit", "-qm", "baseline"], check=True)
        os.makedirs(os.path.join(git_proj, "src"), exist_ok=True)
        for fn in ("A.java", "B.java"):
            with open(os.path.join(git_proj, "src", fn), "w", encoding="utf-8") as f:
                f.write("// changed")
        incomplete = ("<!-- HANDOFF:code agent=c status=done -->\ncompiled: pass\nfiles:\n"
                      "  - src/A.java\ntrace:\n  D1: [C1 A]\n  D2: [C2 B]\n"
                      "open-issues: []\n<!-- /HANDOFF -->")
        out = run_script("validate_code_handoff.py",
                         {"cwd": git_proj, "hook_event_name": "PostToolUse", "tool_name": "Agent",
                          "session_id": "git-diff", "tool_input": {"subagent_type": "x:coder"},
                          "tool_response": {"result": incomplete}}, "posttooluse")
        check("git diff漏报被拒", "漏报 git 改动:src/B.java" in context_text(out), f"got {out}")
    else:
        check("git diff漏报被拒(git不可用时跳过)", True, "")

    print("=== 3b. 多 D-id 矩阵 + 未提交阶段 docs 不污染编码 diff ===")
    if shutil.which("git"):
        multi_proj = make_project(tempfile.mkdtemp(prefix="sdlc-multi-d-"))
        matrix_path = os.path.join(multi_proj, "docs", "traceability-matrix.md")
        with open(matrix_path, "w", encoding="utf-8") as f:
            f.write("| R-id (需求) | D-id (设计) | C-id | T-id | 状态 |\n"
                    "|---|---|---|---|---|\n"
                    "| R1 | D1、D3 | | | |\n"
                    "| R2 | D2, D3 | | | |\n")
        subprocess.run(["git", "init", "-q", multi_proj], check=True)
        subprocess.run(["git", "-C", multi_proj, "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", multi_proj, "config", "user.name", "SDLC Test"], check=True)
        subprocess.run(["git", "-C", multi_proj, "add", "."], check=True)
        subprocess.run(["git", "-C", multi_proj, "commit", "-qm", "baseline"], check=True)
        # requirement/design 阶段产物允许在进入编码时尚未提交；H3 只复校源码改动。
        with open(os.path.join(multi_proj, "docs", "design-doc.md"), "a", encoding="utf-8") as f:
            f.write("\n阶段设计补充\n")
        renderer = os.path.join(multi_proj, "packages", "renderer", "src")
        os.makedirs(renderer, exist_ok=True)
        for fn in ("Menu.tsx", "Settings.tsx", "Routes.tsx"):
            with open(os.path.join(renderer, fn), "w", encoding="utf-8") as f:
                f.write("// changed")
        multi_handoff = (
            "<!-- HANDOFF:code agent=c status=done -->\ncompiled: pass\nfiles:\n"
            "  - packages/renderer/src/Menu.tsx\n"
            "  - packages/renderer/src/Settings.tsx\n"
            "  - packages/renderer/src/Routes.tsx\n"
            "trace:\n"
            "  D1: [C1 Menu]\n"
            "  D2: [C2 Settings]\n"
            "  D3: [C3 Routes]\n"
            "open-issues: [基线工具链待处理]\n<!-- /HANDOFF -->"
        )
        parsed_multi_handoff = _lib.parse_handoff(multi_handoff)
        check("非空open-issues不被解析为D-id",
              parsed_multi_handoff is not None
              and "open-issues" not in parsed_multi_handoff.get("trace", {}),
              f"got {parsed_multi_handoff}")
        out = run_script(
            "validate_code_handoff.py",
            {"cwd": multi_proj, "hook_event_name": "PostToolUse", "tool_name": "Agent",
             "session_id": "multi-d", "tool_input": {"subagent_type": "x:coder"},
             "tool_response": {"result": multi_handoff}},
            "posttooluse",
        )
        check("中文/英文分隔的多D-id可merge",
              "交接块格式:合规" in context_text(out), f"got {out}")
        multi_matrix = _lib.parse_matrix({"cwd": multi_proj})
        check("多D-id拆分为独立映射",
              set(multi_matrix.d_ids()) == {"D1", "D2", "D3"}, f"got {multi_matrix.d_ids()}")
        check("阶段docs不计入coder files且D→C闭合",
              multi_matrix.d_to_c_closed(), f"got {multi_matrix.rows}")
    else:
        check("非空open-issues不被解析为D-id(git不可用时跳过)", True, "")
        check("中文/英文分隔的多D-id可merge(git不可用时跳过)", True, "")
        check("多D-id拆分为独立映射(git不可用时跳过)", True, "")
        check("阶段docs不计入coder files且D→C闭合(git不可用时跳过)", True, "")

    print("=== 4. validate_test_handoff: schema/阻塞语义/merge ===")
    th = ("<!-- HANDOFF:test agent=t status=done -->\nreview-findings:\n  standards:\n"
          "    - severity: low\n      target: C8\n      issue: 无\n  spec:\n"
          "    - severity: high\n      target: C8\n      issue: 偏离\n      requirement: R2\n<!-- /HANDOFF -->")
    out = run_script("validate_test_handoff.py",
                     {"cwd": proj, "hook_event_name": "PostToolUse", "tool_name": "Agent", "session_id": "t",
                      "tool_input": {"subagent_type": "x:tester"},
                      "tool_response": {"result": th}}, "posttooluse")
    check("走查merge摘要", "走查" in context_text(out), f"got {out}")
    m = _lib.parse_matrix({"cwd": proj})
    check("high finding标记阻塞", any("走查发现阻塞" in r["状态"] for r in m.rows), "")
    invalid = ("<!-- HANDOFF:test agent=t status=done -->\nreview-findings:\n  standards:\n"
               "    - severity: unknown\n      issue: x\n  spec:\n"
               "    - severity: low\n      target: C999\n      issue: x\n"
               "<!-- /HANDOFF -->")
    out = run_script("validate_test_handoff.py",
                     {"cwd": proj, "hook_event_name": "PostToolUse", "tool_name": "Agent",
                      "session_id": "invalid-test", "tool_input": {"subagent_type": "x:tester"},
                      "tool_response": {"result": invalid}}, "posttooluse")
    check("非法finding被拒", "不合规" in context_text(out), f"got {out}")

    print("=== 5. derive_state: 阻塞/闭环阶段 + 当前输出合约 ===")
    st = _lib.derive_state({"cwd": proj})
    check("高/中发现后测试未通过", st.phase == "测试未通过", f"got {st.phase}")
    th_pass = ("<!-- HANDOFF:test agent=t status=done -->\nreview-findings:\n  standards:\n"
               "    - severity: low\n      target: C7\n      issue: 无违反\n  spec:\n"
               "    - severity: low\n      target: C8\n      issue: 无偏离\n      requirement: R2\n<!-- /HANDOFF -->")
    run_script("validate_test_handoff.py",
               {"cwd": proj, "hook_event_name": "PostToolUse", "tool_name": "Agent",
                "session_id": "pass-test", "tool_input": {"subagent_type": "x:tester"},
                "tool_response": {"result": th_pass}}, "posttooluse")
    st = _lib.derive_state({"cwd": proj})
    check("低风险走查后闭环", st.phase == "闭环", f"got {st.phase}")
    out = run_script("derive_state.py", {"cwd": proj, "hook_event_name": "SessionStart"})
    check("SessionStart使用hookSpecificOutput", out.get("hookSpecificOutput", {}).get("hookEventName") == "SessionStart", f"got {out}")
    make_project(proj)  # 重置到可编码
    st2 = _lib.derive_state({"cwd": proj})
    check("可编码阶段", st2.phase == "可编码", f"got {st2.phase}")

    print("=== 6. agent 写入边界 ===")
    out = run_script("guard_agent_actions.py",
                     {"cwd": proj, "hook_event_name": "PreToolUse", "agent_type": "sdlc-pipeline:coder",
                      "tool_name": "Write", "tool_input": {"file_path": os.path.join(proj, "docs", "x.md")}})
    check("coder写docs被deny", out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", f"got {out}")
    out = run_script("guard_agent_actions.py",
                     {"cwd": proj, "hook_event_name": "PreToolUse", "agent_type": "sdlc-pipeline:coder",
                      "tool_name": "Write", "tool_input": {"file_path": os.path.join(proj, "src", "x.java")}})
    check("coder写src放行", out == {}, f"got {out}")
    out = run_script("guard_agent_actions.py",
                     {"cwd": proj, "hook_event_name": "PreToolUse", "agent_type": "sdlc-pipeline:tester",
                      "tool_name": "Bash", "tool_input": {"command": "git status"}})
    check("tester Bash被deny", out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", f"got {out}")

    print("=== 7. /init 拷贝语义(目录树/不覆盖/conventions不拷) ===")
    check("conventions与脚手架平级", os.path.isfile(os.path.join(PLUGIN_ROOT, "templates", "conventions", "spring-boot-full.md")), "")
    check("骨架含existing-framework", os.path.isfile(os.path.join(PLUGIN_ROOT, "templates", "spring-boot-full", "docs", "existing-framework.md")), "")
    check("脚手架目录不含conventions", not os.path.exists(os.path.join(PLUGIN_ROOT, "templates", "spring-boot-full", "conventions")), "")

    print("=== 8. manifest 解析: 路径派生/缺字段 ===")
    with open(os.path.join(PLUGIN_ROOT, "templates", "manifest.json"), encoding="utf-8") as f:
        mf = json.load(f)
    check("manifest非空", len(mf) >= 1, "")
    required = ("id", "name", "description", "stacks", "path", "conventions")
    check("所有条目含必备字段",
          all(all(k in entry for k in required) for entry in mf), "")
    check("脚手架ID唯一", len({entry["id"] for entry in mf}) == len(mf), "")
    check("所有path目录存在",
          all(os.path.isdir(os.path.join(PLUGIN_ROOT, entry["path"])) for entry in mf), "")
    check("所有conventions文件存在",
          all(os.path.isfile(os.path.join(PLUGIN_ROOT, entry["conventions"])) for entry in mf), "")
    check("所有stack规则存在",
          all(os.path.isfile(os.path.join(PLUGIN_ROOT, "rules", f"{stack}.md"))
              for entry in mf for stack in entry["stacks"]), "")

    heli = next((entry for entry in mf if entry["id"] == "heli-terminal-client"), None)
    check("heli脚手架已注册", heli is not None, "")
    if heli:
        heli_root = os.path.join(PLUGIN_ROOT, heli["path"])
        check("heli含能力清单",
              os.path.isfile(os.path.join(heli_root, "docs", "existing-framework.md")), "")
        with open(os.path.join(heli_root, "package.json"), encoding="utf-8") as f:
            heli_package = json.load(f)
        scripts = heli_package.get("scripts", {})
        check("heli根脚本固定使用packageManager版本",
              heli_package.get("packageManager") == "pnpm@9.0.0"
              and all("pnpm" not in command or "corepack pnpm" in command
                      for command in scripts.values()),
              f"scripts={scripts}")
        forbidden_names = {".claude", "node_modules", "dist", "out", "dist-installer"}
        forbidden = []
        for current, dirs, _files in os.walk(heli_root):
            for dirname in dirs:
                if dirname in forbidden_names:
                    forbidden.append(os.path.join(current, dirname))
        check("heli资产不含本机设置/依赖/构建产物",
              not forbidden, f"found={forbidden}")

    print(f"\n=== 结果: {PASS} passed, {FAIL} failed ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
