# s04 实际运行追踪：子 Agent 查找测试框架

> prompt: `Use a subtask to find what testing framework this project uses`
>
> 结果：父 Agent 2 轮，子 Agent 3 轮（共 5 次 LLM 调用），子 Agent 的 6 条 messages → 全部丢弃，父 Agent 只收到 2151 字符的摘要
>
> **重点观察：** 子 Agent 从空白 messages 开始，独立完成探索，最终只返回一段摘要。父 Agent 的 messages 始终保持干净——这就是"上下文隔离"。

---

## 启动

**终端输出：**

```
=== s04 verbose 模式 ===
MODEL  = claude-sonnet-4-6
SYSTEM (父) = You are a coding agent at /home/yzeng/Codes/learn-claude-code. Use the task tool to delegate exploration or subtasks.
SYSTEM (子) = You are a coding subagent at /home/yzeng/Codes/learn-claude-code. Complete the given task, then summarize your findings.
PARENT_TOOLS = ["bash", "read_file", "write_file", "edit_file", "task"]
CHILD_TOOLS  = ["bash", "read_file", "write_file", "edit_file"]  ← 没有 task
```

**解读：** 对比 s03 的启动，s04 有 3 个新东西：

| 对比项 | s03 | s04 |
|---|---|---|
| SYSTEM prompt | 1 套 | **2 套**（父/子各一套） |
| TOOLS | 1 套 5 个 | **2 套**：父 5 个（含 task），子 4 个（无 task） |
| 子 Agent 提示 | 无 | `← 没有 task` 明确标注 |

父 Agent 的 system prompt 说 `"Use the task tool to delegate exploration or subtasks."`——告诉 LLM 可以派活。子 Agent 的 system prompt 说 `"Complete the given task, then summarize your findings."`——告诉 LLM 做完就总结。

**子 Agent 没有 `task` 工具**是防止递归套娃的硬约束（参见讲义"概念 1"）。

---

## 用户输入

**终端输出：**

```
s04 >> Use a subtask to find what testing framework this project uses

────────────────── 用户输入 ──────────────────
query = "Use a subtask to find what testing framework this project uses"
```

用户明确说了 `Use a subtask`，这是在引导父 Agent 使用 `task` 工具。如果不这么说，LLM 也可能自己直接用 `bash` 和 `read_file` 去查——它不一定会主动委托。

---

## 父 Agent 第 1 轮：派发子任务

**终端输出：**

```
────────────────── 父 Agent 轮次 1 ──────────────────
messages = [
  [0] user: "Use a subtask to find what testing framework this project uses"
]

→ 调用 client.messages.create(...)

────────────────── 父 Agent 轮次 1: 回复 ──────────────────
response.stop_reason = "tool_use"
response.content = [
  ToolUseBlock: name="task", id="toolu_019f46QJo4giwp4pRTXAgBhp"
    input={"description": "Find the testing framework used in this project", "prompt": "Explore the project at /home/yzeng/Codes/learn-claude-code and determine what testing framework it uses. Look at package.j...
]
```

**解读：** 父 Agent 收到用户请求后，决定使用 `task` 工具。注意它传了两个参数：

- **`description`**: `"Find the testing framework used in this project"`——给人看的简短标签
- **`prompt`**: `"Explore the project at ... and determine what testing framework it uses. Look at package.j..."`——给子 Agent 看的详细指令

`prompt` 是子 Agent 唯一的输入。父 Agent 在这里做了一件聪明的事：它在 prompt 里具体提示了去哪里找（`"Look at package.json, requirements.txt..."`），而不是只说 `"find testing framework"`。这是一种**任务分解的质量**——prompt 写得越好，子 Agent 越高效。

**展开说说"prompt 质量"为什么重要：**

子 Agent 从空白 messages 开始，没有任何上下文。它唯一知道的就是父 Agent 写的这段 prompt。如果 prompt 写得太模糊——比如只说 `"find testing framework"`——子 Agent 就得自己猜该去哪里找，可能会多花好几轮来摸索（先 `ls`，再一个一个目录翻，试错几次才找到方向）。每多一轮就是一次 API 调用，多花钱、多耗时。

但如果 prompt 写得具体——像这里一样点明了 `"Look at package.json, requirements.txt, test files, CI config..."`——子 Agent 第一步就能直奔目标，不用浪费轮次在"搞清楚该看什么"上。

