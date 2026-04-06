# s03 实际运行追踪：todo 工具规划多步任务

> prompt: `Refactor the file hello.py: add type hints, docstrings, and a main guard`
>
> 结果：8 轮 LLM 调用，7 次工具执行（1x read_file + 4x todo + 1x write_file + 1x bash），15 条 messages
>
> **重点观察：** LLM 尝试同时标记 2 个任务为 in_progress，被 TodoManager 拒绝后自动纠正为 1 个。错误即教学——LLM 从 tool_result 中学习规则。

---

## 启动

**终端输出：**

```
=== s03 verbose 模式 ===
MODEL  = claude-sonnet-4-6
SYSTEM = You are a coding agent at /home/yzeng/Codes/learn-claude-code.
Use the todo tool to plan multi-step tasks. Mark in_progress before starting, completed when done.
Prefer tools over prose.
TOOLS  = ["bash", "read_file", "write_file", "edit_file", "todo"]
```

对比 s02 的启动：TOOLS 从 4 个变成 5 个，多了 `todo`。SYSTEM 也从 `"Use tools to solve tasks. Act, don't explain."` 变成了明确的 todo 使用指令：`"Use the todo tool to plan multi-step tasks. Mark in_progress before starting, completed when done."`

---

## 用户输入

**终端输出：**

```
s03 >> Refactor the file hello.py: add type hints, docstrings, and a main guard

──────────────────── 用户输入 ────────────────────
query = "Refactor the file hello.py: add type hints, docstrings, and a main guard"
```

注意这个任务天然是"多步"的：type hints、docstrings、main guard 是 3 件事。正是 todo 工具大展身手的场景。

**prompt 里的三个术语：**

| 术语 | 含义 | 例子 |
|---|---|---|
| **type hints**（类型标注） | 在代码里标明参数和返回值的类型。Python 不强制检查，是给人和 IDE 看的 | `def greet(name: str) -> None:` |
| **docstrings**（文档字符串） | 函数/类开头的三引号字符串，描述它做什么 | `"""Print a greeting message."""` |
| **main guard**（主入口守卫） | `if __name__ == "__main__":` 确保代码只在直接运行时执行，被 import 时不执行 | `if __name__ == "__main__": main()` |

---

## 第 1 轮：LLM 先读文件

**终端输出：**

```
──────────────────── 发送给 LLM (距上次 todo: 0 轮) ────────────────────
messages = [
  [0] user: "Refactor the file hello.py: add type hints, docstrings, and a main guard"
]

→ 调用 client.messages.create(...)

──────────────────── LLM 回复 ────────────────────
response.stop_reason = "tool_use"
response.content = [
  TextBlock: "Let me start by reading the existing file to understand what's there."
  ToolUseBlock: name="read_file", id="toolu_01PGoyUHCCmRNGQR4xUpXseR"
    input={"path": "/home/yzeng/Codes/learn-claude-code/hello.py"}
]

──────────────────── 执行工具 ────────────────────
执行: read_file({"path": "/home/yzeng/Codes/learn-claude-code/hello.py"})
输出 (14 字符):
print("hello")
```

**解读：** LLM 的第一反应不是规划，而是先读文件。这很合理——不知道文件长什么样就没法规划。结果发现 `hello.py` 只有一行 `print("hello")`。

和 [s02 例 1](s02_example1.md) 一样，LLM 选了 `read_file` 而不是 `bash("cat hello.py")`——有专用工具就用专用工具。

---

## 第 2 轮：LLM 创建 todo 列表

**终端输出：**

