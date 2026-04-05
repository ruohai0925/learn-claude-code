#!/usr/bin/env python3
# Harness: the loop -- the model's first connection to the real world.
"""
s01_agent_loop.py - The Agent Loop

The entire secret of an AI coding agent in one pattern:

    while stop_reason == "tool_use":
        response = LLM(messages, tools)
        execute tools
        append results

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> |  Tool   |
    |  prompt  |      |       |      | execute |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                          (loop continues)

This is the core loop: feed tool results back to the model
until the model decides to stop. Production agents layer
policy, hooks, and lifecycle controls on top.
"""

import json
import os
import subprocess

# readline 模块提供终端输入的行编辑和历史功能（上下箭头回溯等）
# macOS 的 libedit 实现与 GNU readline 有差异，需要特殊配置以正确处理 UTF-8 字符
# 如果系统没有 readline（如某些精简 Docker 镜像），跳过即可，不影响核心功能
try:
    import readline
    # #143 UTF-8 backspace fix for macOS libedit
    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')       # 允许输入 8-bit 字符（如中文）
    readline.parse_and_bind('set output-meta on')      # 允许输出 8-bit 字符
    readline.parse_and_bind('set convert-meta off')     # 不将 meta 字符转为 ESC 序列
    readline.parse_and_bind('set enable-meta-keybindings on')
except ImportError:
    pass

from anthropic import Anthropic      # Anthropic 官方 SDK，封装了 Messages API
from dotenv import load_dotenv       # 从 .env 文件加载环境变量

# ── 环境变量加载链：.env 文件 → os.environ → 代码各处读取 ──
#
# 第 1 步：load_dotenv 解析 .env 文件，将 KEY=VALUE 逐行注入 os.environ
#   .env 中生效的变量示例：
#     ANTHROPIC_API_KEY="sk-ant-..."   → SDK 内部自动读取，用于 API 鉴权
#     MODEL_ID=claude-sonnet-4-6       → 代码显式读取，指定使用哪个模型
#     ANTHROPIC_BASE_URL=...           → 可选，自定义 API 端点（注释掉则用官方默认）
#
# override=True：即使终端已 export 了同名变量，.env 的值也会覆盖它，方便本地调试
load_dotenv(override=True)

# 第 2 步：处理自定义 API 端点的兼容逻辑
# 当设置了 ANTHROPIC_BASE_URL（如代理、私有部署、第三方兼容服务）时，
# 移除可能冲突的 ANTHROPIC_AUTH_TOKEN，让 SDK 统一使用 ANTHROPIC_API_KEY 认证
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# 第 3 步：从 os.environ 读取变量，初始化客户端和配置
#
# os.getenv("ANTHROPIC_BASE_URL") → 未设置时返回 None，SDK 使用默认端点 https://api.anthropic.com
# ANTHROPIC_API_KEY → SDK 内部约定从 os.environ 自动读取，代码中无需显式传入
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))

# os.environ["MODEL_ID"] → 用 [] 而非 getenv()：缺失时直接 KeyError 崩溃
# 这是有意为之——模型 ID 是必须项，早崩溃比静默出错好
MODEL = os.environ["MODEL_ID"]

# System prompt——agent 的"人设"，三个关键点：
#   1. 告知 LLM 它是一个 coding agent（定义角色）
#   2. 告知当前工作目录（提供环境上下文）
#   3. "Act, don't explain"——引导 LLM 直接执行命令而非只输出解释
SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don't explain."

TOOLS = [{
    "name": "bash",
    "description": "Run a shell command.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}]


# ── 打印工具 ──────────────────────────────────────────────

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
                        print(f"{DIM}  [{i}] {role}/tool_use: {block.name}({json.dumps(block.input, ensure_ascii=False)}){RESET}")
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
            print(f"{GREEN}  ToolUseBlock: name=\"{block.name}\", id=\"{block.id}\", input={json.dumps(block.input, ensure_ascii=False)}{RESET}")
    print(f"{GREEN}]{RESET}")


def run_bash(command: str) -> str:
    # 1) 安全护栏：子串匹配拦截危险命令（教学级，生产中需更严格的沙箱）
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        # 2) shell=True 支持管道/重定向；timeout 防止命令挂起占死 agent
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=120)
        # 3) 分别处理 stdout（正常输出）和 stderr（错误/警告输出）
        #    stdout: 命令的标准输出，如 ls 的文件列表、cat 的文件内容
        #    stderr: 编译错误、警告信息、命令未找到等诊断信息
        #    合并后让 LLM 同时看到结果和错误，便于自行判断下一步
        out = r.stdout.strip()
        err = r.stderr.strip()
        if out and err:
            combined = f"{out}\n[stderr]\n{err}"
        elif err:
            combined = f"[stderr]\n{err}"
        else:
            combined = out
        # 4) 截断到 50000 字符，防止巨量输出撑爆 LLM 上下文窗口
        return combined[:50000] if combined else "(no output)"
    except subprocess.TimeoutExpired:
        # 5) 异常不抛出，返回错误字符串——让 LLM（而非程序）决定如何应对
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"


# -- The core pattern: a while loop that calls tools until the model stops --
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

        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})
        # If the model didn't call a tool, we're done
        if response.stop_reason != "tool_use":
            separator(f"轮次 {loop_round}: 循环结束")
            print(f"{BOLD}stop_reason = \"{response.stop_reason}\" → 不是 \"tool_use\"，return!{RESET}")
            return
        # Execute each tool call, collect results
        separator(f"轮次 {loop_round}: 执行工具")
        results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"{YELLOW}执行: bash(\"{block.input['command']}\"){RESET}")
                output = run_bash(block.input["command"])
                print(f"{DIM}输出 ({len(output)} 字符):{RESET}")
                print(output[:300] + ("..." if len(output) > 300 else ""))
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": output})
        messages.append({"role": "user", "content": results})
        print(f"\n{CYAN}→ tool_result 已塞回 messages，继续下一轮...{RESET}")


if __name__ == "__main__":
    print(f"{BOLD}=== s01 verbose 模式 ==={RESET}")
    print(f"{DIM}MODEL  = {MODEL}{RESET}")
    print(f"{DIM}SYSTEM = {SYSTEM}{RESET}")
    print(f"{DIM}TOOLS  = {json.dumps([t['name'] for t in TOOLS])}{RESET}")
    print()

    history = []
    while True:
        try:
            query = input(f"{CYAN}s01 >> {RESET}")
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
