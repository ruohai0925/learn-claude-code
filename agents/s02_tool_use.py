#!/usr/bin/env python3
# Harness: tool dispatch -- expanding what the model can reach.
"""
s02_tool_use.py - Tools

The agent loop from s01 didn't change. We just added tools to the array
and a dispatch map to route calls.

    +----------+      +-------+      +------------------+
    |   User   | ---> |  LLM  | ---> | Tool Dispatch    |
    |  prompt  |      |       |      | {                |
    +----------+      +---+---+      |   bash: run_bash |
                          ^          |   read: run_read |
                          |          |   write: run_wr  |
                          +----------+   edit: run_edit |
                          tool_result| }                |
                                     +------------------+

Key insight: "The loop didn't change at all. I just added tools."
"""

import json
import os
import subprocess
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks. Act, don't explain."


# ── 打印工具（和 s01 一样）──────────────────────────────────

CYAN    = "\033[36m"
YELLOW  = "\033[33m"
GREEN   = "\033[32m"
MAGENTA = "\033[35m"
DIM     = "\033[2m"
BOLD    = "\033[1m"
RESET   = "\033[0m"

def separator(label):
    print(f"\n{MAGENTA}{'─'*20} {label} {'─'*20}{RESET}")

def print_messages(messages):
    print(f"{DIM}messages = [{RESET}")
    for i, msg in enumerate(messages):
        role = msg["role"]
        content = msg["content"]
        if isinstance(content, str):
            text_preview = content[:80] + ("..." if len(content) > 80 else "")
            print(f"{DIM}  [{i}] {role}: \"{text_preview}\"{RESET}")
        elif isinstance(content, list):
            for block in content:
                if hasattr(block, "type") and not isinstance(block, dict):
                    if block.type == "text":
                        text_preview = block.text[:80] + ("..." if len(block.text) > 80 else "")
                        print(f"{DIM}  [{i}] {role}/text: \"{text_preview}\"{RESET}")
                    elif block.type == "tool_use":
                        print(f"{DIM}  [{i}] {role}/tool_use: {block.name}({json.dumps(block.input, ensure_ascii=False)[:80]}){RESET}")
                elif isinstance(block, dict) and block.get("type") == "tool_result":
                    c = str(block["content"])
                    c_preview = c[:80] + ("..." if len(c) > 80 else "")
                    print(f"{DIM}  [{i}] {role}/tool_result: \"{c_preview}\"{RESET}")
    print(f"{DIM}]{RESET}")

def print_response(response):
    print(f"{GREEN}response.stop_reason = \"{response.stop_reason}\"{RESET}")
    print(f"{GREEN}response.content = [{RESET}")
    for block in response.content:
        if block.type == "text":
            text_preview = block.text[:120] + ("..." if len(block.text) > 120 else "")
            print(f"{GREEN}  TextBlock: \"{text_preview}\"{RESET}")
        elif block.type == "tool_use":
            print(f"{GREEN}  ToolUseBlock: name=\"{block.name}\", id=\"{block.id}\"{RESET}")
            print(f"{GREEN}    input={json.dumps(block.input, ensure_ascii=False)[:200]}{RESET}")
    print(f"{GREEN}]{RESET}")


# ── s02 新增：路径安全沙箱 ───────────────────────────────────
#
# s01 只有 bash，LLM 可以通过 bash 访问整台机器的任何文件。
# s02 新增了 read_file / write_file / edit_file 这些专用工具，
# 它们都经过 safe_path() 检查，确保只能操作工作目录内的文件。
#
# 为什么不直接用 bash 读写文件？
#   1. bash 的 cat/sed 遇到特殊字符容易出错
#   2. bash 无法做路径限制——LLM 可以 cat /etc/passwd
#   3. 专用工具的参数结构清晰，LLM 更不容易犯格式错误

def safe_path(p: str) -> Path:
    """将相对路径转为绝对路径，并检查是否在工作目录内。

    例：safe_path("greet.py") → /home/user/project/greet.py  ✓
        safe_path("../../etc/passwd") → 抛出 ValueError       ✗
    """
    path = (WORKDIR / p).resolve()          # 拼接并解析 .. 等符号
    if not path.is_relative_to(WORKDIR):    # 解析后是否还在工作目录下？
        raise ValueError(f"Path escapes workspace: {p}")
    return path


# ── 四个工具的处理函数 ───────────────────────────────────────
#
# s01 只有一个 run_bash()。s02 新增了三个文件操作函数。
# 每个函数：接收参数 → 执行操作 → 返回字符串结果
# 返回的字符串会作为 tool_result 传给 LLM。