```
──────────────────── 发送给 LLM (距上次 todo: 1 轮) ────────────────────
messages = [
  [0] user: "Refactor the file hello.py: add type hints, docstrings, and a main guard"
  [1] assistant/text: "Let me start by reading the existing file to understand what's there."
  [1] assistant/tool_use: read_file({"path": "/home/yzeng/Codes/learn-claude-code/hello.py"})
  [2] user/tool_result: "print("hello")"
]

→ 调用 client.messages.create(...)

──────────────────── LLM 回复 ────────────────────
response.stop_reason = "tool_use"
response.content = [
  ToolUseBlock: name="todo", id="toolu_01VJ2MTeUxYKnNg8DYX1bQFF"
    input={"items": [
      {"id": "1", "text": "Add type hints to functions", "status": "pending"},
      {"id": "2", "text": "Add docstrings to functions", "status": "pending"},
      {"id": "3", "text": "Add a main guard (if __name__ == '__main__')", "status": "pending"}
    ]}
]

──────────────────── 执行工具 ────────────────────
执行: todo(items=[...3 项])
输出 (141 字符):
[ ] #1: Add type hints to functions
[ ] #2: Add docstrings to functions
[ ] #3: Add a main guard (if __name__ == '__main__')

(0/3 completed)
```

**解读：** 看到文件内容后，LLM 把用户的需求拆成了 3 个任务，全部标为 `pending`。

**对应代码：** `TodoManager.update()` 第 127-151 行。LLM 传入 items 列表 → 验证每个 item 的 text/status → 检查 in_progress 数量 → 存储 → 调用 `render()` 返回渲染结果。这次 in_progress_count = 0，通过校验。

**TODO 状态：**

```
[ ] #1: Add type hints to functions
[ ] #2: Add docstrings to functions
[ ] #3: Add a main guard (if __name__ == '__main__')
```

---

## 第 3 轮：LLM 犯错 -- 尝试同时标记 2 个 in_progress（最精彩的时刻）

**终端输出：**

```
──────────────────── 发送给 LLM (距上次 todo: 0 轮) ────────────────────
messages = [
  [0] user: "Refactor the file hello.py: add type hints, docstrings, and a main guard"
  [1] assistant/text: "Let me start by reading the existing file to understand what's there."
  [1] assistant/tool_use: read_file({"path": "/home/yzeng/Codes/learn-claude-code/hello.py"})
  [2] user/tool_result: "print("hello")"
  [3] assistant/tool_use: todo({"items": [{"id": "1", "text": "Add type hints to functions", "status": "pending)
  [4] user/tool_result: "[ ] #1: Add type hints to functions
[ ] #2: Add docstrings to functions
[ ] #3: ..."
]

→ 调用 client.messages.create(...)

──────────────────── LLM 回复 ────────────────────
response.stop_reason = "tool_use"
response.content = [
  TextBlock: "The file is minimal — just a bare `print`. I'll refactor it by wrapping the logic in a typed, documented function and ad..."
  ToolUseBlock: name="todo", id="toolu_01JhdXdZuFitwQBhgCVbn31f"
    input={"items": [
      {"id": "1", "text": "Add type hints to functions", "status": "in_progress"},
      {"id": "2", "text": "Add docstrings to functions", "status": "in_progress"},   ← 两个 in_progress！
      {"id": "3", "text": "Add a main guard (...)", "status": "pending"}
    ]}
]

──────────────────── 执行工具 ────────────────────
执行: todo(items=[...3 项])
输出 (49 字符):
Error: Only one task can be in_progress at a time
```

**这是本例最重要的教学时刻。** LLM 想同时标记 #1 和 #2 为 in_progress——它觉得"这两件事可以一起做"。但 TodoManager 有一条硬规则：

**对应代码：** `TodoManager.update()` 第 145-149 行

```python
if status == "in_progress":
    in_progress_count += 1
# ...
if in_progress_count > 1:
    raise ValueError("Only one task can be in_progress at a time")
```

`raise ValueError` 被 `agent_loop` 第 340-341 行的 `try/except` 捕获，变成 `"Error: Only one task can be in_progress at a time"` 返回给 LLM。

**关键点：LLM 不是通过"阅读文档"学到这条规则的——system prompt 里没有说"只能一个 in_progress"。它是通过尝试 → 被拒绝 → 看到错误信息来学习的。** 这和人类使用新 API 的方式完全一样：试一下，看报错，改正。

**TODO 状态没变（因为 update 失败了，不会修改 self.items）：**