这其实就是**管理者和执行者的关系**：好的管理者（父 Agent）不会只说"把这事搞定"，而是会说"去这几个地方查一下，重点关注这些线索"。管理者之所以能给出这些指引，是因为他看过之前的对话、理解了全局上下文——而执行者（子 Agent）没有这些上下文。

**一个关键的设计取舍浮现了：**

| 策略 | prompt 长度 | 子 Agent 轮数 | 总 API 开销 |
|---|---|---|---|
| 模糊 prompt（`"find testing framework"`） | 很短 | 多（要自己探索） | 高 |
| 详细 prompt（列出了去哪里找） | 较长 | 少（第一步就精准） | 低 |
| 过度详细 prompt（把所有文件内容都塞进 prompt） | 极长 | 1（直接回答） | 高（input token 多） |

最优是中间那个——给足线索但不过载。这和人类工作中写 task ticket 是一回事：太短没人能做，太长没人会读，刚好的是"给出方向 + 关键信息 + 预期产出"。

父 Agent 这次的 prompt 质量恰好在这个最优点上。但要注意：这不是我们代码控制的——是 LLM 自己学会的。如果 LLM 写出了一个糟糕的 prompt，子 Agent 的效率就会下降，而我们的 harness 无法干预。**prompt 质量是 LLM 能力的一部分，不是 harness 能保证的。**

**对应代码：** `s04_subagent.py` 第 313-320 行。父 Agent 循环检测到 `block.name == "task"` → 调用 `run_subagent(prompt)`。

---

## 子 Agent 启动：从空白开始

**终端输出：**

```
────────────────── 父 Agent 轮次 1: 执行工具 ──────────────────
派发子任务: "Find the testing framework used in this project"
prompt: "Explore the project at /home/yzeng/Codes/learn-claude-code and determine what testing framework it uses. Look at package"
──────────────────────────────────────────────────

  │ ────────────────── 子 Agent 启动 ──────────────────
  │ prompt: "Explore the project at /home/yzeng/Codes/learn-claude-code and determine what testing framework it uses. Look at package"
  │ tools: ["bash", "read_file", "write_file", "edit_file"]  (没有 task！)
```

**解读：** 注意缩进和竖线 `│`——所有带 `│` 前缀的输出都是子 Agent 的。这是 verbose 打印用缩进来**视觉区分父子**的设计（参见讲义"verbose 输出里看什么"）。

关键信息：
- **tools 列表里没有 `task`**——子 Agent 不能再生子 Agent
- **prompt** 是父 Agent 编写的——子 Agent 收到的不是用户原始输入，而是父 Agent 加工后的指令

---

## 子 Agent 第 1 轮：探索项目结构

**终端输出：**

```
  │ ────────────────── 子 Agent 轮次 1 ──────────────────
  │ messages = [
  │   [0] user: "Explore the project at /home/yzeng/Codes/learn-claude-code and determine what te..."
  │ ]
  │ → 调用 client.messages.create(...)

  │ ────────────────── 子 Agent 轮次 1: 回复 ──────────────────
  │ response.stop_reason = "tool_use"
  │ response.content = [
  │   TextBlock: "I'll explore the project structure to identify the testing framework. Let me look at multiple files simultaneously."
  │   ToolUseBlock: name="bash", id="toolu_0136M3RiZstJXJeGxikPGm47"
  │     input={"command": "find /home/yzeng/Codes/learn-claude-code -maxdepth 3 -type f | sort"}
  │   ToolUseBlock: name="read_file", id="toolu_01RMmJwbUiMVQSJs6K8J65pX"
  │     input={"path": "/home/yzeng/Codes/learn-claude-code"}
  │ ]

  │ ────────────────── 子 Agent 轮次 1: 执行工具 ──────────────────
  │ 执行: bash({"command": "find /home/yzeng/Codes/learn-claude-code -maxdepth 3 -type f | sort"})
  │ 输出 (7524 字符): /home/yzeng/Codes/learn-claude-code/.env
  ...
  │ 执行: read_file({"path": "/home/yzeng/Codes/learn-claude-code"})
  │ 输出 (71 字符): Error: [Errno 21] Is a directory: '/home/yzeng/Codes/learn-claude-code'
```

**解读：** 子 Agent 的 messages 从 `[0]` 开始——**只有一条消息**，就是父 Agent 传过来的 prompt。这证实了"上下文隔离"：子 Agent 看不到父 Agent 之前的任何对话。

