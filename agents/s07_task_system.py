#!/usr/bin/env python3
# Harness: persistent tasks -- goals that outlive any single conversation.
"""
s07_task_system.py - Tasks

Tasks persist as JSON files in .tasks/ so they survive context compression.
Each task has a dependency graph (blockedBy).

    .tasks/
      task_1.json  {"id":1, "subject":"...", "status":"completed", ...}
      task_2.json  {"id":2, "blockedBy":[1], "status":"pending", ...}
      task_3.json  {"id":3, "blockedBy":[2], ...}

    Dependency resolution:
    +----------+     +----------+     +----------+
    | task 1   | --> | task 2   | --> | task 3   |
    | complete |     | blocked  |     | blocked  |
    +----------+     +----------+     +----------+
         |                ^
         +--- completing task 1 removes it from task 2's blockedBy

Key insight: "State that survives compression -- because it's outside the conversation."
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
TASKS_DIR = WORKDIR / ".tasks"

SYSTEM = f"You are a coding agent at {WORKDIR}. Use task tools to plan and track work."


# ── 打印工具 ──────────────────────────────────────────────

CYAN    = "\033[36m"
YELLOW  = "\033[33m"
GREEN   = "\033[32m"
MAGENTA = "\033[35m"
RED     = "\033[31m"
DIM     = "\033[2m"
BOLD    = "\033[1m"
RESET   = "\033[0m"

def separator(label):
    print(f"\n{MAGENTA}{'─'*18} {label} {'─'*18}{RESET}")

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
            input_str = json.dumps(block.input, ensure_ascii=False)
            print(f"{GREEN}    input={input_str[:200]}{('...' if len(input_str) > 200 else '')}{RESET}")
    print(f"{GREEN}]{RESET}")

def print_tasks_dir():
    """Verbose: 打印 .tasks/ 目录里的所有 JSON 文件状态。"""
    if not TASKS_DIR.exists():
        return
    files = sorted(TASKS_DIR.glob("task_*.json"), key=lambda f: int(f.stem.split("_")[1]))
    if not files:
        return
    print(f"{DIM}.tasks/ 目录状态：{RESET}")
    for f in files:
        try:
            task = json.loads(f.read_text())
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}.get(task["status"], "[?]")
            blocked = f" blockedBy={task['blockedBy']}" if task.get("blockedBy") else ""
            print(f"{DIM}  {f.name}: {marker} #{task['id']} \"{task['subject']}\"{blocked}{RESET}")
        except Exception as e:
            print(f"{DIM}  {f.name}: <parse error: {e}>{RESET}")


# ── s07 核心概念：TaskManager —— 持久化的任务图 ──────────────
#
# 问题：s03 的 TodoManager 是内存里的扁平 checklist——
#   - 没有顺序关系（只有 pending/in_progress/completed）
#   - 没有依赖（task B 等 task A 这种关系无法表达）
#   - 没有持久化（s06 的 context compact 触发后全部消失）
#
# s06 的 transcript 是事后审计日志，不是工作状态——压缩后 LLM
# 不知道"我刚才规划了 5 个任务，已经做完 2 个，剩下 3 个"。
#
# 解法：把任务从内存搬到磁盘，从扁平列表升级为依赖图。
#
#   .tasks/
#     task_1.json   {"id":1, "subject":"setup", "status":"completed", "blockedBy":[]}
#     task_2.json   {"id":2, "subject":"code",  "status":"pending",   "blockedBy":[1]}
#     task_3.json   {"id":3, "subject":"test",  "status":"pending",   "blockedBy":[2]}
#
# 三个关键升级：
#
#   1. 一个任务一个 JSON 文件
#      → 持久化（context compact 不影响）
#      → 重启 Agent 后还能 "继续上次的工作"
#      → 多个 Agent 可以共享同一个 .tasks/ 目录（s09+ 的多 Agent 协作基础）
#
#   2. blockedBy 字段 = 依赖边
#      → 任务 2 的 blockedBy=[1] 表示"任务 1 没完成时我不能开始"
#      → 完成任务 1 时自动从所有任务的 blockedBy 里移除 1
#      → 形成 DAG（有向无环图），可以表达任意复杂度的任务关系
#
#   3. 三档状态 pending/in_progress/completed
#      → 比 s03 的"勾/未勾"更细粒度
#      → in_progress 标识"正在做"，避免和"还没开始"混淆
#
# s07 是后续课程的基础：
#   - s08 background tasks：用任务系统跟踪后台执行的命令
#   - s09 agent teams：多个 Agent 共享同一个任务板
#   - s11 autonomous agents：自动从任务板领取未分配的任务
#   - s12 worktree isolation：每个任务在独立的 git worktree 里执行
#
# 类比：项目管理工具（Linear、Jira、Asana）
#   每个 ticket 是一个 JSON 文件
#   blocked by 关系形成依赖图
#   多人协作通过共享 ticket 池实现

class TaskManager:
    def __init__(self, tasks_dir: Path):
        self.dir = tasks_dir
        self.dir.mkdir(exist_ok=True)
        # 启动时扫描已有的 task 文件，确定下一个 ID
        # 这是实现"持久化"的关键——重启后能接着之前的 ID 继续
        self._next_id = self._max_id() + 1

    def _max_id(self) -> int:
        """扫描 .tasks/ 目录，返回最大的任务 ID（用于生成下一个 ID）。"""
        ids = [int(f.stem.split("_")[1]) for f in self.dir.glob("task_*.json")]
        return max(ids) if ids else 0

    def _load(self, task_id: int) -> dict:
        """从磁盘读取一个任务的 JSON。"""
        path = self.dir / f"task_{task_id}.json"
        if not path.exists():
            raise ValueError(f"Task {task_id} not found")
        return json.loads(path.read_text())

    def _save(self, task: dict):
        """把任务的 JSON 写回磁盘。"""
        path = self.dir / f"task_{task['id']}.json"
        path.write_text(json.dumps(task, indent=2, ensure_ascii=False))

    # ── create: 创建新任务 ──────────────────────────────
    #
    # 任务的字段：
    #   id          - 自增整数
    #   subject     - 短标题（如 "Setup project"）
    #   description - 详细描述（可选）
    #   status      - "pending" / "in_progress" / "completed"
    #   blockedBy   - 整数列表，被哪些任务阻塞
    #   owner       - 谁负责（s09+ 多 Agent 时用）
    #
    # 注意：create 不接受 blockedBy 参数——必须创建后用 task_update 设置依赖。
    # 这是一个简化设计，实际使用中往往需要"创建时直接指定依赖"。

    def create(self, subject: str, description: str = "") -> str:
        task = {
            "id": self._next_id, "subject": subject, "description": description,
            "status": "pending", "blockedBy": [], "owner": "",
        }
        self._save(task)
        self._next_id += 1

        # Verbose: 显示磁盘状态变化
        print(f"  {GREEN}创建 task_{task['id']}.json: \"{subject}\"{RESET}")

        return json.dumps(task, indent=2, ensure_ascii=False)

    def get(self, task_id: int) -> str:
        return json.dumps(self._load(task_id), indent=2, ensure_ascii=False)

    # ── update: 更新状态或依赖 ──────────────────────────
    #
    # 三种操作可以独立或组合：
    #   1. 改 status: 通常是 pending → in_progress → completed
    #      特殊：status="completed" 时自动调 _clear_dependency
    #
    #   2. add_blocked_by: 添加依赖（任务 A 现在依赖任务 B）
    #
    #   3. remove_blocked_by: 手动移除依赖（罕见）
    #
    # 注意：set() 去重——避免 blockedBy=[1, 1, 2] 这种重复

    def update(self, task_id: int, status: str = None,
               add_blocked_by: list = None, remove_blocked_by: list = None) -> str:
        task = self._load(task_id)
        old_status = task.get("status")
        old_blocked = list(task.get("blockedBy", []))

        if status:
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Invalid status: {status}")
            task["status"] = status
            # ── 关键：完成任务时自动解除其他任务对它的依赖 ──
            if status == "completed":
                self._clear_dependency(task_id)
        if add_blocked_by:
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
        if remove_blocked_by:
            task["blockedBy"] = [x for x in task["blockedBy"] if x not in remove_blocked_by]
        self._save(task)

        # Verbose: 显示状态变化
        if status and status != old_status:
            print(f"  {GREEN}task_{task_id}: {old_status} → {status}{RESET}")
        if add_blocked_by:
            print(f"  {GREEN}task_{task_id}: blockedBy {old_blocked} → {task['blockedBy']}{RESET}")

        return json.dumps(task, indent=2, ensure_ascii=False)

    # ── _clear_dependency: 自动解除依赖 ─────────────────
    #
    # 当任务 X 完成时，遍历所有任务文件，把 X 从它们的 blockedBy 里移除。
    # 这是依赖图自动更新的核心——LLM 不需要手动管理"哪些任务被解锁"。
    #
    # 例子：
    #   task_2.json: blockedBy=[1]   → 完成 task_1 后变成 blockedBy=[]
    #   task_3.json: blockedBy=[1,2] → 完成 task_1 后变成 blockedBy=[2]
    #
    # 注意这是 O(N) 扫描——每完成一个任务都要遍历所有任务文件。
    # 任务数少时无所谓，但任务数 >1000 时可能需要优化（比如反向索引）。

    def _clear_dependency(self, completed_id: int):
        """Remove completed_id from all other tasks' blockedBy lists."""
        unblocked = []
        for f in self.dir.glob("task_*.json"):
            task = json.loads(f.read_text())
            if completed_id in task.get("blockedBy", []):
                task["blockedBy"].remove(completed_id)
                self._save(task)
                if not task["blockedBy"]:
                    unblocked.append(task["id"])

        # Verbose: 显示哪些任务被解锁了
        if unblocked:
            print(f"  {YELLOW}→ task_{completed_id} 完成，解锁了: {unblocked}{RESET}")

    # ── list_all: 列出所有任务 ──────────────────────────
    #
    # 输出格式：
    #   [x] #1: Setup project
    #   [>] #2: Write code
    #   [ ] #3: Write tests (blocked by: [2])
    #
    # marker 含义：
    #   [x] = completed
    #   [>] = in_progress
    #   [ ] = pending
    #   [?] = 未知状态
    #
    # 注意：list_all 没有显示 blockedBy=[] 的任务的 "ready" 标记。
    # LLM 需要自己从 marker + blockedBy 推断哪些任务是"可以开始的"。

    def list_all(self) -> str:
        tasks = []
        files = sorted(
            self.dir.glob("task_*.json"),
            key=lambda f: int(f.stem.split("_")[1])
        )
        for f in files:
            tasks.append(json.loads(f.read_text()))
        if not tasks:
            return "No tasks."
        lines = []
        for t in tasks:
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}.get(t["status"], "[?]")
            blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
            lines.append(f"{marker} #{t['id']}: {t['subject']}{blocked}")
        return "\n".join(lines)