```
[ ] #1: Add type hints to functions
[ ] #2: Add docstrings to functions
[ ] #3: Add a main guard (if __name__ == '__main__')
```

---

## 第 4 轮：LLM 纠正错误 -- 只标记 1 个 in_progress

**终端输出：**

```
──────────────────── 发送给 LLM (距上次 todo: 0 轮) ────────────────────
messages = [
  ...
  [5] assistant/text: "The file is minimal — just a bare `print`. I'll refactor it by wrapping the logi..."
  [5] assistant/tool_use: todo({"items": [{"id": "1", ... "status": "in_prog)
  [6] user/tool_result: "Error: Only one task can be in_progress at a time"
]

→ 调用 client.messages.create(...)

──────────────────── LLM 回复 ────────────────────
response.stop_reason = "tool_use"
response.content = [
  ToolUseBlock: name="todo", id="toolu_01KV74EGPgnzPtmjTfYbumsF"
    input={"items": [
      {"id": "1", "text": "Add type hints to functions", "status": "in_progress"},   ← 只有 1 个 in_progress
      {"id": "2", "text": "Add docstrings to functions", "status": "pending"},        ← 改回 pending
      {"id": "3", "text": "Add a main guard (...)", "status": "pending"}
    ]}
]

──────────────────── 执行工具 ────────────────────
执行: todo(items=[...3 项])
输出 (141 字符):
[>] #1: Add type hints to functions
[ ] #2: Add docstrings to functions
[ ] #3: Add a main guard (if __name__ == '__main__')

(0/3 completed)
```

**解读：** LLM 看到 `[6] user/tool_result: "Error: Only one task can be in_progress at a time"`，立即理解了规则，把 #2 改回 pending，只保留 #1 为 in_progress。一次纠正，没有第二次犯错。

**TODO 状态：**

```
[>] #1: Add type hints to functions
[ ] #2: Add docstrings to functions
[ ] #3: Add a main guard (if __name__ == '__main__')
```

---

## 第 5 轮：LLM 一次 write_file 完成所有 3 个任务

**终端输出：**

```
──────────────────── 发送给 LLM (距上次 todo: 0 轮) ────────────────────
messages = [
  ...
  [7] assistant/tool_use: todo({"items": [{"id": "1", ... "status": "in_prog)
  [8] user/tool_result: "[>] #1: Add type hints to functions
[ ] #2: Add docstrings to functions
[ ] #3: ..."
]

→ 调用 client.messages.create(...)

──────────────────── LLM 回复 ────────────────────
response.stop_reason = "tool_use"
response.content = [
  ToolUseBlock: name="write_file", id="toolu_01Poxu1r91tTiAn5gf9UYpxg"
    input={"path": "/home/yzeng/Codes/learn-claude-code/hello.py",
           "content": "def greet(name: str = \"World\") -> None:\n    \"\"\"Print a greeting message...\n"}
]

──────────────────── 执行工具 ────────────────────
执行: write_file({"path": "/home/yzeng/Codes/learn-claude-code/hello.py", "content": "def greet(name: str = \"World\") -> None:\n    \"\")
输出 (15 字符):
Wrote 308 bytes
```

**有趣的选择：LLM 用一次 write_file 就完成了全部 3 个任务。** 虽然 todo 里只标了 #1 (type hints) 为 in_progress，LLM 写的文件实际包含了：

- type hints: `name: str = "World"`, `-> None`
- docstrings: `"""Print a greeting message..."""`
- main guard: `if __name__ == "__main__":`

为什么一次写完？因为原文件只有 `print("hello")` 一行，整个重写比分三次编辑效率高得多。LLM 虽然按规则逐步标记 todo 状态，但执行层面选了最高效的方式。**规划的粒度和执行的粒度不必一致。**

和 [s02 例 1](s02_example1.md) 一样，LLM 选了 `write_file` 而不是 `edit_file`——对于几乎完全重写的场景，`write_file` 更合适。

---

## 第 6 轮：LLM 验证结果

**终端输出：**