子 Agent 第一步做了两件事（**并行工具调用**，和 s02/s03 里 LLM 的行为一样）：
1. `bash find` 列出所有文件——成功，返回 7524 字符
2. `read_file` 尝试读目录——**失败了**！`Error: [Errno 21] Is a directory`

**错误恢复：** LLM 试图用 `read_file` 读一个目录路径，触发了 `safe_path` 的错误。但这不是致命的——LLM 在下一轮会从错误信息中学习，不再犯同样的错误。这和 s03 例 1 里 LLM 尝试同时标记 2 个 `in_progress` 被拒绝是同一个模式：**错误即教学**。

---

## 子 Agent 第 2 轮：并行读取 6 个关键文件

**终端输出：**

```
  │ ────────────────── 子 Agent 轮次 2 ──────────────────
  │ messages = [
  │   [0] user: "Explore the project at ..."
  │   [1] assistant/text: "I'll explore the project structure to identify the testing framework. Let me loo..."
  │   [1] assistant/tool_use: bash(...)
  │   [1] assistant/tool_use: read_file(...)
  │   [2] user/tool_result: "/home/yzeng/Codes/learn-claude-code/.env..."
  │   [2] user/tool_result: "Error: [Errno 21] Is a directory: ..."
  │ ]
  │ → 调用 client.messages.create(...)

  │ ────────────────── 子 Agent 轮次 2: 回复 ──────────────────
  │ response.stop_reason = "tool_use"
  │ response.content = [
  │   TextBlock: "Now let me read the key files in parallel — `requirements.txt`, the test files, the CI workflow, and the web `package.js..."
  │   ToolUseBlock: name="read_file"  →  requirements.txt
  │   ToolUseBlock: name="read_file"  →  tests/test_agents_smoke.py
  │   ToolUseBlock: name="read_file"  →  tests/test_s_full_background.py
  │   ToolUseBlock: name="read_file"  →  .github/workflows/ci.yml
  │   ToolUseBlock: name="read_file"  →  .github/workflows/test.yml
  │   ToolUseBlock: name="read_file"  →  web/package.json
  │ ]

  │ ────────────────── 子 Agent 轮次 2: 执行工具 ──────────────────
  │ 执行: read_file → requirements.txt     (50 字符)
  │ 执行: read_file → test_agents_smoke.py (602 字符)
  │ 执行: read_file → test_s_full_background.py (2133 字符)
  │ 执行: read_file → ci.yml               (538 字符)
  │ 执行: read_file → test.yml             (913 字符)
  │ 执行: read_file → web/package.json     (915 字符)
