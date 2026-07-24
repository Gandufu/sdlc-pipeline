"""sdlc-pipeline 校验脚本共享库。

约定:
- 所有脚本从 stdin 读 Claude Code hook 输入(JSON),向 stdout 输出决策 JSON。
- 注入文本严守约束 #1:只陈述事实,不写命令式。
- 真值派生自产物存在性 + 矩阵,无 state.json(设计文档 §4.1)。
- 矩阵 docs/traceability-matrix.md 为 markdown 表格,列:R-id | D-id | C-id | T-id | 状态。
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any

# Windows 控制台默认 GBK,强制 UTF-8 IO,保证 hook 输出(中文事实陈述)不乱码。
for _stream in (sys.stdout, sys.stdin):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

DOCS_DIR_NAME = "docs"
REQUIREMENT_FILE = "requirement-spec.md"
DESIGN_FILE = "design-doc.md"
MATRIX_FILE = "traceability-matrix.md"

# design-doc §3 必填章节(G1 门禁)
DESIGN_REQUIRED_SECTIONS = ["模块划分", "接口/数据模型", "架构"]

# 交接块正则
HANDOFF_RE = re.compile(
    r"<!--\s*HANDOFF:(code|test)\b(?P<body>.*?)<!--\s*/HANDOFF\s*-->",
    re.DOTALL,
)
MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# 输入 / 输出
# ---------------------------------------------------------------------------
def read_hook_input() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def emit(obj: dict[str, Any]) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def project_dir(hook: dict[str, Any]) -> str:
    return hook.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def docs_dir(hook: dict[str, Any]) -> str:
    return os.path.join(project_dir(hook), DOCS_DIR_NAME)


def _path(hook: dict[str, Any], name: str) -> str:
    return os.path.join(docs_dir(hook), name)


# ---------------------------------------------------------------------------
# 产物读取
# ---------------------------------------------------------------------------
def read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def product_exists(hook: dict[str, Any], name: str) -> bool:
    return os.path.isfile(_path(hook, name))


def is_initialized(hook: dict[str, Any]) -> bool:
    """G0:CLAUDE.md 是否含 @docs/existing-framework.md。"""
    root = project_dir(hook)
    for cand in (os.path.join(root, "CLAUDE.md"), os.path.join(root, ".claude", "CLAUDE.md")):
        text = read_text(cand)
        if text and "@docs/existing-framework.md" in text:
            return True
    return False


# ---------------------------------------------------------------------------
# 矩阵解析(方案 I:脚本写,人只读)
# ---------------------------------------------------------------------------
@dataclass
class Matrix:
    rows: list[dict[str, str]] = field(default_factory=list)
    raw_header: str = ""

    def r_ids(self) -> list[str]:
        return [r["R"] for r in self.rows if r.get("R")]

    def d_ids(self) -> list[str]:
        return [r["D"] for r in self.rows if r.get("D")]

    def rows_by_d(self, d_id: str) -> list[dict[str, str]]:
        return [r for r in self.rows if r.get("D") == d_id]

    def r_to_d_closed(self) -> bool:
        requirement_rows = [r for r in self.rows if r.get("R")]
        return bool(requirement_rows) and all(r.get("D") for r in requirement_rows)

    def d_to_c_closed(self) -> bool:
        design_rows = [r for r in self.rows if r.get("D")]
        return bool(design_rows) and all(r.get("C") for r in design_rows)


def parse_matrix(hook: dict[str, Any]) -> Matrix:
    text = read_text(_path(hook, MATRIX_FILE)) or ""
    matrix = Matrix()
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        # 跳过表头(含 R-id / D-id 字样)
        if any("id" in c.lower() or "需求" in c or "设计" in c for c in cells[:2]):
            matrix.raw_header = matrix.raw_header or line
            continue
        # 兼容设计阶段把一个 R 映射到多个 D 的写法（D1、D3 / D1, D3）。
        # 内部统一展开为一行一个 R→D 映射，避免 H3 把整格误判成未知 D-id。
        d_ids = list(dict.fromkeys(d.upper() for d in re.findall(r"D\d+", cells[1], re.IGNORECASE)))
        if d_ids:
            for d_id in d_ids:
                matrix.rows.append(
                    {"R": cells[0], "D": d_id, "C": cells[2], "T": cells[3], "状态": cells[4]}
                )
        else:
            matrix.rows.append(
                {"R": cells[0], "D": cells[1], "C": cells[2], "T": cells[3], "状态": cells[4]}
            )
    return matrix


def write_matrix(hook: dict[str, Any], matrix: Matrix) -> None:
    lines = [
        "# 追溯矩阵 (Traceability Matrix)",
        "",
        "> 由 H3/H4 校验脚本 merge,零手改(设计文档 §5.1)。",
        "",
        "| R-id (需求) | D-id (设计) | C-id (代码模块/文件) | T-id (测试用例) | 状态 |",
        "|---|---|---|---|---|",
    ]
    for r in matrix.rows:
        lines.append(f"| {r['R']} | {r['D']} | {r['C']} | {r['T']} | {r['状态']} |")
    target = _path(hook, MATRIX_FILE)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".traceability-", suffix=".md", dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def merge_trace_into_matrix(hook: dict[str, Any], trace: dict[str, list[str]], status: str) -> None:
    """把 trace {D1:[C7 ...]} merge 进矩阵对应 D 行的 C 列。"""
    matrix = parse_matrix(hook)
    for d_id, c_list in trace.items():
        for row in matrix.rows_by_d(d_id):
            row["C"] = ", ".join(c_list)
            row["状态"] = status
    write_matrix(hook, matrix)


# ---------------------------------------------------------------------------
# 交接块解析
# ---------------------------------------------------------------------------
def parse_handoff(text: str) -> dict[str, Any] | None:
    """从文本中提取第一个 HANDOFF 块,解析为 dict。"""
    if not text:
        return None
    m = HANDOFF_RE.search(text)
    if not m:
        return None
    body = m.group("body")
    kind = m.group(1)
    result: dict[str, Any] = {"kind": kind, "raw": body}
    # compiled
    cm = re.search(r"compiled:\s*(\w+)", body)
    if cm:
        result["compiled"] = cm.group(1).lower()
    # files
    fm = re.search(r"files:\s*\n((?:\s*-\s*.+\n?)+)", body)
    if fm:
        result["files"] = re.findall(r"-\s*(.+)", fm.group(1))
    # trace
    tm = re.search(
        r"(?m)^trace:[ \t]*\r?\n"
        r"((?:^[ \t]+D\d+:[ \t]*\[[^\]\r\n]*\][ \t]*\r?\n?)+)",
        body,
        re.IGNORECASE,
    )
    if tm:
        trace: dict[str, list[str]] = {}
        for line in tm.group(1).splitlines():
            kv = re.match(r"\s*(D\d+):\s*\[(.*)\]", line, re.IGNORECASE)
            if kv:
                trace[kv.group(1).upper()] = [
                    c.strip() for c in kv.group(2).split(",") if c.strip()
                ]
        result["trace"] = trace
    # review-findings (test)
    if kind == "test":
        result["standards"] = _extract_axis(body, "standards")
        result["spec"] = _extract_axis(body, "spec")
    return result


def _extract_axis(body: str, axis: str) -> list[dict[str, str]]:
    """提取 review-findings 下某轴的条目(简易 parse)。"""
    block = re.search(rf"{axis}:\s*\n((?:\s+-\s*.+\n(?:\s+\S.*\n)*)+)", body)
    items: list[dict[str, str]] = []
    if not block:
        return items
    cur: dict[str, str] = {}
    for line in block.group(1).splitlines():
        m = re.match(r"\s+-\s+severity:\s*(\w+)", line)
        if m:
            if cur:
                items.append(cur)
            cur = {"severity": m.group(1).lower()}
            continue
        kv = re.match(r"\s+(\w+):\s*(.+)", line)
        if kv and cur:
            cur[kv.group(1)] = kv.group(2).strip()
    if cur:
        items.append(cur)
    return items


# ---------------------------------------------------------------------------
# design-doc 必填章节
# ---------------------------------------------------------------------------
def design_sections_present(hook: dict[str, Any]) -> tuple[list[str], list[str]]:
    """返回 (已存在且非空的章节, 缺失或为空的章节)。"""
    text = read_text(_path(hook, DESIGN_FILE)) or ""
    present, missing = [], []
    for sec in DESIGN_REQUIRED_SECTIONS:
        heading = re.search(
            rf"(?m)^#{{1,6}}\s+(?:\d+(?:\.\d+)*[.、]?\s*)?[^#\n]*{re.escape(sec)}[^\n]*$",
            text,
        )
        if heading:
            body_start = heading.end()
            next_heading = re.search(r"(?m)^#{1,6}\s+", text[body_start:])
            body_end = body_start + next_heading.start() if next_heading else len(text)
            body = text[body_start:body_end].strip()
        else:
            body = ""
        if body:
            present.append(sec)
        else:
            missing.append(sec)
    return present, missing


def requirement_ids(hook: dict[str, Any]) -> list[str]:
    """从需求文档提取稳定的 R-id。"""
    text = read_text(_path(hook, REQUIREMENT_FILE)) or ""
    return list(dict.fromkeys(re.findall(r"\bR\d+\b", text)))


def is_path_within_project(hook: dict[str, Any], path: str) -> bool:
    """路径解析后是否仍位于项目根目录内。"""
    root = os.path.realpath(project_dir(hook))
    candidate = path if os.path.isabs(path) else os.path.join(root, path)
    candidate = os.path.realpath(candidate)
    try:
        return os.path.commonpath([root, candidate]) == root
    except ValueError:
        return False


def is_docs_path(hook: dict[str, Any], path: str) -> bool:
    if not is_path_within_project(hook, path):
        return False
    root = os.path.realpath(project_dir(hook))
    candidate = path if os.path.isabs(path) else os.path.join(root, path)
    rel = os.path.relpath(os.path.realpath(candidate), root).replace("\\", "/")
    return rel == "docs" or rel.startswith("docs/")


def normalize_project_relative_path(hook: dict[str, Any], path: str) -> str | None:
    """返回规范化项目相对路径；越界、绝对路径或项目根本身返回 None。"""
    if not path or os.path.isabs(path) or not is_path_within_project(hook, path):
        return None
    root = os.path.realpath(project_dir(hook))
    candidate = os.path.realpath(os.path.join(root, path))
    rel = os.path.relpath(candidate, root).replace("\\", "/")
    if rel in ("", ".") or rel.startswith("../"):
        return None
    return rel


def git_changed_files(hook: dict[str, Any]) -> set[str] | None:
    """返回 git 中 tracked+untracked 的实际改动文件；非 git 工程返回 None。"""
    root = project_dir(hook)
    probe = subprocess.run(
        ["git", "-C", root, "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return None
    commands = (
        ["git", "-c", "core.quotepath=false", "-C", root, "diff", "--name-only", "--relative", "HEAD"],
        ["git", "-c", "core.quotepath=false", "-C", root, "ls-files", "--others", "--exclude-standard"],
    )
    changed: set[str] = set()
    for cmd in commands:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            return None
        changed.update(line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip())
    return changed


# ---------------------------------------------------------------------------
# 状态派生(无 state 文件)
# ---------------------------------------------------------------------------
@dataclass
class DerivedState:
    phase: str
    products: dict[str, bool]
    r_to_d_closed: bool
    d_to_c_closed: bool
    compiled: str
    missing_steps: list[str]

    def render(self) -> str:
        """事实陈述式派生视图(注入主会话)。"""
        prod = "、".join(k for k, v in self.products.items() if v) or "无"
        steps = ";".join(self.missing_steps) if self.missing_steps else "无前置阻塞"
        compiled = self.compiled or "未知"
        return (
            f"当前派生阶段:{self.phase}。"
            f"产物:{prod}。"
            f"追溯 R→D {'闭合' if self.r_to_d_closed else '未闭合'}、"
            f"D→C {'闭合' if self.d_to_c_closed else '未闭合'}。"
            f"编译:{compiled}。"
            f"未完成步骤:{steps}。"
        )


def derive_state(hook: dict[str, Any]) -> DerivedState:
    products = {
        "requirement-spec": product_exists(hook, REQUIREMENT_FILE),
        "design-doc": product_exists(hook, DESIGN_FILE),
        "traceability-matrix": product_exists(hook, MATRIX_FILE),
    }
    matrix = parse_matrix(hook)
    compiled = ""
    status_texts = " ".join(r.get("状态", "") for r in matrix.rows).lower()
    if "编译通过" in status_texts or "compiled=pass" in status_texts:
        compiled = "pass"
    elif "编译失败" in status_texts:
        compiled = "fail"

    phase, missing = _derive_phase(hook, products, matrix, compiled)
    return DerivedState(
        phase=phase,
        products=products,
        r_to_d_closed=matrix.r_to_d_closed() if matrix.rows else False,
        d_to_c_closed=matrix.d_to_c_closed() if matrix.rows else False,
        compiled=compiled,
        missing_steps=missing,
    )


def _derive_phase(hook, products, matrix, compiled) -> tuple[str, list[str]]:
    if not is_initialized(hook):
        return "未初始化", ["项目初始化产物尚未形成"]
    if not products["requirement-spec"]:
        return "需求中", ["docs/requirement-spec.md 尚不存在"]
    if not products["design-doc"]:
        return "设计中", ["docs/design-doc.md 尚不存在"]
    if not matrix.r_to_d_closed():
        return "设计中", ["追溯矩阵 R→D 映射尚未闭合"]
    if not matrix.d_to_c_closed():
        return "可编码", ["编码 agent 尚未形成完整 D→C 映射"]
    if compiled != "pass":
        return "编码中", ["编码结果尚未同时满足编译通过与 D→C 闭合"]
    # 编译通过且 D→C 闭合 → 可测试
    status_texts = " ".join(r.get("状态", "") for r in matrix.rows)
    if "走查发现阻塞" in status_texts:
        return "测试未通过", ["仍存在 high/medium 走查发现"]
    if "走查通过" not in status_texts and "review" not in status_texts.lower():
        return "可测试", ["测试 agent 走查结果尚未形成"]
    return "闭环", []


# ---------------------------------------------------------------------------
# 重试计数(SubagentStop 自纠正防死循环)
# ---------------------------------------------------------------------------
def retry_file(session_id: str, agent: str) -> str:
    import tempfile
    return os.path.join(tempfile.gettempdir(), f"sdlc-retry-{session_id}-{agent}.txt")


def get_retries(session_id: str, agent: str) -> int:
    try:
        with open(retry_file(session_id, agent), encoding="utf-8") as f:
            return int(f.read().strip() or "0")
    except OSError:
        return 0


def bump_retries(session_id: str, agent: str) -> int:
    n = get_retries(session_id, agent) + 1
    with open(retry_file(session_id, agent), "w", encoding="utf-8") as f:
        f.write(str(n))
    return n


def reset_retries(session_id: str, agent: str) -> None:
    try:
        os.remove(retry_file(session_id, agent))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 交接块文本提取(兼容 PostToolUse 的 tool_response 与 SubagentStop 的 JSONL transcript)
# ---------------------------------------------------------------------------
def _text_chunks(value: Any) -> list[str]:
    """递归提取 Agent/Task 工具响应中的文本块（兼容 Claude Code 2.1 content 数组）。"""
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value:
            chunks.extend(_text_chunks(item))
        return chunks
    if not isinstance(value, dict):
        return []

    # 按实际响应结构的优先级提取，避免把 status/agentId 等元数据字符串拼入正文。
    for key in ("text", "result", "output", "content", "message"):
        if key in value:
            chunks = _text_chunks(value[key])
            if chunks:
                return chunks
    return []


def extract_handoff_text(hook: dict[str, Any]) -> str:
    """从 hook 输入中提取可能含交接块的文本。

    来源优先级:
    1. last_assistant_message(当前 Claude Code SubagentStop)
    2. tool_response / tool_result(PostToolUse:Agent 返回文本)
    3. agent_transcript_path(SubagentStop 子代理 JSONL)
    4. transcript_path(旧版兼容)
    """
    last_message = hook.get("last_assistant_message")
    if isinstance(last_message, str) and last_message:
        return last_message

    for key in ("tool_response", "tool_result", "response"):
        val = hook.get(key)
        chunks = _text_chunks(val)
        if chunks:
            return "\n".join(chunks)

    for transcript_key in ("agent_transcript_path", "transcript_path"):
        tp = hook.get(transcript_key)
        if not tp or not os.path.isfile(tp):
            continue
        chunks: list[str] = []
        try:
            with open(tp, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # 仅收集 assistant(子代理)产出的文本
                    if rec.get("type") not in (None, "assistant"):
                        continue
                    msg = rec.get("message") or rec
                    content = msg.get("content")
                    if isinstance(content, str):
                        chunks.append(content)
                    elif isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                chunks.append(part.get("text", ""))
        except OSError:
            pass
        if chunks:
            return "\n".join(chunks)
    return ""


def agent_type_of(hook: dict[str, Any]) -> str:
    """从 Agent 工具事件或 SubagentStop 输入推断 agent 类型。"""
    ti = hook.get("tool_input") or {}
    if isinstance(ti, dict) and ti.get("subagent_type"):
        return str(ti["subagent_type"])
    for key in ("agent_type", "subagent_type"):
        if hook.get(key):
            return str(hook[key])
    return ""


def subagent_type_of(hook: dict[str, Any]) -> str:
    """向后兼容旧调用名。"""
    return agent_type_of(hook)


def is_coder(hook: dict[str, Any]) -> bool:
    return "coder" in agent_type_of(hook).lower()


def is_tester(hook: dict[str, Any]) -> bool:
    return "tester" in agent_type_of(hook).lower()


def additional_context(hook: dict[str, Any], text: str) -> dict[str, Any]:
    """按当前 Claude Code hook 合约构造事件专属上下文输出。"""
    event = str(hook.get("hook_event_name") or "")
    if not event:
        return {"systemMessage": text}
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": text,
        }
    }
