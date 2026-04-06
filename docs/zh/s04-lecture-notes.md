# s04: Subagent —— 用子 Agent 隔离上下文

> **前置知识：** 请先完成 [s01](s01-lecture-notes.md)、[s02](s02-lecture-notes.md)、[s03](s03-lecture-notes.md)。本讲义不重复已讲过的概念，只聚焦 s04 的新内容。

---

## 这一课要回答的问题

> s03 例 3 里，LLM 读了 94,000 字符的源码全塞进 messages，直接崩了。有没有办法让 LLM 去做"脏活"（读大量文件、搜索代码），但不污染主对话？

**答案：派一个子 Agent 去做。子 Agent 有自己的 messages，做完后只返回一句话总结。**

---

## 核心类比：你和蒙眼专家（升级版）

回顾 s01 的类比：你是循环，蒙眼专家是 LLM。

现在专家遇到一个复杂子问题——"这个项目用什么测试框架？"——要读好几个文件才能搞清楚。如果专家自己去查，他的笔记本（messages）会被大量文件内容塞满，影响后续工作。

所以专家说：**"帮我找个助手来查这个，查完告诉我结论就行。"**

- 助手拿一张**空白纸**（`messages=[]`）开始工作
- 助手读了 5 个文件，做了各种笔记（助手的 messages 增长）
- 助手最后说："项目用的是 pytest。"
- 你把这一句话告诉专家（`tool_result: "pytest"`）
- **助手的笔记本直接扔掉**——专家的笔记本保持干净

---

## s03 → s04：到底变了什么？

| 组件 | s03 | s04 | 变了吗？ |
|---|---|---|---|
| `while True` 循环结构 | 有 | 一样 | 不变 |
| 工具（父 Agent） | 5 个 | 5 个（bash/read/write/edit + **task** 替代 todo） | **变了** |
| 工具（子 Agent） | 不适用 | 4 个（bash/read/write/edit，**没有 task**） | **新增** |
| TodoManager | 有 | **去掉了**（s04 聚焦于上下文隔离，不含 todo） | 去掉 |
| Subagent | 无 | **`run_subagent()` 函数** | **新增** |
| System prompt | 1 套 | **2 套**（父 Agent 用一套，子 Agent 用另一套） | **变了** |

---

## 概念 1：两套工具集——防止递归套娃

```python
CHILD_TOOLS  = [bash, read_file, write_file, edit_file]         # 4 个
PARENT_TOOLS = [bash, read_file, write_file, edit_file, task]   # 5 个（多了 task）
```

为什么子 Agent 没有 `task` 工具？

如果子 Agent 也能用 `task` 生成子 Agent，就会形成无限嵌套：

```
父 Agent → 生子 Agent → 子再生孙 Agent → 孙再生曾孙 → ...（无限递归）
```

这是一个**硬约束**：子 Agent 的工具定义列表里根本没有 `task`，LLM 看不到它，自然不会调用。不是靠 prompt 说"你不能生子 Agent"（那是软约束，LLM 可能无视），而是工具列表里直接没有这个选项。

对比 s03 的"Only one in_progress"——那也是硬约束，代码层面 `raise ValueError`。这里更彻底：工具都不给你看。

---

## 概念 2：`run_subagent()` —— 独立上下文的子循环

```python
def run_subagent(prompt: str) -> str:
    sub_messages = [{"role": "user", "content": prompt}]   # ← 从零开始！
    for _ in range(30):                                     # ← 安全上限
        response = client.messages.create(
            model=MODEL, system=SUBAGENT_SYSTEM,            # ← 不同的 system prompt
            messages=sub_messages,                          # ← 独立的 messages
            tools=CHILD_TOOLS,                              # ← 没有 task
            max_tokens=8000,
        )
        sub_messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            break
        # ... 执行工具，收集结果，塞回 sub_messages ...
    # 只返回最终文本，sub_messages 直接丢弃
    return "".join(b.text for b in response.content if hasattr(b, "text"))
```

这个函数的结构和 s01 的 `agent_loop` 几乎一样——都是循环 + 调 LLM + 执行工具 + 塞回结果。但有 **3 个关键区别**：

### 区别 1：messages 从零开始

```python
sub_messages = [{"role": "user", "content": prompt}]
```

子 Agent 看不到父 Agent 之前的任何对话。它只知道一件事：你给它的 `prompt`。

**这就是"上下文隔离"的意思。** 父 Agent 的 messages 可能有 20 条消息、几万字符，但子 Agent 从一张白纸开始。

### 区别 2：只返回摘要，子 messages 丢弃

```python
return "".join(b.text for b in response.content if hasattr(b, "text"))
```