TASKS = TaskManager(TASKS_DIR)


# ── 工具函数（和 s02-s06 一样）──────────────────────────────

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
        c = fp.read_text()
        if old_text not in c:
            return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# ── 派发表：4 个任务工具 ────────────────────────────────────
#
# task_create / task_update / task_list / task_get 全部走统一派发表
# （非侵入式扩展，参见 s05 讲义"非侵入式 vs 侵入式"）。
# 它们调用的是同一个 TASKS 实例的方法。

TOOL_HANDLERS = {
    "bash":        lambda **kw: run_bash(kw["command"]),
    "read_file":   lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file":  lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":   lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "task_create": lambda **kw: TASKS.create(kw["subject"], kw.get("description", "")),
    "task_update": lambda **kw: TASKS.update(kw["task_id"], kw.get("status"), kw.get("addBlockedBy"), kw.get("removeBlockedBy")),
    "task_list":   lambda **kw: TASKS.list_all(),
    "task_get":    lambda **kw: TASKS.get(kw["task_id"]),
}

# ── TOOLS 列表：4 个 base + 4 个 task ──────────────────────
#
# 注意 task_update 的 input_schema：
#   - status 是 enum，限定三个合法值
#   - addBlockedBy 和 removeBlockedBy 是 array of integer
#   这是给 LLM 看的"使用说明"，避免它传错参数。
#
# task_list 的 input_schema 是空的——不需要任何参数。

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "task_create", "description": "Create a new task.",
     "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "description": {"type": "string"}}, "required": ["subject"]}},
    {"name": "task_update", "description": "Update a task's status or dependencies.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}, "addBlockedBy": {"type": "array", "items": {"type": "integer"}}, "removeBlockedBy": {"type": "array", "items": {"type": "integer"}}}, "required": ["task_id"]}},
    {"name": "task_list", "description": "List all tasks with status summary.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "task_get", "description": "Get full details of a task by ID.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
]


# ── Agent 循环 ────────────────────────────────────────────
#
# 和 s01-s05 一样，没有任何特殊处理。
# 4 个 task 工具走 TOOL_HANDLERS 统一派发——非侵入式扩展。
# 这是 s07 的"低调"之处：核心创新在 TaskManager 类，循环本身没变。

def agent_loop(messages: list):
    loop_round = 0
    while True:
        loop_round += 1

        separator(f"轮次 {loop_round}")
        print_messages(messages)
        print(f"\n{CYAN}→ 调用 client.messages.create(...){RESET}")

        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )

        separator(f"轮次 {loop_round}: 回复")
        print_response(response)

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            separator(f"轮次 {loop_round}: 循环结束")
            print(f"{BOLD}stop_reason = \"{response.stop_reason}\" → return!{RESET}")
            return

        separator(f"轮次 {loop_round}: 执行工具")
        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                try:
                    output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                except Exception as e:
                    output = f"Error: {e}"

                # ── s07 特有的 verbose：区分 task 工具和其他工具 ──
                if block.name.startswith("task_"):
                    print(f"{YELLOW}执行: {block.name}({json.dumps(block.input, ensure_ascii=False)[:120]}){RESET}")
                    print(f"{DIM}输出 ({len(str(output))} 字符): {str(output)[:300]}{RESET}")
                else:
                    print(f"{YELLOW}执行: {block.name}({json.dumps(block.input, ensure_ascii=False)[:120]}){RESET}")
                    print(f"{DIM}输出 ({len(str(output))} 字符): {str(output)[:200]}{RESET}")

                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        messages.append({"role": "user", "content": results})

        # ── s07 特有：打印 .tasks/ 目录的当前状态 ──
        # 让读者一眼看到磁盘上的任务文件如何变化（哪些新建、哪些状态变了）
        if any(b.type == "tool_use" and b.name.startswith("task_") for b in response.content):
            print()
            print_tasks_dir()

        print(f"\n{CYAN}→ tool_result 已塞回 messages，继续下一轮...{RESET}")


if __name__ == "__main__":
    print(f"{BOLD}=== s07 verbose 模式 ==={RESET}")
    print(f"{DIM}MODEL     = {MODEL}{RESET}")
    print(f"{DIM}TASKS_DIR = {TASKS_DIR}{RESET}")
    print(f"{DIM}下一个 task ID: {TASKS._next_id}（启动时扫描了已有文件）{RESET}")
    print()

    separator("TOOLS 列表")
    print(f"{DIM}{json.dumps([t['name'] for t in TOOLS])}{RESET}")
    print(f"{DIM}注意: task_* 工具操作磁盘上的 .tasks/ 目录{RESET}")
    print()

    # 启动时打印当前的任务状态（如果有）
    if list(TASKS_DIR.glob("task_*.json")):
        separator("启动时已有任务")
        print_tasks_dir()
        print()

    history = []
    while True:
        try:
            query = input(f"{CYAN}s07 >> {RESET}")
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
