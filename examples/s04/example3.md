# s04 实际运行追踪：子 Agent 创建模块 + 父 Agent 验证（共享文件系统）

> prompt: `Use a task to create a new module, then verify it from here`
>
> 结果：父 Agent 3 轮，子 Agent 2 轮（共 5 次 LLM 调用）。子 Agent 创建了 `greetings.py`，父 Agent 用 `read_file` + `bash` 验证文件确实存在且可用。
>
> **重点观察：** 子 Agent 写的文件，父 Agent 能读到——因为它们共享文件系统。这是"共享什么、不共享什么"的最佳演示：messages 隔离，文件系统共享。

---

## 用户输入

**终端输出：**

```
s04 >> Use a task to create a new module, then verify it from here

────────────────── 用户输入 ──────────────────
query = "Use a task to create a new module, then verify it from here"
```

这个 prompt 巧妙地包含了**两步**：
1. 用子 Agent **创建**一个模块
2. 在父 Agent 里**验证**它存在

"then verify it from here"——"from here"隐含的意思是"在父 Agent 的上下文中"。这迫使父 Agent 在子 Agent 完成后自己去检查文件，从而证明文件系统是共享的。

---

## 父 Agent 第 1 轮：派发创建任务

**终端输出：**

```
────────────────── 父 Agent 轮次 1 ──────────────────
messages = [
  [0] user: "Use a task to create a new module, then verify it from here"
]

→ 调用 client.messages.create(...)

────────────────── 父 Agent 轮次 1: 回复 ──────────────────
response.stop_reason = "tool_use"
response.content = [
  TextBlock: "I'll use a task to create a new module, then verify it from the main context."
  ToolUseBlock: name="task", id="toolu_01NiHDh6dDa1rUzuEck7nPrp"
    input={"description": "Create a new Python module", "prompt": "Create a new Python module at /home/yzeng/Codes/learn-claude-code/greetings.py with the following:\n1. A function `greet(name)` that returns \"...
]
```

**解读：** 注意父 Agent 做了一个聪明的决策：

1. 它先输出了一段 TextBlock（`"I'll use a task to create a new module, then verify it from the main context."`）——说明它理解了任务的两个步骤
2. 但它只发出了 **一个** `task` 工具调用——先创建，后面再验证

它没有同时发出 `task` + `read_file`，因为 `read_file` 依赖于 `task` 完成后文件才存在。**LLM 理解工具之间的依赖关系。**

另外看 `prompt` 的内容：父 Agent 自己编写了一个详细的模块规格——要有 `greet(name)` 函数、`farewell(name)` 函数、`__all__` 等。这些细节**不是用户说的**（用户只说了 "create a new module"），而是父 Agent 自己补充的。LLM 有创造力。

---

## 子 Agent 第 1 轮：直接写文件

**终端输出：**