```

**解读：** 子 Agent 从第 1 轮的 `find` 输出中挑选了 6 个最可能包含测试框架信息的文件，**一次性并行读取**。这说明 LLM 已经学会了"先全局扫描，再精准读取"的策略。

**这个策略值得展开说说，因为没人教过它这么做。**

回忆一下子 Agent 的 system prompt：`"Complete the given task, then summarize your findings."`——只说了"完成任务然后总结"，完全没提"先列文件再挑着读"。这个两步走策略是 LLM 从训练数据中学到的"涌现行为"：

1. **第 1 轮：全局扫描。** 用 `bash find` 拿到整个项目的文件列表（7524 字符），代价低（一次命令就完成），收益高（看到了全部 109 个文件的路径）。
2. **第 2 轮：精准读取。** 从 109 个文件中只挑了 6 个——`requirements.txt`、两个 test 文件、两个 CI 配置、`package.json`。命中率极高：这 6 个文件恰好是最可能包含测试框架信息的。

**对比一个"笨"策略：** 如果子 Agent 不先扫描，而是直接 `read_file("package.json")`、`read_file("setup.py")`、`read_file("Makefile")`……它在盲猜。猜错了（比如这个项目没有 `setup.py`）就浪费了一次工具调用，还要处理错误、再猜。

**对比例 2 的"蛮力"策略：** 例 2 的子 Agent 也是先 `find`，但第二步选择了读 **所有** 27 个 .py 文件，最终撞了 rate limit。同样是"先扫描再读取"，但**筛选**的质量决定了结果——6 个精选 vs 27 个全读，差别巨大。

这暗示了一个更深层的问题：**LLM 的"判断力"是 Agent 效率的关键瓶颈。** 我们的 harness 只负责执行工具调用——选择哪些文件、读多少、什么顺序，全部由 LLM 决定。如果 LLM 判断力差（像例 2 那样一口气全读），harness 也救不了。如果 LLM 判断力好（像这里精选 6 个），两轮就搞定。

这也是为什么 Claude Code 里的 Agent tool 要强调"给子 Agent 足够的上下文"——好的 prompt 能帮 LLM 做出更好的筛选判断，减少浪费的轮次。

注意子 Agent 的 messages 此时已经有 5 条消息了（[0]-[4]），包含了 7524 字符的 `find` 输出、一个错误信息、以及 6 个文件的内容。**这些全部留在子 Agent 的 `sub_messages` 里**，父 Agent 一个字都看不到。

**把 sub_messages 展开看看，理解"5 条消息"到底是什么：**

```
sub_messages = [
  [0] role: user
      content: "Explore the project at ... Look at package.json, requirements.txt..."
      ← 父 Agent 写的 prompt，子 Agent 唯一的起点

  [1] role: assistant
      content: [
        TextBlock("I'll explore the project structure..."),
        ToolUseBlock(name="bash", input={"command": "find ... -type f | sort"}),
        ToolUseBlock(name="read_file", input={"path": "/home/yzeng/..."}),
      ]
      ← 子 Agent 第 1 轮的回复：1 段话 + 2 个工具调用

  [2] role: user
      content: [
        {"type": "tool_result", "content": "/home/yzeng/.env\n/home/yzeng/..."},   ← 7524 字符！
        {"type": "tool_result", "content": "Error: [Errno 21] Is a directory..."},  ← 71 字符
      ]
      ← harness 执行完工具后塞回的结果

  [3] role: assistant
      content: [
        TextBlock("Now let me read the key files in parallel..."),
        ToolUseBlock(name="read_file", path="requirements.txt"),
        ToolUseBlock(name="read_file", path="test_agents_smoke.py"),
        ... 共 6 个 ToolUseBlock
      ]
      ← 子 Agent 第 2 轮的回复：1 段话 + 6 个工具调用

  [4] role: user
      content: [
        {"type": "tool_result", "content": "anthropic>=0.25.0\n..."},        ← 50 字符
        {"type": "tool_result", "content": "from __future__ import...\n..."},  ← 602 字符
        {"type": "tool_result", "content": "import importlib...\n..."},        ← 2133 字符
        {"type": "tool_result", "content": "name: CI\n..."},                   ← 538 字符
        {"type": "tool_result", "content": "name: Test\n..."},                 ← 913 字符
        {"type": "tool_result", "content": "{\"name\": \"web\"..."},           ← 915 字符
      ]
      ← 6 个文件的完整内容，共 ~5151 字符
]
```

每一轮循环固定增加 2 条消息：一条 `assistant`（LLM 的回复），一条 `user`（工具结果）。所以 2 轮后 = 1（初始 prompt）+ 2×2 = 5 条。

**关键观察：父 Agent 的 messages 同一时刻只有 1 条（用户输入）。** 子 Agent 的 5 条消息里塞了 ~12,800 字符的工具输出，但父 Agent 完全不知道这些内容的存在。这就是"上下文隔离"的实质——不是"看不到"，是根本**不在同一个列表里**。`sub_messages` 和父 Agent 的 `history` 是两个独立的 Python list 对象。

**sub_messages 的增长：**

| 轮次 | messages 数 | 新增内容 |
|---|---|---|
| 开始 | 1 | prompt（~100 字符） |
| 第 1 轮后 | 3 | +assistant 回复 +tool_result（7524 字符 find 输出 + 71 字符错误） |
| 第 2 轮后 | 5 | +assistant 回复 +tool_result（5151 字符，6 个文件内容） |
| 第 3 轮后 | **6** | +assistant 回复（end_turn 的摘要文本）。**没有 +tool_result**——见下文 |

---

## 子 Agent 第 3 轮：生成摘要 + end_turn

**终端输出：**

```
  │ ────────────────── 子 Agent 轮次 3 ──────────────────
  │ messages = [
  │   [0] user: "Explore the project at ..."
  │   [1] assistant/text + tool_use × 2
  │   [2] user/tool_result × 2
  │   [3] assistant/text + tool_use × 6
  │   [4] user/tool_result × 6
  │ ]
  │ → 调用 client.messages.create(...)

  │ ────────────────── 子 Agent 轮次 3: 回复 ──────────────────
  │ response.stop_reason = "end_turn"
  │ response.content = [
  │   TextBlock: "Here is a complete picture of everything found:
  │
  │   ---
  │
  │   ## Testing Framework Analysis
  │
  │   The project uses **two different te..."
  │ ]
