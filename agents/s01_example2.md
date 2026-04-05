# s01 实际运行追踪（例 2）：多步任务

> prompt: `Create hello.py that prints hello, then run it`
>
> 结果：3 轮 LLM 调用，2 次工具执行，9 条新 messages
>
> **重点观察：** LLM 把一个任务拆成多步（写文件 → 运行文件），每步调一次工具，自己决定什么时候"做完了"。

---

## 用户输入

**终端输出：**

```
s01 >> Create hello.py that prints hello, then run it

──────────────────── 用户输入 ────────────────────
query = "Create hello.py that prints hello, then run it"
```

**对应代码：** `__main__` 第 219-229 行

```python
query = input("s01 >> ")
history.append({"role": "user", "content": query})
agent_loop(history)
```

---

## 轮次 1：发送给 LLM

**终端输出：**

```
──────────────────── 轮次 1: 发送给 LLM ────────────────────
messages = [
  [0] user: "What python files are in this directory?"
  [1] assistant/tool_use: bash({"command": "find ... -name \"*.py\" -type f"})
  [2] user/tool_result: "/home/yzeng/.../s10_team_protocols.py\n..."
  [3] assistant/text: "Here are the Python files found in the directory..."
  [4] user: "Create hello.py that prints hello, then run it"
]
```

**关键观察：** messages 里有 5 条！[0]-[3] 是例 1 留下来的历史。`history` 没有清空——LLM 能看到之前所有对话。新输入追加在 [4]。

**对应代码：** `agent_loop` 第 175-182 行

```python
print_messages(messages)    # 打印快照：[0]-[3] 是例 1 的，[4] 是新输入

response = client.messages.create(
    model=MODEL, system=SYSTEM, messages=messages,    # 5 条消息全部发给 LLM
    tools=TOOLS, max_tokens=8000,
)
```

---

## 轮次 1：LLM 回复 → 写文件

**终端输出：**

```
──────────────────── 轮次 1: LLM 回复 ────────────────────
response.stop_reason = "tool_use"
response.content = [
  ToolUseBlock: name="bash", id="toolu_013jCiD7o8FqTjemfVHsusKF",
                input={"command": "echo 'print(\"hello\")' > /home/yzeng/Codes/learn-claude-code/hello.py"}
]
```

**解读��** LLM 把任务拆成了两步，先做第一步——用 `echo` 写文件。`stop_reason = "tool_use"` 说明它知道还没完。

---

## 轮次 1：执行工具

**终端输出：**

```
──────────────────── 轮次 1: 执行工具 ────────────────────
执行: bash("echo 'print("hello")' > /home/yzeng/Codes/learn-claude-code/hello.py")
输出 (11 字符):
(no output)

→ tool_result 已塞回 messages，继续下一轮...
```

**解读：** `echo 'print("hello")' > hello.py` 这条命令把文字写进文件。`>` 把 stdout **重定向到文件**了——`echo` 本来会往 stdout 输出 `print("hello")`，但 `>` 把这个输出截走送进了 `hello.py`，不再经过 stdout。所以 `subprocess.run()` 捕获到的 `r.stdout` 是空的，`r.stderr` 也是空的，代码走到第 161 行 `return combined[:50000] if combined else "(no output)"`，返回 `"(no output)"`。这个字符串作为 `tool_result` 传给 LLM——LLM 看到没有报错信息，就知道文件写成功了，继续下一步。

对比后面轮次 2 执行的 `python hello.py`——没有 `>` 重定向，`print("hello")` 的结果正常走 stdout，`r.stdout` 就是 `"hello"`。同样一个 `run_bash()`，有没有 `>` 决定了 stdout 是空还是有内容。

**补充：stdout 和 stderr 是什么？**

每个终端命令运行时，有两条独立的输出通道：

| 通道 | 全称 | 用途 | 举例 |
|---|---|---|---|
| stdout | standard output（标准输出） | 命令的**正常结果** | `ls` 列出的文件列表、`cat` 打印的文件内容 |
| stderr | standard error（标准错误） | **错误和警告**信息 | `python: No such file`、编译报错、权限不足 |

为什么要分两条？因为你可能想只保存结果、忽略错误（或反过来）。比如：

```bash
python app.py > output.txt      # stdout 写进文件，stderr 仍然打印到终端
python app.py 2> errors.txt     # stderr 写进文件，stdout 仍然打印到终端
```

在 `run_bash()` 里（第 146-147 行），`capture_output=True` 让 `subprocess` 分别捕获两条通道：

```python
r = subprocess.run(command, shell=True, capture_output=True, text=True, ...)
r.stdout    # "hello"              ← 正常输出
r.stderr    # ""                   ← 没有错误
```

然后第 152-159 行把它们合并，一起传给 LLM：

```python
out = r.stdout.strip()
err = r.stderr.strip()
if out and err:
    combined = f"{out}\n[stderr]\n{err}"    # 两个都有 → 合并，用 [stderr] 标记
elif err:
    combined = f"[stderr]\n{err}"           # 只有错误 → 标记后传给 LLM
else:
    combined = out                          # 只有正常输出（最常见的情况）
```

为什么要合并给 LLM？因为 LLM 需要**同时看到结果和错误**才能判断下一步。比如编译一个文件，stdout 可能是空的，但 stderr 里有报错信息——LLM 看到后就知道要修 bug。

**对应代码：** `agent_loop` 第 195-206 行