```
──────────────────── 发送给 LLM (距上次 todo: 1 轮) ────────────────────
messages = [
  ...
  [9] assistant/tool_use: write_file({"path": "/home/.../hello.py", "content": "def greet(n)
  [10] user/tool_result: "Wrote 308 bytes"
]

→ 调用 client.messages.create(...)

──────────────────── LLM 回复 ────────────────────
response.stop_reason = "tool_use"
response.content = [
  TextBlock: "Now let's verify it runs correctly:"
  ToolUseBlock: name="bash", id="toolu_01WcPkHP3GxUBVW21Urc4FfZ"
    input={"command": "cd /home/yzeng/Codes/learn-claude-code && python hello.py"}
]

──────────────────── 执行工具 ────────────────────
执行: bash({"command": "cd /home/yzeng/Codes/learn-claude-code && python hello.py"})
输出 (13 字符):
Hello, World!
```

**解读：** LLM 写完文件后没有立即标完成——而是先运行验证。只有确认 `python hello.py` 输出了 `Hello, World!` 才算真正完成。这是好的 Agent 行为：**写完代码要验证。**

注意此时 `距上次 todo: 1 轮` → `距上次 todo: 2 轮`，计数器在涨，但还没到 3 轮的 nag 触发阈值。

---

## 第 7 轮：LLM 一次性标记全部完成

**终端输出：**

```
──────────────────── 发送给 LLM (距上次 todo: 2 轮) ────────────────────
messages = [
  ...
  [11] assistant/text: "Now let's verify it runs correctly:"
  [11] assistant/tool_use: bash({"command": "cd /home/yzeng/Codes/learn-claude-code && python hello.py"})
  [12] user/tool_result: "Hello, World!"
]

→ 调用 client.messages.create(...)

──────────────────── LLM 回复 ────────────────────
response.stop_reason = "tool_use"
response.content = [
  ToolUseBlock: name="todo", id="toolu_01Li1S3MLWZ9m5JY5HLTgatu"
    input={"items": [
      {"id": "1", "text": "Add type hints to functions", "status": "completed"},
      {"id": "2", "text": "Add docstrings to functions", "status": "completed"},
      {"id": "3", "text": "Add a main guard (...)", "status": "completed"}
    ]}
]

──────────────────── 执行工具 ────────────────────
执行: todo(items=[...3 项])
输出 (141 字符):
[x] #1: Add type hints to functions
[x] #2: Add docstrings to functions
[x] #3: Add a main guard (if __name__ == '__main__')

(3/3 completed)
```

LLM 跳过了中间状态（没有逐个标 in_progress → completed），直接把 3 个任务全部设为 completed。为什么这样做？因为它已经在第 5 轮用一次 write_file 把 3 件事全做了，而且第 6 轮验证通过了。逐个更新状态是多余的。

**TODO 状态：**

```
[x] #1: Add type hints to functions
[x] #2: Add docstrings to functions
[x] #3: Add a main guard (if __name__ == '__main__')

(3/3 completed)
```

---

## 追踪分析：LLM 如何知道任务状态

这是理解 Agent 状态管理的关键问题。第 7 轮时，LLM 把全部 3 个任务标为 completed。**它怎么知道这 3 件事都做完了？**

LLM 没有独立的"记忆"——它的全部信息来源就是 messages 数组。让我们站在 LLM 的视角，看看第 7 轮时它能看到什么：

```
messages = [
  [0]  user:          "Refactor the file hello.py: add type hints, docstrings, and a main guard"
  [1]  assistant:     read_file("hello.py")
  [2]  user:          "print("hello")"
  [3]  assistant:     todo([3 items, all pending])
  [4]  user:          "[ ] #1: Add type hints\n[ ] #2: Add docstrings\n[ ] #3: Add main guard"
  [5]  assistant:     todo([#1 in_progress, #2 in_progress])       ← 尝试 2 个 in_progress
  [6]  user:          "Error: Only one task can be in_progress at a time"
  [7]  assistant:     todo([#1 in_progress, #2 pending, #3 pending])
  [8]  user:          "[>] #1: Add type hints\n[ ] #2: ...\n[ ] #3: ..."
  [9]  assistant:     write_file("hello.py", "def greet(name: str = \"World\") -> None:...")
  [10] user:          "Wrote 308 bytes"
  [11] assistant:     bash("python hello.py")
  [12] user:          "Hello, World!"
]
```

