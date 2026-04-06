#!/usr/bin/env python3
# Harness: planning -- keeping the model on course without scripting the route.
"""
s03_todo_write.py - TodoWrite

The model tracks its own progress via a TodoManager. A nag reminder
forces it to keep updating when it forgets.

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> | Tools   |
    |  prompt  |      |       |      | + todo  |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                                |
                    +-----------+-----------+
                    | TodoManager state     |
                    | [ ] task A            |
                    | [>] task B <- doing   |
                    | [x] task C            |
                    +-----------------------+
                                |
                    if rounds_since_todo >= 3:
                      inject <reminder>

Key insight: "The agent can track its own progress -- and I can see it."
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

# ── System prompt 变化 ──────────────────────────────────────
#
# 对比 s02: "Use tools to solve tasks. Act, don't explain."
# s03 新增: 告诉 LLM 要用 todo 工具规划多步任务，并且要更新状态
SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use the todo tool to plan multi-step tasks. Mark in_progress before starting, completed when done.
Prefer tools over prose."""


# ── 打印工具（和 s01/s02 一样）──────────────────────────────

CYAN    = "\033[36m"
YELLOW  = "\033[33m"
GREEN   = "\033[32m"
MAGENTA = "\033[35m"
RED     = "\033[31m"
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
                elif isinstance(block, dict):
                    if block.get("type") == "tool_result":
                        c = str(block["content"])
                        c_preview = c[:80] + ("..." if len(c) > 80 else "")
                        print(f"{DIM}  [{i}] {role}/tool_result: \"{c_preview}\"{RESET}")
                    elif block.get("type") == "text":
                        # nag reminder 也是 text block
                        print(f"{DIM}  [{i}] {role}/text: \"{block['text'][:80]}\"{RESET}")
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
            input_str = json.dumps(block.input, ensure_ascii=False)
            print(f"{GREEN}    input={input_str[:200]}{('...' if len(input_str) > 200 else '')}{RESET}")
    print(f"{GREEN}]{RESET}")


# ── s03 核心新概念：TodoManager ─────────────────────────────
#
# s01/s02 的 Agent 做多步任务时，没有"进度追踪"——LLM 做到哪了，
# 还剩什么没做，全靠 LLM 自己记住。对话越长，LLM 越容易忘。
#
# TodoManager 给 LLM 一个"白板"：
#   - LLM 通过 todo 工具写入任务列表
#   - 每个任务有 3 种状态：pending（待做）、in_progress（正在做）、completed（完成）
#   - 同一时间只允许 1 个 in_progress（强制逐步聚焦，不能同时开多个任务）
#   - TodoManager 返回渲染后的列表，LLM 能在 tool_result 里看到当前进度
#
# 这不是 LLM 的内置能力——是你的程序提供的外部状态管理。

class TodoManager:
    def __init__(self):
        self.items = []     # 任务列表，每项是 {"id": "1", "text": "...", "status": "pending"}

    def update(self, items: list) -> str:
        """LLM 每次调用 todo 工具时，传入完整的任务列表（不是增量更新）。

        为什么是全量更新而不是增量？
        因为 LLM 一次就能输出整个列表，全量替换更简单、不容易出状态不一致的 bug。
        """
        if len(items) > 20:
            raise ValueError("Max 20 todos allowed")
        validated = []
        in_progress_count = 0
        for i, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(i + 1)))
            if not text:
                raise ValueError(f"Item {item_id}: text required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {item_id}: invalid status '{status}'")
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"id": item_id, "text": text, "status": status})
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")
        self.items = validated
        return self.render()     # 返回渲染后的列表给 LLM 看

    def render(self) -> str:
        """把任务列表渲染成人类可读的文本。

        输出示例：
            [ ] #1: Add type hints
            [>] #2: Add docstrings         ← 正在做
            [x] #3: Add main guard         ← 已完成
            (1/3 completed)
        """
        if not self.items:
            return "No todos."
        lines = []
        for item in self.items:
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}[item["status"]]
            lines.append(f"{marker} #{item['id']}: {item['text']}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)


TODO = TodoManager()


# ── 工具函数（和 s02 一样，省略注释）──────────────────────────

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


# ── 派发表：比 s02 多了一个 todo 工具 ───────────────────────

TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "todo":       lambda **kw: TODO.update(kw["items"]),   # ← s03 新增
}

