#!/usr/bin/env python3
# Harness: on-demand knowledge -- domain expertise, loaded when the model asks.
"""
s05_skill_loading.py - Skills

Two-layer skill injection that avoids bloating the system prompt:

    Layer 1 (cheap): skill names in system prompt (~100 tokens/skill)
    Layer 2 (on demand): full skill body in tool_result

    skills/
      pdf/
        SKILL.md          <-- frontmatter (name, description) + body
      code-review/
        SKILL.md

    System prompt:
    +--------------------------------------+
    | You are a coding agent.              |
    | Skills available:                    |
    |   - pdf: Process PDF files...        |  <-- Layer 1: metadata only
    |   - code-review: Review code...      |
    +--------------------------------------+

    When model calls load_skill("pdf"):
    +--------------------------------------+
    | tool_result:                         |
    | <skill>                              |
    |   Full PDF processing instructions   |  <-- Layer 2: full body
    |   Step 1: ...                        |
    |   Step 2: ...                        |
    | </skill>                             |
    +--------------------------------------+

Key insight: "Don't put everything in the system prompt. Load on demand."
"""

import json
import os
import re
import subprocess
import yaml
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]
SKILLS_DIR = WORKDIR / "skills"


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


# ── s05 核心概念：SkillLoader —— 两层技能注入 ──────────────
#
# 问题：如果把所有领域知识（PDF 处理、代码审查、MCP 构建……）
#       全塞进 system prompt，10 个 skill × 2000 token = 20,000 token，
#       每次 API 调用都要付这 20,000 的成本，哪怕用户只需要其中 1 个。
#
# 解法：分两层——
#
#   Layer 1（system prompt 里，始终存在）：
#     只放 skill 的名字 + 一句话描述，每个 ~100 token
#     → LLM 知道"有哪些 skill 可用"，但不知道具体内容
#
#   Layer 2（tool_result 里，按需加载）：
#     LLM 调用 load_skill("pdf") 时，把完整的 SKILL.md body 返回
#     → LLM 此刻才看到完整的 PDF 处理教程
#
# 类比：Layer 1 是图书馆的目录卡片，Layer 2 是把书从书架上拿下来翻开看。
#       你不会把图书馆所有书都摊在桌上——你先看目录，找到需要的那本，再取出来。
#
# 文件结构：
#   skills/
#     pdf/SKILL.md           ← YAML frontmatter（name, description）+ Markdown body
#     code-review/SKILL.md
#     agent-builder/SKILL.md
#     mcp-builder/SKILL.md

class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills = {}
        self._load_all()

    def _load_all(self):
        """扫描 skills/ 目录下所有 SKILL.md，解析 frontmatter。"""
        if not self.skills_dir.exists():
            return
        for f in sorted(self.skills_dir.rglob("SKILL.md")):
            text = f.read_text()
            meta, body = self._parse_frontmatter(text)
            name = meta.get("name", f.parent.name)
            self.skills[name] = {"meta": meta, "body": body, "path": str(f)}

    # ── YAML frontmatter 解析 ──────────────────────────────
    #
    # SKILL.md 文件格式：
    #   ---
    #   name: pdf
    #   description: Process PDF files...
    #   ---
    #   # PDF Processing Skill
    #   （完整的 Markdown body）
    #
    # _parse_frontmatter 把文件拆成两部分：
    #   meta = {"name": "pdf", "description": "Process PDF files..."}  ← Layer 1 用
    #   body = "# PDF Processing Skill\n..."                           ← Layer 2 用

    def _parse_frontmatter(self, text: str) -> tuple:
        """Parse YAML frontmatter between --- delimiters."""
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        return meta, match.group(2).strip()

    # ── Layer 1：给 system prompt 用的简短描述 ──────────────
    #
    # 输出类似：
    #   - pdf: Process PDF files - extract text, create PDFs, merge documents.
    #   - code-review: Perform thorough code reviews with security...
    #   - agent-builder: Design and build AI agents for any domain...
    #   - mcp-builder: Build MCP servers that give Claude new capabilities.
    #
    # 注意：只有 name + description，没有 body。
    # 这段文字直接嵌进 SYSTEM prompt，每次 API 调用都会发送。
    # 所以要短——每个 skill ~100 token，4 个 skill ~400 token，可以接受。

    def get_descriptions(self) -> str:
        """Layer 1: short descriptions for the system prompt."""
        if not self.skills:
            return "(no skills available)"
        lines = []
        for name, skill in self.skills.items():
            desc = skill["meta"].get("description", "No description")
            tags = skill["meta"].get("tags", "")
            line = f"  - {name}: {desc}"
            if tags:
                line += f" [{tags}]"
            lines.append(line)
        return "\n".join(lines)

    # ── Layer 2：完整的 skill body，按需返回 ──────────────
    #
    # 当 LLM 调用 load_skill("pdf") 时，返回：
    #   <skill name="pdf">
    #   # PDF Processing Skill
    #   （完整的 Markdown body，可能有 2000+ token）
    #   </skill>
    #
    # 这段内容作为 tool_result 塞进 messages——不在 system prompt 里。
    # 只有 LLM 请求时才加载，不请求就不花 token。
    #
    # <skill> 标签是一种约定：帮 LLM 识别"这是一个 skill 的内容"，
    # 和普通的 tool_result（比如 read_file 的输出）区分开。

    def get_content(self, name: str) -> str:
        """Layer 2: full skill body returned in tool_result."""
        skill = self.skills.get(name)
        if not skill:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"