```
  │ ────────────────── 子 Agent 启动 ──────────────────
  │ prompt: "Create a new Python module at /home/yzeng/Codes/learn-claude-code/greetings.py with the following:
  1. A function `greet("
  │ tools: ["bash", "read_file", "write_file", "edit_file"]  (没有 task！)

  │ ────────────────── 子 Agent 轮次 1 ──────────────────
  │ messages = [
  │   [0] user: "Create a new Python module at /home/yzeng/Codes/learn-claude-code/greetings.py w..."
  │ ]
  │ → 调用 client.messages.create(...)

  │ ────────────────── 子 Agent 轮次 1: 回复 ──────────────────
  │ response.stop_reason = "tool_use"
  │ response.content = [
  │   TextBlock: "I have all the information needed to create the file. Let me write it now!"
  │   ToolUseBlock: name="write_file", id="toolu_01LMgNRYJ8vRge2vd3CjqLcz"
  │     input={"path": "/home/yzeng/Codes/learn-claude-code/greetings.py", "content": "\"\"\"A simple greetings module providing greeting and farewell functions.\"\"\"\n\n__all__ = [\"greet\", \"farewell\"]\n\n\nde...
  │ ]

  │ ────────────────── 子 Agent 轮次 1: 执行工具 ──────────────────
  │ 执行: write_file({"path": "/home/yzeng/Codes/learn-claude-code/greetings.py", "content": "..."})
  │ 输出 (15 字符): Wrote 321 bytes
```

**解读：** 子 Agent 不需要先读什么——prompt 里已经有了完整规格，直接 `write_file` 创建文件。

关键时刻：**`Wrote 321 bytes`——文件已经写入磁盘。** 父 Agent 和子 Agent 共享文件系统，所以子 Agent 写的文件父 Agent 能看到。

这和进程模型无关——即使子 Agent 是一个独立的 subprocess，只要它在同一台机器上、写入同一个目录，父 Agent 一样能读到。文件系统的共享是操作系统层面的事，不取决于 Python 的调用方式。当前 s04 里 `run_subagent()` 恰好是同一个进程内的函数调用，但这不是文件系统共享的原因。

**真正想隔离文件系统，需要更重的手段：** Docker 容器、chroot、或者 git worktree（各自在不同的目录下工作）。s12 的 worktree isolation 就是这个思路——给每个子 Agent 一个独立的工作目录副本，避免多个 Agent 同时改同一个文件产生冲突。

**对应代码：** `s04_subagent.py` 第 135-140 行 `run_write()` 函数。无论是父还是子调用它，`WORKDIR` 都是一样的。

---

## 子 Agent 第 2 轮：确认完成 + 返回摘要

**终端输出：**

```
  │ ────────────────── 子 Agent 轮次 2 ──────────────────
  │ messages = [
  │   [0] user: "Create a new Python module at ..."
  │   [1] assistant/text: "I have all the information needed to create the file. Let me write it now!"
  │   [1] assistant/tool_use: write_file(...)
  │   [2] user/tool_result: "Wrote 321 bytes"
  │ ]
  │ → 调用 client.messages.create(...)

  │ ────────────────── 子 Agent 轮次 2: 回复 ──────────────────
  │ response.stop_reason = "end_turn"
  │ response.content = [
  │   TextBlock: "The file has been created at `/home/yzeng/Codes/learn-claude-code/greetings.py`. Here's a summary of what was added:
  │
  │   - ..."
  │ ]

  │ ────────────────── 子 Agent 结束 ──────────────────
  │ 共 2 轮，子 Agent messages 有 4 条 → 全部丢弃
  │ 只返回摘要 (534 字符):
  │ The file has been created at `/home/yzeng/Codes/learn-claude-code/greetings.py`. Here's a summary of what was added:
  │
  │ - **Module docstring** — A brief description at the top of the file.
  │ - **`__all__`** — A list exporting `"greet"` and `"farewell"`, controlling what's available on `from greetings im...
──────────────────────────────────────────────────
子任务完成，摘要返回给父 Agent (534 字符)
```

**解读：** 子 Agent 只用了 2 轮就完成了任务——因为创建文件本身就很简单。`end_turn` 后返回 534 字符的摘要，包含文件路径和内容说明。

**为什么是 4 条消息？** 逐条数：

| 索引 | role | 内容 | 产生时机 |
|---|---|---|---|
| [0] | user | prompt | 初始化 |
| [1] | assistant | text + write_file | 第 1 轮 LLM 回复 |
| [2] | user | tool_result: "Wrote 321 bytes" | 第 1 轮工具执行 |
| [3] | assistant | text: 摘要（end_turn） | 第 2 轮 LLM 回复 |

第 2 轮 `stop_reason = "end_turn"` → 代码先 append assistant 回复，然后 `break` 跳出循环 → 没有执行工具，也就没有 tool_result → 所以是 4 条不是 5 条。

规律：`1（prompt）+（N-1）× 2（完整轮次，每轮 assistant + tool_result）+ 1（最后一轮只有 assistant）= 2N`。example1 跑了 3 轮 = 6 条，这里跑了 2 轮 = 4 条。

此时的状态：
- **磁盘上**：`greetings.py` 已经存在（321 字节）
- **子 Agent 的 sub_messages**：4 条消息 → **已被 Python 垃圾回收**
- **父 Agent 的 messages**：即将收到 534 字符的 `tool_result`

---

## 父 Agent 第 2 轮：验证文件（核心观察点）

**终端输出：**

```
────────────────── 父 Agent 轮次 2 ──────────────────
messages = [
  [0] user: "Use a task to create a new module, then verify it from here"
  [1] assistant/text: "I'll use a task to create a new module, then verify it from the main context."
  [1] assistant/tool_use: task({"description": "Create a new Python module", "prompt": "Create a new Python mod)
  [2] user/tool_result: "The file has been created at `/home/yzeng/Codes/learn-claude-code/greetings.py`...."
]

→ 调用 client.messages.create(...)

────────────────── 父 Agent 轮次 2: 回复 ──────────────────
response.stop_reason = "tool_use"
response.content = [
  TextBlock: "The task is done. Now let me verify the file from here:"
  ToolUseBlock: name="read_file", id="toolu_01KSDnhXgX7N9jnHXQX2xEfk"
    input={"path": "/home/yzeng/Codes/learn-claude-code/greetings.py"}
  ToolUseBlock: name="bash", id="toolu_012r7nr1V19BynQc8VuDavPV"
    input={"command": "cd /home/yzeng/Codes/learn-claude-code && python -c \"\nfrom greetings import greet, farewell, __all__\nprint('__all__:', __all__)\nprint(greet('World'))\nprint(farewell('World'))\n\""}
]
```

**解读：** 这是本例最精彩的一轮。父 Agent 做了两件事来验证子 Agent 的工作：

**验证 1：`read_file` 读文件内容**

```
执行: read_file({"path": "/home/yzeng/Codes/learn-claude-code/greetings.py"})
输出 (320 字符): """A simple greetings module providing greeting and farewell functions."""

__all__ = ["greet", "farewell"]


def greet(name):
    """Return a greeting message for the given name."""
    return f"Hell
```

**成功了！** 父 Agent 用 `read_file` 读到了子 Agent 创建的文件。文件内容完整——有 docstring、`__all__`、`greet` 函数。

**验证 2：`bash` 运行 Python 代码测试**

```
执行: bash({"command": "cd ... && python -c \"from greetings import greet, farewell, __all__\n..."})
输出 (60 字符): __all__: ['greet', 'farewell']
Hello, World!
Goodbye, World!
```

**也成功了！** 父 Agent 不仅读了文件，还用 `python -c` 实际导入并运行了模块。`greet("World")` 返回 `"Hello, World!"`，`farewell("World")` 返回 `"Goodbye, World!"`——功能完全正确。

**这证明了"共享文件系统"：** 子 Agent 写的文件 → 磁盘上 → 父 Agent 能读到。messages 是隔离的，但文件系统不是。

**并行验证：** 注意父 Agent 同时发出了 `read_file` 和 `bash` 两个工具调用——它知道两者互不依赖，可以并行执行。这和 s02/s03 里看到的并行工具调用是同一个模式。

---

## 父 Agent 第 3 轮：综合报告

**终端输出：**

```
────────────────── 父 Agent 轮次 3 ──────────────────
messages = [
  [0] user: "Use a task to create a new module, then verify it from here"
  [1] assistant/text: "I'll use a task to create a new module, then verify it from the main context."
  [1] assistant/tool_use: task(...)
  [2] user/tool_result: "The file has been created at ..."
  [3] assistant/text: "The task is done. Now let me verify the file from here:"
  [3] assistant/tool_use: read_file(...)
  [3] assistant/tool_use: bash(...)
  [4] user/tool_result: "\"\"\"A simple greetings module ..."
  [4] user/tool_result: "__all__: ['greet', 'farewell']\nHello, World!\nGoodbye, World!"
]

→ 调用 client.messages.create(...)

────────────────── 父 Agent 轮次 3: 回复 ──────────────────
response.stop_reason = "end_turn"
response.content = [
  TextBlock: "Everything checks out! Here's a summary of what was created and verified: ..."
]

────────────────── 父 Agent 轮次 3: 循环结束 ──────────────────
stop_reason = "end_turn" → return!
```

**解读：** 父 Agent 的 messages 共 5 条——结构非常清晰：

| 索引 | 内容 | 来源 |
|---|---|---|
| [0] | 用户请求 | 用户 |
| [1] | task 工具调用 | 父 Agent |
| [2] | 子 Agent 摘要（534 字符） | 子 Agent → tool_result |
| [3] | read_file + bash 验证 | 父 Agent |
| [4] | 文件内容 + 运行结果 | 工具 → tool_result |

子 Agent 内部的 4 条 messages、`write_file` 操作细节——父 Agent 完全不知道。它只知道"文件被创建了"（来自摘要）和"文件确实存在且能用"（来自自己的验证）。

---

## 最终回答

**终端输出：**

```
────────────────── 最终回答 ──────────────────
Everything checks out! Here's a summary of what was created and verified:

### `greetings.py` — Module Contents
| Element | Details |
|---|---|
| **Module docstring** | Brief description of the module |
| `__all__` | `["greet", "farewell"]` — controls public API |
| `greet(name)` | Returns `"Hello, {name}!"` |
| `farewell(name)` | Returns `"Goodbye, {name}!"` |

### Verification Results
- File was successfully created by the sub-task
- Both functions import correctly
- `greet("World")` → `Hello, World!`
- `farewell("World")` → `Goodbye, World!`
- `__all__` is correctly defined
```

**解读：** 一个完整的"委托 → 验证"循环。父 Agent 给出了结构化的报告，包含模块内容和验证结果。

---

## 全局流程图

```
用户: "create a module, then verify"
         │
         ▼
父 Agent 轮次 1: task(prompt="Create greetings.py...")
         │
         ├──▶ 子 Agent 轮次 1: write_file("greetings.py", ...)  →  磁盘
         │    子 Agent 轮次 2: end_turn → 摘要 (534 字符)
         │    sub_messages (4条) → 丢弃
         │
         │◀── tool_result: "The file has been created..."
         ▼
父 Agent 轮次 2: read_file("greetings.py") + bash("python -c ...")
         │                    ↑
         │            从磁盘读取子 Agent 写的文件
         ▼
父 Agent 轮次 3: end_turn → 最终报告
```

---

## 父子共享和隔离的实证

| 维度 | 本例中的证据 | 共享？ |
|---|---|---|
| **文件系统** | 子 Agent 写 `greetings.py`，父 Agent 用 `read_file` 读到了 | 共享 |
| **工具函数** | 父子都调用同一个 `run_write()` / `run_read()` | 共享 |
| **messages** | 子 Agent 有 4 条 messages，父 Agent 一条都看不到 | 不共享 |
| **system prompt** | 子 Agent 用 `SUBAGENT_SYSTEM`，父 Agent 用 `SYSTEM` | 不共享 |
| **工具列表** | 子 Agent 没有 `task`，父 Agent 有 | 不共享 |

---

## 这个例子的关键收获

1. **文件系统是父子之间唯一的"副作用通道"。** 子 Agent 的 `write_file` 操作改变了磁盘状态，父 Agent 能观察到这个变化。这不是通过 messages 传递的——是通过共享的操作系统文件系统。

2. **父 Agent 不盲目信任子 Agent 的摘要。** 子 Agent 说"文件已创建"，但父 Agent 还是自己去 `read_file` + `bash` 验证了一遍。这是一种"信任但验证"的模式——在生产环境中非常重要。

3. **"先委托后验证"是一个常见的 Agent 工作模式。** 父 Agent 把"创建"工作外包给子 Agent（避免污染自己的上下文），但把"验证"工作留给自己（因为验证结果需要在后续对话中使用）。

4. **子 Agent 只需 2 轮就完成了。** 创建文件是一个简单任务，不需要复杂的多轮探索。这说明子 Agent 的开销与任务复杂度成正比——简单任务不会浪费太多 API 调用。

5. **父 Agent 理解工具依赖。** 它没有在第 1 轮就同时发出 `task` + `read_file`——因为文件还不存在。它等 `task` 完成后，才在第 2 轮发出验证工具调用。LLM 具备这种因果推理能力。
