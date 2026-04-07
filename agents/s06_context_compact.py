#!/usr/bin/env python3
# Harness: compression -- clean memory for infinite sessions.
"""
s06_context_compact.py - Compact

Three-layer compression pipeline so the agent can work forever:

    Every turn:
    +------------------+
    | Tool call result |
    +------------------+
            |
            v
    [Layer 1: micro_compact]        (silent, every turn)
      Replace non-read_file tool_result content older than last 3
      with "[Previous: used {tool_name}]"
            |
            v
    [Check: tokens > THRESHOLD?]
       |               |
       no              yes
       |               |
       v               v
    continue    [Layer 2: auto_compact]
                  Save full transcript to .transcripts/
                  Ask LLM to summarize conversation.
                  Replace all messages with [summary].
                        |
                        v
                [Layer 3: compact tool]
                  Model calls compact -> immediate summarization.
                  Same as auto, triggered manually.

Key insight: "The agent can forget strategically and keep working forever."
"""

import json
import os
import subprocess
import time
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks."


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


# ── s06 核心概念：三层压缩管道 ──────────────────────────────
#
# 问题：context window 是有限的。一个 1000 行的文件 ≈ 4000 token，
#       读 30 个文件 + 跑 20 个 bash 命令 → 100,000+ token → 撑爆。
#       s05 的 skill body 持久留在 messages 里也会加剧这个问题。
#
# 解法：三层压缩，逐级递进——
#
#   Layer 1（micro_compact）：每一轮自动执行，静默替换旧的 tool_result
#     → "温和压缩"，保留最近 3 个结果，旧的替换为占位符
#
#   Layer 2（auto_compact）：token 超过阈值时自动触发
#     → "激进压缩"，保存完整 transcript 到磁盘，让 LLM 总结，然后
#       用一条 summary 替换全部 messages
#
#   Layer 3（compact 工具）：LLM 主动调用 compact 工具手动触发
#     → 和 Layer 2 一样的逻辑，但由 LLM 决定何时触发
#
# 类比：手机存储管理
#   Layer 1 = 自动清理缓存（每天，你感觉不到）
#   Layer 2 = 存储满了自动把旧照片移到云端（你收到通知）
#   Layer 3 = 你手动点"立即清理"按钮

# ── 关键配置 ──────────────────────────────────────────────
#
# THRESHOLD: 触发 auto_compact 的 token 阈值。
#   生产环境可能设 80,000-100,000（Claude 的 context window 是 200K）。
#   教学演示设低一些（12000），这样读 3-4 个文件就能触发 auto_compact，
#   不需要积累太多 token（避免撞 API rate limit）。
#
# KEEP_RECENT: 保留最近 3 个 tool_result 不被 micro_compact 替换。
#   为什么是 3？因为 LLM 通常需要最近几轮的工具输出来理解当前状态。
#   太少（1）→ LLM 丢失了刚执行的命令的上下文
#   太多（10）→ micro_compact 几乎不起作用
#
# PRESERVE_RESULT_TOOLS: {"read_file"} 的结果永远不被替换。
#   为什么？因为 read_file 的输出是"参考材料"——LLM 可能需要反复查阅。
#   如果压缩了，LLM 就得重新读文件，浪费一次工具调用。
#   而 bash 的输出通常是"执行确认"（如 "Wrote 321 bytes"），压缩后
#   用 "[Previous: used bash]" 替代完全够用。
#
# RATE_LIMIT_RETRY: 遇到 429 rate limit 时自动等待重试。
#   因为我们的 API plan 只有 30,000 input token/分钟的限额，
#   读几个大文件就可能撞上。简单地等 60 秒再重试即可。

THRESHOLD = 12000
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
KEEP_RECENT = 3
PRESERVE_RESULT_TOOLS = {"read_file"}


RATE_LIMIT_MAX_RETRIES = 3
RATE_LIMIT_WAIT = 60  # seconds


def estimate_tokens(messages: list) -> int:
    """粗略估算 token 数：~4 字符/token。"""
    return len(str(messages)) // 4


# ── Rate limit 重试 ──────────────────────────────────────
#
# 我们的 API plan 只有 30K input token/分钟。读几个大文件后，
# messages 本身就有几千 token，每次 API 调用都发送全部 messages，
# 很容易撞 rate limit。
#
# 解法很简单：捕获 429 错误，等 60 秒，重试。
# 生产环境会用指数退避（exponential backoff），但教学演示里等固定时间就够了。