```

**解读：** `stop_reason = "end_turn"`——子 Agent 认为任务完成了，不再调用工具。它输出了一段结构化的分析报告（用 Markdown 格式），总结了找到的测试框架信息。

这是 `SUBAGENT_SYSTEM` prompt 里 `"summarize your findings"` 的效果——子 Agent 知道自己该总结，而不是继续挖。

**第 6 条消息就在这里产生。** 看代码（`s04_subagent.py` 第 234-235 行）：

```python
sub_messages.append({"role": "assistant", "content": response.content})  # ← 先 append
if response.stop_reason != "tool_use":
    break                                                                 # ← 再 break
```

先 append，再判断是否 break。所以即使 `stop_reason = "end_turn"`，这个 assistant 回复也已经被塞进 `sub_messages` 了。前 2 轮每轮 +2（assistant + tool_result）= 5 条，第 3 轮只 +1（assistant，没有 tool_result 因为 break 了）= **6 条**。

把完整的 6 条列出来：

| 索引 | role | 内容 | 来源 |
|---|---|---|---|
| [0] | user | prompt | 父 Agent 传入 |
| [1] | assistant | text + bash + read_file | 子 Agent 第 1 轮回复 |
| [2] | user | 2 个 tool_result（find 输出 + 错误） | harness 执行工具 |
| [3] | assistant | text + 6 个 read_file | 子 Agent 第 2 轮回复 |
| [4] | user | 6 个 tool_result（文件内容） | harness 执行工具 |
| **[5]** | **assistant** | **TextBlock: 摘要报告** | **子 Agent 第 3 轮回复（end_turn）** |

第 [5] 条就是第 6 条消息——它被 append 到 `sub_messages` 里了，但紧接着 `break` 跳出循环，不会再有 tool_result。函数返回后，这 6 条消息连同里面的 ~12,800 字符工具输出一起被垃圾回收。

---

## 子 Agent 结束：上下文丢弃的关键时刻

**终端输出：**

```
  │ ────────────────── 子 Agent 结束 ──────────────────
  │ 共 3 轮，子 Agent messages 有 6 条 → 全部丢弃
  │ 只返回摘要 (2151 字符):
  │ Here is a complete picture of everything found:
  │
  │ ---
  │
  │ ## Testing Framework Analysis
  │
  │ The project uses **two different testing frameworks**, one for each layer of the codebase:
  │ ...