子 Agent 可能跑了 10 轮工具调用，`sub_messages` 里积累了 20 条消息。但函数只提取最后一个 response 里的 TextBlock 文本——一段摘要。

`sub_messages` 是一个局部变量，函数返回后就被 Python 垃圾回收了。**子 Agent 的完整对话历史不会进入父 Agent 的 messages。**

父 Agent 收到的只是一个普通的 `tool_result`：

```python
# 父 Agent 的 messages：
{"type": "tool_result", "tool_use_id": "toolu_xxx", "content": "项目用的是 pytest。"}
```

对比如果没有子 Agent（像 s03 例 3 那样直接在父 Agent 里读所有文件）：

| 方式 | 父 Agent messages 增加了什么 | 大小 |
|---|---|---|
| 不用子 Agent（s03 例 3） | 5 个文件的完整内容 + 5 个 tool_result | 94,000+ 字符 |
| 用子 Agent（s04） | 一句话摘要 | ~100 字符 |

### 区别 3：安全上限 `for _ in range(30)`

```python
for _ in range(30):  # safety limit
```

s01-s03 的 `agent_loop` 用 `while True`——理论上可以无限循环（虽然 LLM 最终会 `end_turn`）。子 Agent 加了一个硬上限：最多 30 轮。为什么？

因为子 Agent 是自动化的，没有人类监督。如果子 Agent 陷入某种循环（比如反复尝试一个失败的命令），30 轮后会强制停止，不会无限消耗 API 额度。

---

## 概念 3：父子共享什么、不共享什么

| 维度 | 共享吗？ | 说明 |
|---|---|---|
| **文件系统** | 共享 | 子 Agent 写的文件，父 Agent 能看到。反过来也一样 |
| **API client / MODEL** | 共享 | 用同一个 API key，同一个模型 |
| **工具函数** | 共享 | `TOOL_HANDLERS` 是同一个字典 |
| **messages 列表** | **不共享** | 父有自己的 `history`，子有自己的 `sub_messages` |
| **system prompt** | **不共享** | 父用 `SYSTEM`，子用 `SUBAGENT_SYSTEM` |
| **工具定义列表** | **不共享** | 父用 `PARENT_TOOLS`（有 task），子用 `CHILD_TOOLS`（没有 task） |

**共享文件系统**是一个重要细节。如果你让子 Agent "创建一个新模块 helper.py"，它写的文件真的出现在磁盘上。父 Agent 之后可以用 `read_file` 验证这个文件确实存在。

---

## 一个父 Agent 可以调用多个子 Agent 吗？

可以。看父 Agent 循环里的这段代码：

```python
for block in response.content:        # ← 遍历 LLM 返回的所有 block
    if block.type == "tool_use":
        if block.name == "task":
            output = run_subagent(block.input["prompt"])   # 第 1 个 task → 子 Agent A
            # ...
        if block.name == "task":
            output = run_subagent(block.input["prompt"])   # 第 2 个 task → 子 Agent B
```

LLM 一次回复里可以返回多个 `tool_use` block，其中可以有多个 `task`。`for` 循环逐个处理，每遇到一个 `task` 就调一次 `run_subagent()`。

这些子 Agent 之间的关系：

| 维度 | 关系 |
|---|---|
| **执行顺序** | **串行**。`for` 循环是顺序执行的——A 跑完、返回摘要之后，B 才启动 |
| **messages** | **完全隔离**。A 和 B 各自从空白 `sub_messages` 开始，互相看不到对方的对话 |
| **文件系统** | **共享**。A 写了一个文件，B 能读到——因为它们操作的是同一个磁盘 |
| **协调者** | **父 Agent**。父 Agent 收到 A 和 B 的摘要后，可以综合判断下一步做什么 |

换句话说，多个子 Agent 是**兄弟关系**，不是父子关系。它们之间没有直接通信——唯一的"间接通信"是文件系统的副作用（A 写的文件 B 能读到）。

---

## 父 Agent 循环里的工具派发

父 Agent 的循环里，`task` 工具需要特殊处理——不走 `TOOL_HANDLERS`，而是调 `run_subagent()`：

```python
for block in response.content:
    if block.type == "tool_use":
        if block.name == "task":
            # task 工具 → 启动子 Agent
            output = run_subagent(block.input["prompt"])
        else:
            # 普通工具 → 查派发表
            handler = TOOL_HANDLERS.get(block.name)
            output = handler(**block.input)
        results.append({"type": "tool_result", ..., "content": output})
```

从父 Agent 的角度看，`task` 和 `bash`、`read_file` 一样——都是调用一个工具，等返回结果。它不知道也不关心子 Agent 内部跑了几轮。

---

## verbose 输出里看什么

s04 的 verbose 打印有缩进来区分父子：

