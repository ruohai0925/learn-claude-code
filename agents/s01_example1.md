# s01 实际运行追踪：终端输出 ↔ 代码逐行对应

> prompt: `What python files are in this directory?`
>
> 结果：2 轮 LLM 调用，1 次工具执行，4 条 messages

---

## 启动

**终端输出：**

```
=== s01 verbose 模式 ===
MODEL  = claude-sonnet-4-6
SYSTEM = You are a coding agent at /home/yzeng/Codes/learn-claude-code. Use bash to solve tasks. Act, don't explain.
TOOLS  = ["bash"]
```

**对应代码：** `__main__` 第 168-173 行

```python
print(f"=== s01 verbose 模式 ===")
print(f"MODEL  = {MODEL}")                                    # → claude-sonnet-4-6
print(f"SYSTEM = {SYSTEM}")                                    # → You are a coding agent at ...
print(f"TOOLS  = {json.dumps([t['name'] for t in TOOLS])}")    # → ["bash"]

history = []    # 此时 history 是空列表
```

---

## 用户输入

**终端输出：**

```
s01 >> What python files are in this directory?

──────────────────── 用户输入 ────────────────────
query = "What python files are in this directory?"
```

**对应代码：** `__main__` 第 178-186 行

```python
query = input("s01 >> ")                                # 你输入了 "What python files are in this directory?"
history.append({"role": "user", "content": query})      # history 现在有 1 条消息
agent_loop(history)                                     # → 进入核心循环
```

---

## 轮次 1：发送给 LLM

**终端输出：**

```
──────────────────── 轮次 1: 发送给 LLM ────────────────────
messages = [
  [0] user: "What python files are in this directory?"
]

→ 调用 client.messages.create(...)
```

**对应代码：** `agent_loop` 第 130-141 行

```python
loop_round = 1                          # 第 1 轮

print_messages(messages)                # 打印 messages 快照 → 只有 [0] 一条

response = client.messages.create(      # 把 messages + tools 发给 LLM API
    model=MODEL,                        #   用 claude-sonnet-4-6
    system=SYSTEM,                      #   系统提示词
    messages=messages,                  #   当前只有 1 条 user 消息
    tools=TOOLS,                        #   告诉 LLM 它有 bash 工具
    max_tokens=8000,
)
```

**此时 messages 状态：** 1 条

```
[0] user: "What python files are in this directory?"
```

---

## 轮次 1：LLM 回复

**终端输出：**

```
──────────────────── 轮次 1: LLM 回复 ────────────────────
response.stop_reason = "tool_use"
response.content = [
  ToolUseBlock: name="bash", id="toolu_01GppbwjGwTHh1HFwW6fBXA9",
                input={"command": "find /home/yzeng/Codes/learn-claude-code -name \"*.py\" -type f"}
]
```

**解读：**

- `stop_reason = "tool_use"` → LLM 说"我想调用工具，先别结束"
- `ToolUseBlock` → LLM 想调用 `bash`，命令是 `find ... -name "*.py"`
- `id = "toolu_01Gpp..."` → 这次调用的唯一 ID，返回结果时要带上

**对应代码：** `agent_loop` 第 143-152 行

```python
print_response(response)                                            # 打印上面这段

messages.append({"role": "assistant", "content": response.content}) # 追加 LLM 回复到 messages

if response.stop_reason != "tool_use":   # "tool_use" != "tool_use" → False
    return                               # → 不 return，继续往下执行工具
```

**此时 messages 状态：** 2 条

```
[0] user:      "What python files are in this directory?"
[1] assistant: [ToolUseBlock: bash("find ... -name *.py -type f")]
```

---

## 轮次 1：执行工具

**终端输出：**

```
──────────────────── 轮次 1: 执行工具 ────────────────────
执行: bash("find /home/yzeng/Codes/learn-claude-code -name "*.py" -type f")
输出 (1344 字符):
/home/yzeng/Codes/learn-claude-code/agents/s10_team_protocols.py
/home/yzeng/Codes/learn-claude-code/agents/s12_worktree_task_isolation.py
/home/yzeng/Codes/learn-claude-code/agents/s05_skill_loading.py
/home/yzeng/Codes/learn-claude-code/agents/s_full.py
/home/yzeng/Codes/learn-claude-code/agents/s...

→ tool_result 已塞回 messages，继续下一轮...
```

**对应代码：** `agent_loop` 第 154-165 行

```python
results = []
for block in response.content:
    if block.type == "tool_use":
        output = run_bash(block.input["command"])           # 实际执行 find 命令 → 拿到 1344 字符
        print(output[:300])                                 # 终端只显示前 300 字符（你看到了截断的 "s...")
        results.append({
            "type": "tool_result",
            "tool_use_id": block.id,                        # 带上 "toolu_01Gpp..." 这个 ID
            "content": output,                              # 完整的 1344 字符都给 LLM
        })

messages.append({"role": "user", "content": results})      # 作为 user 消息塞回去
# → 回到 while True 顶部，进入轮次 2
```