def api_call_with_retry(create_fn):
    """包装 API 调用，遇到 rate limit 自动等待重试。"""
    for attempt in range(RATE_LIMIT_MAX_RETRIES):
        try:
            return create_fn()
        except Exception as e:
            if "rate_limit" in str(type(e).__name__).lower() or "429" in str(e):
                wait = RATE_LIMIT_WAIT * (attempt + 1)
                print(f"{RED}Rate limit! 等待 {wait} 秒后重试 ({attempt+1}/{RATE_LIMIT_MAX_RETRIES})...{RESET}")
                time.sleep(wait)
            else:
                raise
    # 最后一次不捕获异常，让它自然抛出
    return create_fn()


# ── Layer 1: micro_compact —— 静默替换旧的 tool_result ──────
#
# 每一轮循环开始时自动执行。它做的事情很简单：
#
# 1. 扫描所有 messages，找到所有 tool_result
# 2. 按出现顺序排列，保留最近 KEEP_RECENT 个
# 3. 把更早的 tool_result 的 content 替换为 "[Previous: used {tool_name}]"
#
# 例外：
#   - content 长度 <= 100 的不替换（已经够短了，压缩没意义）
#   - read_file 的结果不替换（PRESERVE_RESULT_TOOLS）
#
# 注意：micro_compact 是**原地修改** messages 列表里的 dict 对象。
# 它不创建新的 messages 列表，而是直接改 part["content"] = "..."。
# 这意味着旧的 tool_result 内容**永久丢失**（除非 auto_compact 之前
# 保存了 transcript）。

def micro_compact(messages: list) -> list:
    """Layer 1: 静默替换旧的 tool_result 为占位符。"""
    # 收集所有 tool_result 的位置
    tool_results = []
    for msg_idx, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            for part_idx, part in enumerate(msg["content"]):
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    tool_results.append((msg_idx, part_idx, part))
    if len(tool_results) <= KEEP_RECENT:
        return messages

    # 构建 tool_use_id → tool_name 映射
    # （因为 tool_result 里只有 tool_use_id，没有 tool_name）
    tool_name_map = {}
    for msg in messages:
        if msg["role"] == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "type") and block.type == "tool_use":
                        tool_name_map[block.id] = block.name

    # 替换旧的 tool_result（保留最近 KEEP_RECENT 个）
    to_clear = tool_results[:-KEEP_RECENT]
    replaced_count = 0
    preserved_count = 0
    for _, _, result in to_clear:
        if not isinstance(result.get("content"), str) or len(result["content"]) <= 100:
            continue
        tool_id = result.get("tool_use_id", "")
        tool_name = tool_name_map.get(tool_id, "unknown")
        if tool_name in PRESERVE_RESULT_TOOLS:
            preserved_count += 1
            continue
        old_len = len(result["content"])
        result["content"] = f"[Previous: used {tool_name}]"
        replaced_count += 1

    if replaced_count > 0 or preserved_count > 0:
        separator("Layer 1: micro_compact")
        print(f"{YELLOW}tool_result 总数: {len(tool_results)}, 保留最近 {KEEP_RECENT} 个{RESET}")
        print(f"{YELLOW}替换了 {replaced_count} 个旧 tool_result → \"[Previous: used ...]\" {RESET}")
        if preserved_count > 0:
            print(f"{YELLOW}保留了 {preserved_count} 个 read_file 结果（PRESERVE_RESULT_TOOLS）{RESET}")
        tokens_after = estimate_tokens(messages)
        print(f"{DIM}压缩后 token 估算: ~{tokens_after}{RESET}")

    return messages


# ── Layer 2: auto_compact —— 保存 transcript + LLM 总结 ──────
#
# 当 estimate_tokens(messages) > THRESHOLD 时自动触发。
#
# 它做两件事：
#   1. 把完整的 messages 保存到 .transcripts/ 目录（JSONL 格式）
#      → 这是"安全网"——压缩后原始对话不会真正丢失
#   2. 让 LLM 总结整个对话（另起一次 API 调用，不在主循环里）
#      → 返回一条 summary，替换掉全部 messages
#
# 压缩后 messages 变成只有 1 条消息：
#   [{"role": "user", "content": "[Conversation compressed...]\n\n{summary}"}]
#
# 这是最激进的压缩——从可能几十条 messages 压到 1 条。
# 代价是 LLM 丢失了所有细节，只保留了 summary 里的信息。
#
# 注意 messages[:] = ... 的写法：
#   这是 Python 的"切片赋值"，原地替换列表内容（不创建新列表）。
#   因为 agent_loop 外面的 history 变量也指向同一个列表对象，
#   所以 messages[:] = ... 会同时更新 history。
#   如果写 messages = ...（不带 [:]），只会改变局部变量，history 不受影响。