```
──────────────── 父 Agent 轮次 1 ────────────────      ← 没有缩进 = 父 Agent
...
  │ ──────────── 子 Agent 启动 ──────────────────      ← 有缩进 "│" = 子 Agent
  │ prompt: "Find what testing framework..."
  │ tools: ["bash", "read_file", "write_file", "edit_file"]  (没有 task！)
  │
  │ ──────────── 子 Agent 轮次 1 ────────────────
  │ messages = [
  │   [0] user: "Find what testing framework..."       ← 从零开始的 messages
  │ ]
  │ ...
  │ ──────────── 子 Agent 结束 ──────────────────
  │ 共 3 轮，子 Agent messages 有 7 条 → 全部丢弃
  │ 只返回摘要 (42 字符): "The project uses pytest."
──────────────────────────────────────────────────

子任务完成，摘要返回给父 Agent (42 字符)           ← 回到父 Agent
```

关键看这几点：

| 看什么 | 在哪里 | 说明 |
|---|---|---|
| 子 Agent 的 messages 从 `[0]` 开始 | 子 Agent 轮次 1 | 确认上下文是干净的 |
| 子 Agent 内部的工具调用 | 子 Agent 各轮次 | 看它为了回答问题做了什么 |
| "共 N 轮，messages 有 M 条 → 全部丢弃" | 子 Agent 结束 | 确认历史没有泄漏到父 |
| "只返回摘要 (N 字符)" | 子 Agent 结束 | 对比 M 条 messages vs N 字符摘要 |

---

## 和 s03 例 3 的对比：子 Agent 如何避免崩溃

回忆 s03 例 3："Review all Python files" → 94,000 字符塞进 messages → 崩溃。

如果用 s04 的子 Agent 来做同一件事：

```
父 Agent:  "请子 Agent 去 review 所有 Python 文件"
  → task(prompt="Review all Python files and summarize style issues")

子 Agent（独立 messages）:
  - 轮次 1: bash find → 列出所有 .py 文件
  - 轮次 2: bash cat × 3 → 读了 94,000 字符    ← 塞进子 Agent 的 messages
  - 轮次 3: 分析 + 总结
  - 返回: "发现 3 个 style issue: ..."           ← 只返回摘要

父 Agent 收到:
  tool_result: "发现 3 个 style issue: ..."      ← 父 messages 只多了这一条
```

94,000 字符留在子 Agent 的 `sub_messages` 里，函数返回后被丢弃。父 Agent 的 messages 只增加了几十字符的摘要。**父 Agent 不会崩溃。**

但要注意：**压力转嫁给了子 Agent。** 94,000 字符现在塞进的是子 Agent 的 `sub_messages`——子 Agent 自己照样面临 context 膨胀、触及 rate limit 或 token 上限的风险。子 Agent 的优势不在于它能处理更多数据，而在于它"崩了也不影响父 Agent"——父 Agent 的 messages 保持干净，可以继续工作。

真正要解决"数据量太大"的问题，需要的是**分治**：把任务拆成多个子 Agent，每个只读几个文件，而不是让一个子 Agent 吞掉所有文件。这已经超出 s04 的范围，但值得记住：**子 Agent 解决的是上下文隔离问题，不是数据量问题。**

---

## 自己动手试试

```sh
python agents/s04_subagent.py
```

| 试这个 prompt | 观察什么 | 详细追踪 |
|---|---|---|
| `Use a subtask to find what testing framework this project uses` | 子 Agent 读了几个文件？摘要有多短？ | [example1.md](../../examples/s04/example1.md) |
| `Delegate: read all .py files and summarize what each one does` | 子 Agent 的 messages 有多长？父 Agent 收到多少？ | [example2.md](../../examples/s04/example2.md) |
| `Use a task to create a new module, then verify it from here` | 子 Agent 写的文件，父 Agent 能读到吗？ | [example3.md](../../examples/s04/example3.md) |

---

## 这一课的关键收获

1. **子 Agent = 独立 messages 的新循环。** 和 s01 的 `agent_loop` 结构一样，只是 messages 从零开始、工具集受限、只返回摘要。
2. **上下文隔离的本质是 messages 隔离。** 父子共享文件系统和工具函数，但各有各的 messages——这就够了。
3. **防止递归靠工具列表，不靠 prompt。** 子 Agent 看不到 `task` 工具，比在 prompt 里写"不要生子 Agent"可靠得多。
4. **摘要是压缩的极端形式。** 子 Agent 可能产生了 20 条 messages，但父 Agent 只收到一句话。信息被极度压缩了——细节丢失，但父 Agent 的 context 保持干净。
5. **这就是 Claude Code 里 Agent tool 的原理。** 你在 Claude Code 里看到的 "Agent tool launched" 就是这个模式：独立上下文、共享文件系统、只返回摘要。