──────────────────────────────────────────────────
子任务完成，摘要返回给父 Agent (2151 字符)
```

**解读：** 这是整个 s04 最核心的时刻。三行数字说明一切：

| 指标 | 值 | 含义 |
|---|---|---|
| 子 Agent 轮数 | 3 | 跑了 3 轮工具调用 |
| sub_messages 条数 | 6 | 积累了 6 条消息（含大量文件内容） |
| 返回给父的文本 | 2151 字符 | 从第 6 条消息里**提取**出来的 |

**"全部丢弃"**——`sub_messages` 是 `run_subagent()` 的局部变量，函数返回后被 Python 垃圾回收。子 Agent 读过的 7524 字符 find 输出、5151 字符文件内容，全部消失了。

**对应代码：** `s04_subagent.py` 第 251 行：
```python
summary = "".join(b.text for b in response.content if hasattr(b, "text")) or "(no summary)"
```

注意这行代码在 `for` 循环**外面**。循环里每一轮都会 `response = client.messages.create(...)`，所以 `response` 不断被覆盖。循环结束后，`response` 指向的就是**最后一轮**的 LLM 回复（即第 3 轮、`stop_reason = "end_turn"` 的那次）。代码做的事情很简单：从这个最后一次 response 的 `content` 列表里，把其中的 TextBlock 的 `.text` 拼起来——没有任何"压缩"或"摘要"算法。前两轮的 response 已经被覆盖了，代码根本拿不到。

**那为什么返回的内容看起来像"摘要"？** 因为 LLM 自己选择了输出一段总结性的文字，而不是把前面读到的文件原封不动地吐出来。这是 LLM 的行为——它在第 3 轮看到了 `sub_messages` 里所有的工具输出（find 结果 + 6 个文件内容），然后**自己决定**输出一段结构化的分析报告。"压缩"发生在 LLM 的推理过程中，不在我们的代码里。

换句话说：如果 LLM 在最后一轮选择把所有文件内容原样输出（虽然不太可能，但理论上可以），那 `summary` 就不会是 2151 字符，而是几万字符。我们的代码不控制返回内容的质量和长度——全看 LLM 怎么写。`SUBAGENT_SYSTEM` 里的 `"summarize your findings"` 是一个软约束，引导 LLM 输出摘要，但 LLM 完全有可能无视它。

---

## 父 Agent 第 2 轮：收到摘要，综合回答

**终端输出：**

```
────────────────── 父 Agent 轮次 2 ──────────────────
messages = [
  [0] user: "Use a subtask to find what testing framework this project uses"
  [1] assistant/tool_use: task({"description": "Find the testing framework used in this project", "prompt": "Ex)
  [2] user/tool_result: "Here is a complete picture of everything found:

---

## Testing Framework Analy..."
]

→ 调用 client.messages.create(...)

────────────────── 父 Agent 轮次 2: 回复 ──────────────────
response.stop_reason = "end_turn"
response.content = [
  TextBlock: "The project uses **pytest** as its primary testing framework (with some tests written in **unittest** style, which pytes..."
]

────────────────── 父 Agent 轮次 2: 循环结束 ──────────────────
stop_reason = "end_turn" → return!
```

**解读：** 看父 Agent 的 messages——**只有 3 条**：

1. `[0]` 用户输入
2. `[1]` 父 Agent 的 `task` 工具调用
3. `[2]` 子 Agent 返回的摘要（作为 `tool_result`）

子 Agent 内部的 6 条消息、3 轮工具调用、所有文件内容——父 Agent **完全不知道**。它只看到一个 `tool_result`，就像 `read_file` 或 `bash` 的返回值一样。

**从父 Agent 的角度，`task` 就是一个普通工具。** 它不知道背后有另一个 LLM 循环在跑。

---

## 最终回答

**终端输出：**

```
────────────────── 最终回答 ──────────────────
The project uses **pytest** as its primary testing framework (with some tests written in **unittest** style, which pytest also runs seamlessly).

Here's a quick summary of the findings:

- **Python tests** → [`pytest`](https://docs.pytest.org/), located in the `tests/` directory
  - `test_agents_smoke.py` uses pytest-native features like `@pytest.mark.parametrize`
  - `test_s_full_background.py` uses `unittest.TestCase` style, but is still executed by pytest
  - Tests are run via: `python -m pytest tests/test_agents_smoke.py -q`
  - The CI pipeline (`.github/workflows/test.yml`) installs pytest explicitly

- **Web frontend (Next.js)** → No testing framework is configured; CI only runs TypeScript type-checking and a production build.
```

**解读：** 父 Agent 基于子 Agent 的 2151 字符摘要，进一步精炼出了一个更简洁的回答。注意它**没有重复子 Agent 的全部内容**，而是提取了关键信息。这是两层压缩：

```
原始数据（文件内容）  →  子 Agent 摘要（2151 字符）  →  父 Agent 最终回答（~600 字符）
      ~13,000 字符              ~2,151 字符                    ~600 字符
```

---

## 全局数据对比

| 指标 | 子 Agent 内部 | 父 Agent 可见 |
|---|---|---|
| LLM 调用次数 | 3 次 | 1 次（`task` 工具调用） |
| 工具执行次数 | 9 次（1 bash + 1 错误 + 6 read_file + 1 TextBlock） | 1 次（`task`） |
| messages 条数 | 6 条 | 3 条 |
| 文件内容大小 | ~13,000 字符 | 0 字符 |
| 返回数据大小 | — | 2,151 字符（摘要） |

---

## 这个例子的关键收获

1. **子 Agent 的 messages 从 `[0]` 开始，且结束后全部丢弃。** 这是上下文隔离的核心——父 Agent 的 messages 永远不会被子 Agent 的中间过程"污染"。

2. **子 Agent 会犯错，也会自我纠正。** 它尝试 `read_file` 读目录失败了，但在下一轮自动切换策略。错误信息留在 `sub_messages` 里，子 Agent 从中学习，父 Agent 完全不知道。

3. **并行工具调用在子 Agent 里照常工作。** 子 Agent 在第 2 轮一次性发出 6 个 `read_file` 调用——和 s02/s03 里的行为一模一样。

4. **`task` 工具从父 Agent 的视角看就是一个普通工具。** 父 Agent 不知道背后有另一个 LLM 循环——它只看到 `tool_use → tool_result`，和 `bash` 没有区别。

5. **两层压缩。** 原始文件内容 ~13,000 字符 → 子 Agent 摘要 2,151 字符 → 父 Agent 最终回答 ~600 字符。每一层都在丢弃细节、保留结论。