def auto_compact(messages: list) -> list:
    """Layer 2: 保存 transcript 到磁盘，让 LLM 总结，替换全部 messages。"""
    # 保存完整 transcript
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(transcript_path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")

    separator("Layer 2: auto_compact — 保存 transcript")
    print(f"{YELLOW}transcript 保存到: {transcript_path}{RESET}")
    print(f"{YELLOW}原始 messages: {len(messages)} 条{RESET}")

    # 让 LLM 总结（独立的 API 调用，不在主循环里）
    separator("Layer 2: auto_compact — LLM 总结")
    conversation_text = json.dumps(messages, default=str)[-80000:]
    print(f"{CYAN}→ 调用 client.messages.create(...)（总结用，非主循环）{RESET}")
    print(f"{DIM}发送 conversation_text 最后 {len(conversation_text)} 字符给 LLM 做总结{RESET}")

    # 总结调用也用 api_call_with_retry 包装——
    # 因为它紧跟在主循环的 API 调用之后，rate limit 额度可能已经快用完了。
    response = api_call_with_retry(lambda: client.messages.create(
        model=MODEL,
        messages=[{"role": "user", "content":
            "Summarize this conversation for continuity. Include: "
            "1) What was accomplished, 2) Current state, 3) Key decisions made. "
            "Be concise but preserve critical details.\n\n" + conversation_text}],
        max_tokens=2000,
    ))
    summary = next((block.text for block in response.content if hasattr(block, "text")), "")
    if not summary:
        summary = "No summary generated."

    separator("Layer 2: auto_compact — 压缩结果")
    print(f"{BOLD}原始: {len(messages)} 条 messages → 压缩后: 1 条{RESET}")
    print(f"{GREEN}summary ({len(summary)} 字符):{RESET}")
    print(f"{DIM}{summary[:300]}{'...' if len(summary) > 300 else ''}{RESET}")

    # 替换全部 messages
    return [
        {"role": "user", "content": f"[Conversation compressed. Transcript: {transcript_path}]\n\n{summary}"},
    ]


# ── 工具函数（和 s02-s05 一样）──────────────────────────────

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


# ── 派发表：多了 compact 工具 ──────────────────────────────
#
# compact 工具和 s04 的 task 一样，需要在循环里做特殊处理（侵入式）。
# 因为 compact 的效果不是"返回一个字符串"，而是"替换全部 messages"——
# 这改变了循环的状态，不是普通的 tool handler 能做的。
#
# 对比 s05 的 load_skill（非侵入式，走统一派发表）：
#   load_skill: handler(**input) → 返回字符串 → 塞进 tool_result → 继续
#   compact:    设 manual_compact = True → 塞假的 tool_result → 循环结束后
#               调 auto_compact() 替换全部 messages

TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "compact":    lambda **kw: "Manual compression requested.",
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
    {"name": "compact", "description": "Trigger manual conversation compression.",
     "input_schema": {"type": "object", "properties": {"focus": {"type": "string", "description": "What to preserve in the summary"}}}},
]


# ── Agent 循环：三层压缩集成在循环的不同位置 ──────────────────
#
# 循环结构和 s01-s05 一样（while True + 调 LLM + 派发工具），
# 但在三个地方插入了压缩逻辑：
#
#   循环开始时：
#     → micro_compact(messages)         # Layer 1
#     → if tokens > THRESHOLD:
#           auto_compact(messages)      # Layer 2
#
#   工具执行时：
#     → if block.name == "compact":
#           manual_compact = True       # 标记 Layer 3
#
#   循环结束前：
#     → if manual_compact:
#           auto_compact(messages)      # Layer 3 执行
#           return                      # 压缩后结束本次循环
#
# 为什么 manual_compact 在循环结束时才执行（而不是工具执行时立刻执行）？
# 因为 compact 工具被调用时，还需要先把 tool_result 塞回 messages
# （API 要求 assistant 的 tool_use 必须有对应的 tool_result）。
# 如果立刻压缩，tool_result 还没塞回去，API 下次调用会报错。