SKILL_LOADER = SkillLoader(SKILLS_DIR)

# ── Layer 1 嵌入 system prompt ──────────────────────────────
#
# SYSTEM prompt 的结构：
#   "You are a coding agent at {WORKDIR}.
#    Use load_skill to access specialized knowledge before tackling unfamiliar topics.
#
#    Skills available:
#      - pdf: Process PDF files...
#      - code-review: Perform thorough code reviews...
#      - agent-builder: Design and build AI agents...
#      - mcp-builder: Build MCP servers..."
#
# LLM 看到这段就知道：
#   1. 有 4 个 skill 可用
#   2. 每个 skill 是做什么的（一句话描述）
#   3. 用 load_skill 工具可以加载具体内容
#
# 对比 s04：s04 的 SYSTEM 是纯静态字符串，s05 的 SYSTEM 是动态生成的
# （包含了从 skills/ 目录扫描到的 skill 列表）。
# 加了新的 skills/ 子目录 → 重启程序 → SYSTEM 自动更新。

SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use load_skill to access specialized knowledge before tackling unfamiliar topics.

Skills available:
{SKILL_LOADER.get_descriptions()}"""


# ── 工具函数（和 s02-s04 一样）──────────────────────────────

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


# ── 派发表：多了 load_skill ──────────────────────────────────
#
# 对比 s04：
#   s04 多了 task 工具（需要特殊处理，调 run_subagent）
#   s05 多了 load_skill 工具（不需要特殊处理，直接查 TOOL_HANDLERS）
#
# load_skill 和 bash、read_file 一样，走统一的派发表——
# 它只是一个普通工具，返回的 tool_result 恰好是 skill 的 body 内容。
# 没有子循环、没有独立 messages、没有特殊分支。
# 这是 s05 相对于 s04 的一大简化。

TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_LOADER.get_content(kw["name"]),
}

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "load_skill", "description": "Load specialized knowledge by name.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string", "description": "Skill name to load"}}, "required": ["name"]}},
]


# ── Agent 循环（和 s01-s04 结构一样）──────────────────────────
#
# s05 的循环和 s02 一模一样：while True + 调 LLM + 派发工具 + 塞回结果。
# 没有 s03 的 todo nag，没有 s04 的子 Agent 分支。
#
# 唯一的区别在"循环外面"：
#   1. SYSTEM prompt 里多了 skill 描述（Layer 1）
#   2. TOOL_HANDLERS 里多了 load_skill（Layer 2）
#   3. TOOLS 列表里多了 load_skill 的定义
#
# 循环本身完全不知道 skill 的存在——它只是照常派发工具。
# 这说明 skill loading 是一个"非侵入式"的功能：
# 不需要改循环代码，只需要在外面加一个工具 + 改 system prompt。

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

                # ── s05 特有的 verbose：区分 load_skill 和其他工具 ──
                if block.name == "load_skill":
                    skill_name = block.input.get("name", "?")
                    print(f"{YELLOW}加载 skill: \"{skill_name}\"{RESET}")
                    print(f"{DIM}返回内容 ({len(str(output))} 字符):{RESET}")
                    # 只打印 skill body 的前 300 字符，避免刷屏
                    preview = str(output)[:300]
                    print(f"{DIM}{preview}{'...' if len(str(output)) > 300 else ''}{RESET}")
                else:
                    print(f"{YELLOW}执行: {block.name}({json.dumps(block.input, ensure_ascii=False)[:120]}){RESET}")
                    print(f"{DIM}输出 ({len(str(output))} 字符): {str(output)[:200]}{RESET}")

                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        messages.append({"role": "user", "content": results})
        print(f"\n{CYAN}→ tool_result 已塞回 messages，继续下一轮...{RESET}")


if __name__ == "__main__":
    # ── 启动时打印：展示 Layer 1 的效果 ──────────────────────
    print(f"{BOLD}=== s05 verbose 模式 ==={RESET}")
    print(f"{DIM}MODEL  = {MODEL}{RESET}")
    print()

    # 打印扫描到的 skill 列表
    separator("SkillLoader 扫描结果")
    print(f"{DIM}skills_dir = {SKILLS_DIR}{RESET}")
    print(f"{DIM}扫描到 {len(SKILL_LOADER.skills)} 个 skill:{RESET}")
    for name, skill in SKILL_LOADER.skills.items():
        desc = skill["meta"].get("description", "No description")
        body_len = len(skill["body"])
        # 截取 description 的第一行（避免多行 description 刷屏）
        desc_first_line = desc.split('\n')[0][:80]
        print(f"  {CYAN}{name}{RESET}: {desc_first_line}...")
        print(f"    {DIM}Layer 1 (system prompt): ~{len(desc)} 字符描述{RESET}")
        print(f"    {DIM}Layer 2 (tool_result):   ~{body_len} 字符完整 body{RESET}")
    print()

    # 打印完整的 SYSTEM prompt
    separator("SYSTEM prompt (包含 Layer 1)")
    print(f"{DIM}{SYSTEM}{RESET}")
    print()

    # 打印 TOOLS 列表
    separator("TOOLS 列表")
    print(f"{DIM}{json.dumps([t['name'] for t in TOOLS])}{RESET}")
    print()

    history = []
    while True:
        try:
            query = input(f"{CYAN}s05 >> {RESET}")
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