def run_bash(command: str) -> str:
    """和 s01 一样：执行 shell 命令，返回输出字符串。"""
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def run_read(path: str, limit: int = None) -> str:
    """读取文件内容。可选 limit 参数限制读取行数。

    LLM 调用示例：read_file(path="greet.py")
                  read_file(path="greet.py", limit=10)
    """
    try:
        text = safe_path(path).read_text()          # safe_path 确保不逃逸
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    """写入文件。如果目录不存在会自动创建。

    LLM 调用示例：write_file(path="greet.py", content="def greet(name):...")
    """
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)  # 自动建目录
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    """替换文件中的指定文本（只替换第一次出现）。

    LLM 调用示例：edit_file(path="greet.py",
                           old_text="def greet(name):",
                           new_text="def greet(name):\\n    \"\"\"Greet someone.\"\"\"")
    """
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"    # 找不到则报错，让 LLM 重试
        fp.write_text(content.replace(old_text, new_text, 1))  # 只替换第 1 次出现
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# ── s02 核心新概念：工具派发表（dispatch map）────────────────
#
# s01 的循环里硬编码了 run_bash()：
#     output = run_bash(block.input["command"])
#
# s02 改成查表：
#     handler = TOOL_HANDLERS[block.name]    # 根据工具名找到处理函数
#     output = handler(**block.input)         # 调用处理函数
#
# 好处：加一个新工具不需要改循环代码，只需要：
#   1. 在 TOOL_HANDLERS 加一行映射
#   2. 在 TOOLS 加一个工具定义
#
# lambda **kw 的含义：
#   **kw 把 LLM 传来的 JSON 参数展开为关键字参数
#   例如 LLM 传 {"path": "greet.py", "content": "..."}
#   → kw = {"path": "greet.py", "content": "..."}
#   → kw["path"] = "greet.py", kw["content"] = "..."

TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}

# ── 工具定义列表（给 LLM 看的说明书）────────────────────────
#
# s01 只有 1 个工具。s02 有 4 个。
# 每个工具的结构和 s01 一样：name + description + input_schema
# 详细解释见 s01-lecture-notes.md "第 2 部分：告诉 LLM 它有什么工具"

TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read file contents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "limit": {"type": "integer"},       # 选填参数，不在 required 里
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace exact text in file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
]


# ── agent_loop：和 s01 结构完全一样 ─────────────────────────
#
# 唯一的区别在工具执行部分：
#   s01: output = run_bash(block.input["command"])       ← 硬编码
#   s02: handler = TOOL_HANDLERS[block.name]             ← 查表
#        output = handler(**block.input)

def agent_loop(messages: list):
    loop_round = 0
    while True:
        loop_round += 1

        separator(f"轮次 {loop_round}: 发送给 LLM")
        print_messages(messages)
        print(f"\n{CYAN}→ 调用 client.messages.create(...){RESET}")

        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )

        separator(f"轮次 {loop_round}: LLM 回复")
        print_response(response)

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            separator(f"轮次 {loop_round}: 循环结束")
            print(f"{BOLD}stop_reason = \"{response.stop_reason}\" → 不是 \"tool_use\"，return!{RESET}")
            return

        separator(f"轮次 {loop_round}: 执行工具")
        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                if handler:
                    print(f"{YELLOW}执行: {block.name}({json.dumps(block.input, ensure_ascii=False)[:120]}){RESET}")
                    output = handler(**block.input)
                else:
                    output = f"Unknown tool: {block.name}"
                print(f"{DIM}输出 ({len(output)} 字符):{RESET}")
                print(output[:300] + ("..." if len(output) > 300 else ""))
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})
        print(f"\n{CYAN}→ tool_result 已塞回 messages，继续下一轮...{RESET}")


if __name__ == "__main__":
    print(f"{BOLD}=== s02 verbose 模式 ==={RESET}")
    print(f"{DIM}MODEL  = {MODEL}{RESET}")
    print(f"{DIM}SYSTEM = {SYSTEM}{RESET}")
    print(f"{DIM}TOOLS  = {json.dumps([t['name'] for t in TOOLS])}{RESET}")
    print()

    history = []
    while True:
        try:
            query = input(f"{CYAN}s02 >> {RESET}")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break

        separator("用户输入")
        print(f"query = \"{query}\"")
        history.append({"role": "user", "content": query})

        agent_loop(history)

        separator("最终回答")
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()