LLM 的推理链路是这样的：

**第 1 步：回忆任务列表。** 从 [4] 看到 3 个任务：type hints、docstrings、main guard。

**第 2 步：回忆做了什么。** 从 [9] 看到自己写了一个包含 `name: str = "World"` 和 `-> None`（type hints）、`""" ... """`（docstrings）的文件。文件内容是自己生成的，它知道里面有 main guard。

**第 3 步：确认结果。** 从 [12] 看到 `"Hello, World!"`——文件能正确运行。

**结论：** 一次 write_file 包含了全部 3 个功能 + 运行验证通过 → 3 个任务都完成了。

这里有个微妙之处：**LLM 不需要 TodoManager 告诉它哪些任务完成了。** TodoManager 的状态（[8] 中的 `[>] #1`）还停在"#1 正在做"，#2 和 #3 还是 pending。但 LLM 自己知道它在 write_file 里同时实现了全部功能。todo 工具只是 LLM 的"白板"，不是它的"大脑"——真正的状态判断是 LLM 根据 messages 历史做的推理。

### 深入理解：TodoManager 是"白板"，不是"指挥官"

回看实际发生的事情：

```
TodoManager 的状态：  [>] #1: type hints    [ ] #2: docstrings    [ ] #3: main guard
LLM 的实际行为：      write_file 一次性写入了包含全部 3 个功能的完整文件
```

TodoManager 说"你在做 #1"，但 LLM 做了 #1+#2+#3。没有任何代码阻止这件事。为什么？因为架构里有**两种约束**，级别完全不同：

| 约束类型 | 实现方式 | 能否被 LLM 绕过 | 例子 |
|---|---|---|---|
| **硬约束** | Python 代码 `raise ValueError` | 不能。代码直接拒绝，返回错误 | "Only one task can be in_progress" |
| **软约束** | System prompt 里的文字指令 | **能。LLM 可以选择不遵守** | "Mark in_progress before starting" |

"只能有 1 个 in_progress" 是硬约束——LLM 试了 2 个，被代码拒绝了，必须改（见第 3 轮）。

"先标 in_progress 再开始做" 是软约束——system prompt 里写了，但 LLM 可以无视。这次它看到 `hello.py` 只有一行 `print("hello")`，觉得太简单了，没必要分 3 步改，一次写完更高效。

**LLM 做决策的依据不是 TodoManager 的状态，而是 messages 里的全部历史。** 它是一个自主推理的模型，todo 只是它可以读写的一个工具。就像你给一个人一块白板，他可以在上面写计划，但他干活的时候不需要每一步都看白板——他自己知道该干什么。

这其实是**好事**。如果 LLM 严格按照 todo 一步步做（先只加 type hints，提交，再只加 docstrings，提交...），对于这个 14 字符的文件来说反而是浪费。LLM 的灵活判断让它选择了更高效的方式。

TodoManager 的真正价值不在于控制 LLM 的行为，而在于：
1. **帮 LLM 在长对话中不忘事**——messages 被工具输出淹没时，todo 提供了一个清晰的进度摘要
2. **帮人类观察进度**——你在终端能看到 `[x] [x] [x]` 的状态变化，知道 Agent 做到哪了

---

## 第 8 轮：最终回答

**终端输出：**

```
──────────────────── 发送给 LLM (距上次 todo: 0 轮) ────────────────────
messages = [
  ...
  [13] assistant/tool_use: todo({"items": [...all completed])
  [14] user/tool_result: "[x] #1: ...\n[x] #2: ...\n[x] #3: ..."
]

→ 调用 client.messages.create(...)

──────────────────── LLM 回复 ────────────────────
response.stop_reason = "end_turn"
response.content = [
  TextBlock: "All three tasks are done. Here's a summary of every change made to `hello.py`:

| What | Before | After |
|---|---|---|
..."
]

──────────────────── 循环结束 ────────────────────
stop_reason = "end_turn" → return!
```