# ── 工具定义：比 s02 多了一个 todo ──────────────────────────
#
# todo 工具的 input_schema 比较复杂：
#   items 是一个数组（array），数组里每个元素是一个对象（object），
#   每个对象有 id、text、status 三个字段。
#   status 用了 enum 限制只能是 "pending"/"in_progress"/"completed"。
#
# LLM 调用示例：
#   todo(items=[
#     {"id": "1", "text": "Add type hints", "status": "completed"},
#     {"id": "2", "text": "Add docstrings", "status": "in_progress"},
#     {"id": "3", "text": "Add main guard", "status": "pending"},
#   ])

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "todo",
     "description": "Update task list. Track progress on multi-step tasks.",
     "input_schema": {
         "type": "object",
         "properties": {
             "items": {
                 "type": "array",                          # 数组
                 "items": {                                 # 数组里每个元素的 schema
                     "type": "object",
                     "properties": {
                         "id": {"type": "string"},
                         "text": {"type": "string"},
                         "status": {
                             "type": "string",
                             "enum": ["pending", "in_progress", "completed"],  # 只允许这 3 个值
                         },
                     },
                     "required": ["id", "text", "status"],
                 },
             },
         },
         "required": ["items"],
     }},
]


# ── agent_loop：在 s02 基础上新增了两个机制 ─────────────────
#
# 新增 1: rounds_since_todo 计数器
#   - 每轮检查 LLM 是否调用了 todo 工具
#   - 如果调用了 → 计数器归零
#   - 如果没调用 → 计数器 +1
#
# 新增 2: nag reminder 注入
#   - 当 rounds_since_todo >= 3 时，在 tool_result 后面追加一条提醒：
#     "<reminder>Update your todos.</reminder>"
#   - 这条提醒作为 user 消息的一部分发给 LLM
#   - LLM 看到后会想起来更新任务状态
#
# 循环本体（while True → create → append → check stop_reason → execute）不变。

def agent_loop(messages: list):
    rounds_since_todo = 0
    while True:
        loop_round = rounds_since_todo  # 用于打印（注意这不是总轮次，是距上次 todo 的轮次）

        separator(f"发送给 LLM (距上次 todo: {rounds_since_todo} 轮)")
        print_messages(messages)

        # 打印当前 todo 状态
        if TODO.items:
            print(f"\n{CYAN}当前 TODO 状态:{RESET}")
            print(f"{CYAN}{TODO.render()}{RESET}")

        print(f"\n{CYAN}→ 调用 client.messages.create(...){RESET}")

        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )

        separator("LLM 回复")
        print_response(response)

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            separator("循环结束")
            print(f"{BOLD}stop_reason = \"{response.stop_reason}\" → return!{RESET}")
            if TODO.items:
                print(f"\n{CYAN}最终 TODO 状态:{RESET}")
                print(f"{CYAN}{TODO.render()}{RESET}")
            return

        separator("执行工具")
        results = []
        used_todo = False
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                try:
                    output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                except Exception as e:
                    output = f"Error: {e}"

                # 打印工具执行详情
                if block.name == "todo":
                    print(f"{YELLOW}执行: todo(items=[...{len(block.input.get('items', []))} 项]){RESET}")
                else:
                    print(f"{YELLOW}执行: {block.name}({json.dumps(block.input, ensure_ascii=False)[:120]}){RESET}")
                print(f"{DIM}输出 ({len(str(output))} 字符):{RESET}")
                print(str(output)[:300] + ("..." if len(str(output)) > 300 else ""))

                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
                if block.name == "todo":
                    used_todo = True

        # ── s03 核心：nag reminder 逻辑 ─────────────────────
        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1

        if rounds_since_todo >= 3:
            nag = "<reminder>Update your todos.</reminder>"
            results.append({"type": "text", "text": nag})
            print(f"\n{RED}⚠ 注入 nag reminder: {nag}{RESET}")
            print(f"{RED}  (LLM 已经 {rounds_since_todo} 轮没更新 todo 了){RESET}")
        else:
            status_label = "✓ 本轮调用了 todo" if used_todo else f"○ 距上次 todo: {rounds_since_todo} 轮"
            print(f"\n{DIM}{status_label}{RESET}")

        messages.append({"role": "user", "content": results})
        print(f"{CYAN}→ tool_result 已塞回 messages，继续下一轮...{RESET}")


if __name__ == "__main__":
    print(f"{BOLD}=== s03 verbose 模式 ==={RESET}")
    print(f"{DIM}MODEL  = {MODEL}{RESET}")
    print(f"{DIM}SYSTEM = {SYSTEM}{RESET}")
    print(f"{DIM}TOOLS  = {json.dumps([t['name'] for t in TOOLS])}{RESET}")
    print()

    history = []
    while True:
        try:
            query = input(f"{CYAN}s03 >> {RESET}")
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