**此时 messages 状态：** 3 条

```
[0] user:      "What python files are in this directory?"
[1] assistant: [ToolUseBlock: bash("find ... -name *.py -type f")]
[2] user:      [tool_result: "/home/yzeng/.../s10_team_protocols.py\n..." (1344字符)]
```

注意 `[2]` 的 role 是 **user**——工具执行结果是以 user 身份塞回去的。

---

## 轮次 2：发送给 LLM

**终端输出：**

```
──────────────────── 轮次 2: 发送给 LLM ────────────────────
messages = [
  [0] user: "What python files are in this directory?"
  [1] assistant/tool_use: bash({"command": "find /home/yzeng/Codes/learn-claude-code -name \"*.py\" -type f"})
  [2] user/tool_result: "/home/yzeng/Codes/learn-claude-code/agents/s10_team_protocols.py
/home/yzeng/Cod..."
]

→ 调用 client.messages.create(...)
```

**这是理解 Agent 循环的关键时刻。** 对比轮次 1，messages 从 1 条变成了 3 条：

| 索引 | role | 内容 | 谁产生的 |
|---|---|---|---|
| [0] | user | 你的问题 | 你输入的 |
| [1] | assistant | bash("find ...") | LLM 在轮次 1 回复的 |
| [2] | user | tool_result (1344 字符) | 程序执行工具后塞回去的 |

LLM 这次能看到完整的对话历史：你问了什么 → 它请求了什么命令 → 命令输出了什么。有足够信息给最终回答了。

**对应代码：** 和轮次 1 一样的 `client.messages.create(...)`，只是 messages 多了 2 条。

---

## 轮次 2：LLM 回复

**终端输出：**

```
──────────────────── 轮次 2: LLM 回复 ────────────────────
response.stop_reason = "end_turn"
response.content = [
  TextBlock: "Here are the Python files found in the directory, organized by folder:

**`agents/`**
- `__init__.py`
- `s01_agent_loop...."
]
```

**解读：**

- `stop_reason = "end_turn"` → 不再是 `"tool_use"`！LLM 说"我说完了"
- `TextBlock`（不是 `ToolUseBlock`）→ 这次是纯文字回答，不需要再调工具

---

## 轮次 2：循环结束

**终端输出：**

```
──────────────────── 轮次 2: 循环结束 ────────────────────
stop_reason = "end_turn" → 不是 "tool_use"，return!
```

**对应代码：** `agent_loop` 第 147-152 行

```python
messages.append({"role": "assistant", "content": response.content})

if response.stop_reason != "tool_use":   # "end_turn" != "tool_use" → True!
    return                               # → agent_loop 结束，回到 __main__
```

---

## 最终回答

**终端输出：**

```
──────────────────── 最终回答 ────────────────────
Here are the Python files found in the directory, organized by folder:

**`agents/`**
- `__init__.py`
- `s01_agent_loop.py`
- `s02_tool_use.py`
- `s03_todo_write.py`
- `s04_subagent.py`
- `s05_skill_loading.py`
- `s06_context_compact.py`
- `s07_task_system.py`
- `s08_background_tasks.py`
- `s09_agent_teams.py`
- `s10_team_protocols.py`
- `s11_autonomous_agents.py`
- `s12_worktree_task_isolation.py`
- `s_full.py`

**`tests/`**
- `test_agents_smoke.py`
- `test_s_full_background.py`

**`skills/agent-builder/scripts/`**
- `init_agent.py`

**`skills/agent-builder/references/`**
- `minimal-agent.py`
- `subagent-pattern.py`
- `tool-templates.py`

In total, there are **20 Python files** across the project.
```

**对应代码：** `__main__` 第 190-196 行

```python
response_content = history[-1]["content"]       # 取 history 最后一条（LLM 的最终回复）
if isinstance(response_content, list):          # content 是 block 列表
    for block in response_content:
        if hasattr(block, "text"):              # 找到 TextBlock
            print(block.text)                   # → 打印 "Here are the Python files..."
```

然后 `s01 >>` 再次出现，等待下一个问题。`history` 没有清空——如果继续提问，LLM 能看到之前所有对话。

---

## 总结

```
messages 的增长过程：

[]                                                                              开始
  ↓ 用户输入
[0] user: "What python files are in this directory?"                            1 条
  ↓ 轮次 1：LLM 回复 (stop_reason = "tool_use")
[0] user: 问题
[1] assistant: bash("find ... *.py")                                            2 条
  ↓ 轮次 1：执行工具，结果塞回去
[0] user: 问题
[1] assistant: bash("find ... *.py")
[2] user: tool_result (1344 字符)                                               3 条
  ↓ 轮次 2：LLM 回复 (stop_reason = "end_turn")
[0] user: 问题
[1] assistant: bash("find ... *.py")
[2] user: tool_result (1344 字符)
[3] assistant: "Here are the Python files..."                                   4 条
```

**4 条消息，2 轮 LLM 调用，1 次工具执行。**