`stop_reason = "end_turn"` → 和 [s01 例 1](s01_example1.md) 一样，不是 `"tool_use"` 就 return，循环结束。

---

## 最终回答

```
All three tasks are done. Here's a summary of every change made to `hello.py`:

| What | Before | After |
|---|---|---|
| **Structure** | Bare `print` at module level | Logic wrapped in `greet()` + `main()` functions |
| **Type hints** | None | `greet(name: str = "World") -> None` and `main() -> None` |
| **Docstrings** | None | Google-style docstrings on both functions (with `Args:` section on `greet`) |
| **Main guard** | None | `if __name__ == "__main__": main()` prevents execution on import |

The main guard is especially important — without it, `print` would fire whenever
another module did `import hello`, which is rarely desirable.
```

---

## TODO 状态完整演变

```
第 2 轮：创建列表
[ ] #1: Add type hints to functions
[ ] #2: Add docstrings to functions
[ ] #3: Add a main guard (if __name__ == '__main__')

第 3 轮：尝试 2 个 in_progress → ERROR

第 4 轮：纠正为 1 个 in_progress
[>] #1: Add type hints to functions
[ ] #2: Add docstrings to functions
[ ] #3: Add a main guard (if __name__ == '__main__')

第 5 轮：write_file（实际完成了全部 3 个任务，但 TODO 状态没变）
第 6 轮：bash 验证（TODO 状态仍没变）

第 7 轮：一次性标记全部完成
[x] #1: Add type hints to functions
[x] #2: Add docstrings to functions
[x] #3: Add a main guard (if __name__ == '__main__')
```

从这个演变可以看到：**TODO 状态和实际进度之间有延迟。** 第 5 轮 write_file 时 3 件事实际上都做完了，但 TODO 状态直到第 7 轮才更新。这是因为 TODO 是 LLM 主动维护的，不是自动的——LLM 选择了先验证再更新状态。

如果 LLM 在第 5、6 轮继续不更新 todo，到第 7 轮（距上次 todo 达到 3 轮）就会触发 nag reminder。但这次 LLM 在第 7 轮（距上次 todo: 2 轮）就自觉更新了，nag 没有被触发。

---

## 总结

```
messages 增长过程（15 条）：

 [0]  user:      "Refactor the file hello.py: ..."
 [1]  assistant: read_file("hello.py")                          第 1 轮
 [2]  user:      "print("hello")"
 [3]  assistant: todo([3 pending])                              第 2 轮
 [4]  user:      "[ ] [ ] [ ]"
 [5]  assistant: todo([2 in_progress, 1 pending])               第 3 轮 ← 犯错
 [6]  user:      "Error: Only one task can be in_progress"
 [7]  assistant: todo([1 in_progress, 2 pending])               第 4 轮 ← 纠正
 [8]  user:      "[>] [ ] [ ]"
 [9]  assistant: write_file("hello.py", "def greet...")         第 5 轮 ← 一次完成 3 件事
[10]  user:      "Wrote 308 bytes"
[11]  assistant: bash("python hello.py")                        第 6 轮 ← 验证
[12]  user:      "Hello, World!"
[13]  assistant: todo([3 completed])                            第 7 轮 ← 更新状态
[14]  user:      "[x] [x] [x]"
 →    assistant: "All three tasks are done. ..."                第 8 轮 ← end_turn
```

**8 轮 LLM 调用，其中 1 轮因为错误而"浪费"。** 但这个"浪费"不是坏事——LLM 通过它学会了 TodoManager 的规则。整个过程展示了 Agent 的 3 个核心行为：

1. **从错误中学习：** LLM 不需要预先知道所有规则，tool_result 中的报错就是最好的"文档"
2. **规划与执行分离：** todo 规划了 3 步，实际执行只用了 1 次 write_file
3. **自主验证：** 写完代码先 `python hello.py`，确认能跑才标完成