def agent_loop(messages: list):
    loop_round = 0
    while True:
        loop_round += 1

        # ── Layer 1: micro_compact ──
        micro_compact(messages)

        # ── Layer 2: auto_compact（token 超阈值时触发）──
        tokens = estimate_tokens(messages)
        if tokens > THRESHOLD:
            separator(f"Layer 2: 触发! token 估算 ~{tokens} > {THRESHOLD}")
            messages[:] = auto_compact(messages)
            tokens = estimate_tokens(messages)

        separator(f"轮次 {loop_round}")
        print(f"{DIM}token 估算: ~{tokens} / {THRESHOLD}{RESET}")
        print_messages(messages)
        print(f"\n{CYAN}→ 调用 client.messages.create(...){RESET}")

        # ── api_call_with_retry 包装 ──────────────────────────
        #
        # s01-s05 里直接调 client.messages.create(...)，
        # 但 s06 的场景容易撞 rate limit：
        #   - 读大量文件 → messages 膨胀 → 每次 API 调用发送的 input token 增多
        #   - micro_compact 保护 read_file 结果 → 大量文件内容留在 messages 里
        #   - auto_compact 的总结调用本身也消耗额度
        #
        # api_call_with_retry 是一个简单的重试包装：
        #   捕获 429 RateLimitError → 等 60 秒 → 重试（最多 3 次）
        #   不是 s06 的核心概念，但对教学演示来说是必要的——
        #   否则读几个大文件就会崩溃，看不到压缩管道的效果。
        response = api_call_with_retry(lambda: client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        ))

        separator(f"轮次 {loop_round}: 回复")
        print_response(response)

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            separator(f"轮次 {loop_round}: 循环结束")
            print(f"{BOLD}stop_reason = \"{response.stop_reason}\" → return!{RESET}")
            return

        separator(f"轮次 {loop_round}: 执行工具")
        results = []
        manual_compact = False
        for block in response.content:
            if block.type == "tool_use":
                if block.name == "compact":
                    # ── Layer 3: compact 工具（标记，稍后执行）──
                    manual_compact = True
                    output = "Compressing..."
                    print(f"{RED}compact 工具被调用! 将在本轮结束后执行压缩{RESET}")
                else:
                    handler = TOOL_HANDLERS.get(block.name)
                    try:
                        output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                    except Exception as e:
                        output = f"Error: {e}"
                    print(f"{YELLOW}执行: {block.name}({json.dumps(block.input, ensure_ascii=False)[:120]}){RESET}")
                    print(f"{DIM}输出 ({len(str(output))} 字符): {str(output)[:200]}{RESET}")

                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        messages.append({"role": "user", "content": results})

        # ── Layer 3: manual compact 执行 ──
        if manual_compact:
            separator("Layer 3: manual compact 执行")
            messages[:] = auto_compact(messages)
            return

        print(f"\n{CYAN}→ tool_result 已塞回 messages，继续下一轮...{RESET}")


if __name__ == "__main__":
    print(f"{BOLD}=== s06 verbose 模式 ==={RESET}")
    print(f"{DIM}MODEL     = {MODEL}{RESET}")
    print(f"{DIM}THRESHOLD = {THRESHOLD} token（触发 auto_compact）{RESET}")
    print(f"{DIM}KEEP_RECENT = {KEEP_RECENT}（micro_compact 保留最近 N 个 tool_result）{RESET}")
    print(f"{DIM}PRESERVE_RESULT_TOOLS = {PRESERVE_RESULT_TOOLS}（这些工具的结果不被 micro_compact 替换）{RESET}")
    print(f"{DIM}TRANSCRIPT_DIR = {TRANSCRIPT_DIR}{RESET}")
    print()

    separator("TOOLS 列表")
    print(f"{DIM}{json.dumps([t['name'] for t in TOOLS])}{RESET}")
    print(f"{DIM}注意: compact 工具是 Layer 3（手动压缩）{RESET}")
    print()

    history = []
    while True:
        try:
            query = input(f"{CYAN}s06 >> {RESET}")
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
        elif isinstance(response_content, str):
            print(response_content[:500])
        print()
