#!/usr/bin/env python3
# Harness: context isolation -- protecting the model's clarity of thought.
"""
s04_subagent.py - Subagents

Spawn a child agent with fresh messages=[]. The child works in its own
context, sharing the filesystem, then returns only a summary to the parent.

    Parent agent                     Subagent
    +------------------+             +------------------+
    | messages=[...]   |             | messages=[]      |  <-- fresh
    |                  |  dispatch   |                  |
    | tool: task       | ---------->| while tool_use:  |
    |   prompt="..."   |            |   call tools     |
    |   description="" |            |   append results |
    |                  |  summary   |                  |
    |   result = "..." | <--------- | return last text |
    +------------------+             +------------------+
              |
    Parent context stays clean.
    Subagent context is discarded.

Key insight: "Process isolation gives context isolation for free."
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

# ── System prompt：父 Agent 和子 Agent 各有一套 ────────────
#
# 父 Agent：知道自己可以用 task 工具派活
# 子 Agent：知道自己是"子 Agent"，完成任务后要总结
SYSTEM = f"You are a coding agent at {WORKDIR}. Use the task tool to delegate exploration or subtasks."
SUBAGENT_SYSTEM = f"You are a coding subagent at {WORKDIR}. Complete the given task, then summarize your findings."


# ── 打印工具 ──────────────────────────────────────────────

CYAN    = "\033[36m"
YELLOW  = "\033[33m"
GREEN   = "\033[32m"
MAGENTA = "\033[35m"
RED     = "\033[31m"
DIM     = "\033[2m"
BOLD    = "\033[1m"
RESET   = "\033[0m"

def separator(label, indent=0):
    prefix = "  │ " * indent
    print(f"\n{prefix}{MAGENTA}{'─'*18} {label} {'─'*18}{RESET}")

def print_messages(messages, indent=0):
    prefix = "  │ " * indent
    print(f"{prefix}{DIM}messages = [{RESET}")
    for i, msg in enumerate(messages):
        role = msg["role"]
        content = msg["content"]
        if isinstance(content, str):
            text_preview = content[:80] + ("..." if len(content) > 80 else "")
            print(f"{prefix}{DIM}  [{i}] {role}: \"{text_preview}\"{RESET}")
        elif isinstance(content, list):
            for block in content:
                if hasattr(block, "type") and not isinstance(block, dict):
                    if block.type == "text":
                        text_preview = block.text[:80] + ("..." if len(block.text) > 80 else "")
                        print(f"{prefix}{DIM}  [{i}] {role}/text: \"{text_preview}\"{RESET}")
                    elif block.type == "tool_use":
                        print(f"{prefix}{DIM}  [{i}] {role}/tool_use: {block.name}({json.dumps(block.input, ensure_ascii=False)[:80]}){RESET}")
                elif isinstance(block, dict) and block.get("type") == "tool_result":
                    c = str(block["content"])
                    c_preview = c[:80] + ("..." if len(c) > 80 else "")
                    print(f"{prefix}{DIM}  [{i}] {role}/tool_result: \"{c_preview}\"{RESET}")
    print(f"{prefix}{DIM}]{RESET}")

def print_response(response, indent=0):
    prefix = "  │ " * indent
    print(f"{prefix}{GREEN}response.stop_reason = \"{response.stop_reason}\"{RESET}")
    print(f"{prefix}{GREEN}response.content = [{RESET}")
    for block in response.content:
        if block.type == "text":
            text_preview = block.text[:120] + ("..." if len(block.text) > 120 else "")
            print(f"{prefix}{GREEN}  TextBlock: \"{text_preview}\"{RESET}")
        elif block.type == "tool_use":
            print(f"{prefix}{GREEN}  ToolUseBlock: name=\"{block.name}\", id=\"{block.id}\"{RESET}")
            input_str = json.dumps(block.input, ensure_ascii=False)
            print(f"{prefix}{GREEN}    input={input_str[:200]}{('...' if len(input_str) > 200 else '')}{RESET}")
    print(f"{prefix}{GREEN}]{RESET}")


# ── 工具函数（和 s02/s03 一样，省略注释）─────────────────────

def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(command: str) -> str:
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
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

def run_read(path: str, limit: int = None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# ── 派发表（父子共用同一套工具函数）──────────────────────────

TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}

# ── s04 核心概念 1：父子工具集不同 ──────────────────────────
#
# 子 Agent（CHILD_TOOLS）：只有基础工具（bash, read, write, edit）
# 父 Agent（PARENT_TOOLS）：基础工具 + task 工具
#
# 为什么子 Agent 没有 task 工具？
#   防止递归套娃——子 Agent 如果也能生子 Agent，就会无限嵌套。
#   这是一个硬约束：子 Agent 的 TOOLS 列表里根本没有 task 这个选项，
#   LLM 看不到它，自然不会调用。

CHILD_TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
]


# ── s04 核心概念 2：run_subagent —— 独立上下文的子循环 ──────
#
# 和 s01 的 agent_loop 几乎一样，但有 3 个关键区别：
#
#   1. messages 从零开始（不是父 Agent 的 history）
#      → 子 Agent 看不到父 Agent 之前的对话，上下文干净
#
#   2. 用 CHILD_TOOLS（没有 task 工具）
#      → 防止递归套娃
#
#   3. 只返回最终文本摘要（子 Agent 的 messages 直接丢弃）
#      → 父 Agent 收到的是一段简洁的总结，不是子 Agent 的完整对话历史
#
# 子 Agent 和父 Agent 共享的是什么？
#   - 同一个文件系统（子 Agent 写的文件，父 Agent 能看到）
#   - 同一个 API client 和 MODEL
#   - 同一套工具函数（TOOL_HANDLERS）
#
# 不共享的是什么？
#   - messages 列表（各自独立）
#   - system prompt（各自不同）
#   - 工具定义列表（子没有 task）

def run_subagent(prompt: str) -> str:
    """启动一个子 Agent，用独立的 messages 执行任务，只返回摘要。"""
    sub_messages = [{"role": "user", "content": prompt}]  # ← 从零开始的 messages

    separator("子 Agent 启动", indent=1)
    print(f"  │ {CYAN}prompt: \"{prompt[:120]}\"{RESET}")
    print(f"  │ {DIM}tools: {json.dumps([t['name'] for t in CHILD_TOOLS])}  (没有 task！){RESET}")

    sub_round = 0
    for _ in range(30):  # 安全上限：最多跑 30 轮，防止无限循环
        sub_round += 1

        separator(f"子 Agent 轮次 {sub_round}", indent=1)
        print_messages(sub_messages, indent=1)
        print(f"  │ {CYAN}→ 调用 client.messages.create(...){RESET}")

        response = client.messages.create(
            model=MODEL, system=SUBAGENT_SYSTEM, messages=sub_messages,
            tools=CHILD_TOOLS, max_tokens=8000,
        )

        separator(f"子 Agent 轮次 {sub_round}: 回复", indent=1)
        print_response(response, indent=1)

        sub_messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            break

        # 子 Agent 的工具执行（和父一样，只是没有 task）
        separator(f"子 Agent 轮次 {sub_round}: 执行工具", indent=1)
        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                print(f"  │ {YELLOW}执行: {block.name}({json.dumps(block.input, ensure_ascii=False)[:100]}){RESET}")
                print(f"  │ {DIM}输出 ({len(str(output))} 字符): {str(output)[:200]}{RESET}")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)[:50000]})
        sub_messages.append({"role": "user", "content": results})

    # 只提取最终的文本回复，其余全部丢弃
    summary = "".join(b.text for b in response.content if hasattr(b, "text")) or "(no summary)"

    separator("子 Agent 结束", indent=1)
    print(f"  │ {BOLD}共 {sub_round} 轮，子 Agent messages 有 {len(sub_messages)} 条 → 全部丢弃{RESET}")
    print(f"  │ {BOLD}只返回摘要 ({len(summary)} 字符):{RESET}")
    print(f"  │ {summary[:300]}{'...' if len(summary) > 300 else ''}")

    return summary


# ── 父 Agent 的工具定义 ─────────────────────────────────────
#
# PARENT_TOOLS = CHILD_TOOLS + [task 工具]
# task 工具的 prompt 参数是给子 Agent 的任务描述
# description 参数是给人看的简短标签

PARENT_TOOLS = CHILD_TOOLS + [
    {"name": "task",
     "description": "Spawn a subagent with fresh context. It shares the filesystem but not conversation history.",
     "input_schema": {
         "type": "object",
         "properties": {
             "prompt": {"type": "string"},
             "description": {"type": "string", "description": "Short description of the task"},
         },
         "required": ["prompt"],
     }},
]


# ── 父 Agent 的循环 ─────────────────────────────────────────
#
# 和 s01-s03 的循环结构一样。唯一的区别：
#   遇到 block.name == "task" 时，不查 TOOL_HANDLERS，而是调 run_subagent()

def agent_loop(messages: list):
    loop_round = 0
    while True:
        loop_round += 1

        separator(f"父 Agent 轮次 {loop_round}")
        print_messages(messages)
        print(f"\n{CYAN}→ 调用 client.messages.create(...){RESET}")

        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=PARENT_TOOLS, max_tokens=8000,
        )

        separator(f"父 Agent 轮次 {loop_round}: 回复")
        print_response(response)

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            separator(f"父 Agent 轮次 {loop_round}: 循环结束")
            print(f"{BOLD}stop_reason = \"{response.stop_reason}\" → return!{RESET}")
            return

        separator(f"父 Agent 轮次 {loop_round}: 执行工具")
        results = []
        for block in response.content:
            if block.type == "tool_use":
                if block.name == "task":
                    # ── task 工具：启动子 Agent ──
                    desc = block.input.get("description", "subtask")
                    prompt = block.input.get("prompt", "")
                    print(f"{YELLOW}派发子任务: \"{desc}\"{RESET}")
                    print(f"{DIM}prompt: \"{prompt[:120]}\"{RESET}")
                    print(f"{MAGENTA}{'─'*50}{RESET}")
                    output = run_subagent(prompt)
                    print(f"{MAGENTA}{'─'*50}{RESET}")
                    print(f"{YELLOW}子任务完成，摘要返回给父 Agent ({len(output)} 字符){RESET}")
                else:
                    # 普通工具：和之前一样
                    handler = TOOL_HANDLERS.get(block.name)
                    output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                    print(f"{YELLOW}执行: {block.name}({json.dumps(block.input, ensure_ascii=False)[:120]}){RESET}")
                    print(f"{DIM}输出 ({len(str(output))} 字符): {str(output)[:200]}{RESET}")

                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        messages.append({"role": "user", "content": results})
        print(f"\n{CYAN}→ tool_result 已塞回 messages，继续下一轮...{RESET}")


if __name__ == "__main__":
    print(f"{BOLD}=== s04 verbose 模式 ==={RESET}")
    print(f"{DIM}MODEL  = {MODEL}{RESET}")
    print(f"{DIM}SYSTEM (父) = {SYSTEM}{RESET}")
    print(f"{DIM}SYSTEM (子) = {SUBAGENT_SYSTEM}{RESET}")
    print(f"{DIM}PARENT_TOOLS = {json.dumps([t['name'] for t in PARENT_TOOLS])}{RESET}")
    print(f"{DIM}CHILD_TOOLS  = {json.dumps([t['name'] for t in CHILD_TOOLS])}  ← 没有 task{RESET}")
    print()

    history = []
    while True:
        try:
            query = input(f"{CYAN}s04 >> {RESET}")
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