```python
output = run_bash(block.input["command"])     # 执行 echo ... > hello.py
# output = "(no output)"                      # echo 重定向没有输出

results.append({
    "type": "tool_result",
    "tool_use_id": block.id,
    "content": output,                        # "(no output)" 也要传给 LLM
})
messages.append({"role": "user", "content": results})
# → 回到 while True，进入轮次 2
```

**此时 messages 状态：** 7 条

```
[0] user:      (例1) 问题
[1] assistant: (例1) bash("find ...")
[2] user:      (例1) tool_result
[3] assistant: (例1) 最终回答
[4] user:      "Create hello.py that prints hello, then run it"    ← 新输入
[5] assistant: bash("echo 'print(\"hello\")' > hello.py")          ← 轮次1 LLM回复
[6] user:      tool_result: "(no output)"                          ← 轮次1 工具结果
```

---

## 轮次 2：LLM 回复 → 运行文件

**终端输出：**

```
──────────────────── 轮次 2: LLM 回复 ────────────────────
response.stop_reason = "tool_use"
response.content = [
  ToolUseBlock: name="bash", id="toolu_011k3YVHjezjSdY2Dbmq1mCu",
                input={"command": "python /home/yzeng/Codes/learn-claude-code/hello.py"}
]
```

**解读：** LLM 看到写文件成功（虽然 no output，但没有报错），现在做第二步——运行文件。`stop_reason` 仍然是 `"tool_use"`，还没完。

---

## 轮次 2：执行工具

**终端输出：**

```
──────────────────── 轮次 2: 执行工具 ────────────────────
执行: bash("python /home/yzeng/Codes/learn-claude-code/hello.py")
输出 (5 字符):
hello

→ tool_result 已塞回 messages，继续下一轮...
```

**对应代码：** 同样的 `run_bash()` → `results.append()` → `messages.append()`

**此时 messages 状态：** 9 条

```
[0]-[3] (例1 的历史)
[4] user:      "Create hello.py that prints hello, then run it"
[5] assistant: bash("echo ... > hello.py")     ← 写文件
[6] user:      tool_result: "(no output)"
[7] assistant: bash("python hello.py")          ← 运行文件
[8] user:      tool_result: "hello"             ← 运行输出
```

---

## 轮次 3：LLM 回复 → 最终回答

**终端输出：**

```
──────────────────── 轮次 3: LLM 回复 ────────────────────
response.stop_reason = "end_turn"
response.content = [
  TextBlock: "Done! Created `hello.py` with a single `print("hello")` statement
             and ran it — it outputs **hello** as expected."
]

──────────────────── 轮次 3: 循环结束 ────────────────────
stop_reason = "end_turn" → 不是 "tool_use"，return!
```

**解读：** LLM 看到 `hello.py` 输出了 `hello`，确认两步都完成了，`stop_reason = "end_turn"`。

**注意 TextBlock 里的格式：** `` `hello.py` ``、`"hello"`、`**hello**`——为什么混用？

| 标记 | 含义 | 例子 |
|---|---|---|
| `` `hello.py` `` | 反引号 = 代码/文件名 | 这是一个文件名 |
| `"hello"` | 双引号 = 字符串字面值 | Python 代码里的字符串 |
| `**hello**` | 双星号 = 加粗强调 | 强调运行输出的关键结果 |

这些格式全是 LLM 自己选的 Markdown 排版，你的代码里没有任何地方控制这些。`TextBlock` 的内容完全由 LLM 生成，就像你在 ChatGPT 里看到的回复一样。换一个模型、换一次运行，措辞和格式可能完全不同。唯一不变的是外层结构（`TextBlock`、`ToolUseBlock`、`stop_reason`），因为那是 API 协议规定的。

**对应代码：** `agent_loop` 第 190-193 行

```python
if response.stop_reason != "tool_use":    # "end_turn" != "tool_use" → True!
    return                                # agent_loop 结束
```

---

## 总结：这一次交互的完整数据流

```
messages 的增长过程（只看 [4] 之后的新消息）：

[4] user: "Create hello.py that prints hello, then run it"
  ↓ 轮次 1：LLM 想写文件 (stop_reason = "tool_use")
[5] assistant: bash("echo ... > hello.py")
  ↓ 轮次 1：执行，无输出
[6] user: tool_result("(no output)")
  ↓ 轮次 2：LLM 想运行文件 (stop_reason = "tool_use")
[7] assistant: bash("python hello.py")
  ↓ 轮次 2：执行，输出 "hello"
[8] user: tool_result("hello")
  ↓ 轮次 3：LLM 确认完成 (stop_reason = "end_turn")
[9] assistant: "Done! Created hello.py ... outputs hello as expected."
```

**和例 1 的对比：**

| | 例 1 | 例 2 |
|---|---|---|
| 任务 | 查看文件 | 创建并运行文件 |
| LLM 调用轮次 | 2 轮 | 3 轮 |
| 工具执行次数 | 1 次 (find) | 2 次 (echo, python) |
| 新增 messages | 4 条 | 6 条 |
| 关键区别 | 单步任务 | **LLM 自己把任务拆成多步** |

**核心洞察：** 你只说了"创建并运行"，LLM 自己决定拆成两步。循环代码没有任何"拆步"逻辑——它只是���复问 LLM"你还要调工具吗？"，LLM 自己判断什么时候该停。
