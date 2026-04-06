# s02 实际运行追踪（例 2）：read_file + edit_file 编辑文件

> prompt: `Edit greet.py to add a docstring to the function`
>
> 结果：3 轮 LLM 调用，2 次工具执行（read_file → edit_file），5 条新 messages
>
> **重点观察：** LLM 自己决定先读后改——虽然你只说了"编辑"，它知道要先看看文件内容才能用 `edit_file` 的 `old_text` 参数。另外，轮次 2 的回复里**同时包含 TextBlock 和 ToolUseBlock**。

---

## 用户输入

**终端输出：**

```
s02 >> Edit greet.py to add a docstring to the function

──────────────────── 用户输入 ────────────────────
query = "Edit greet.py to add a docstring to the function"
```

此时 messages 里已有例 1 的 4 条历史（[0]-[3]），新输入追加在 [4]。

---

## 轮次 1：LLM 回复 → 先读文件

**终端输出：**

```
──────────────────── 轮次 1: LLM 回复 ────────────────────
response.stop_reason = "tool_use"
response.content = [
  ToolUseBlock: name="read_file", id="toolu_01WBWCDgqXoc7iSip3bWmYRw"
    input={"path": "/home/yzeng/Codes/learn-claude-code/greet.py"}
]
```

**LLM 为什么先读再改？** 因为 `edit_file` 需要 `old_text` 参数——你必须告诉它要替换什么。LLM 虽然在例 1 里写过这个文件，但它不确定文件现在的确切内容（可能被手动改过），所以先 `read_file` 看一眼。

这体现了 LLM 的**规划能力**——你只说了"编辑"，它自己拆成了"先读 → 再改"两步。

---

## 轮次 1：执行工具

**终端输出：**

```
──────────────────── 轮次 1: 执行工具 ────────────────────
执行: read_file({"path": "/home/yzeng/Codes/learn-claude-code/greet.py"})
输出 (101 字符):
def greet(name):
    """Return a greeting message for the given name."""
    return f"Hello, {name}!"
```

**对应代码：** 派发表查到 `read_file` → 调用 `run_read()`（第 131-139 行）：

```python
handler = TOOL_HANDLERS.get("read_file")     # → lambda **kw: run_read(kw["path"], kw.get("limit"))
output = handler(**block.input)               # → run_read("/home/.../greet.py", None)
                                              # → 返回文件完整内容（101 字符）
```

这里 LLM 没有传 `limit` 参数，所以 `kw.get("limit")` 返回 `None`，`run_read()` 返回了文件全部内容。如果你想看 `limit` 的效果，可以用 prompt 暗示 LLM：

```
s02 >> Read the first 2 lines of greet.py
```

LLM 大概率会调用 `read_file(path="greet.py", limit=2)`，verbose 输出里会看到 `input` 多了 `"limit": 2`，返回结果变成：

```
def greet(name):
    """
... (12 more lines)
```

`limit` 的价值在于：如果文件有几千行，全读进来会浪费 LLM 的上下文窗口。LLM 可以先 `limit=2` 看一眼开头，再决定要不要读更多。

LLM 现在能看到文件的确切内容了。

---

## 轮次 2：LLM 回复 → TextBlock + ToolUseBlock 同时出现

**终端输出：**

```
──────────────────── 轮次 2: LLM 回复 ────────────────────
response.stop_reason = "tool_use"
response.content = [
  TextBlock: "The function already has a docstring (...). I'll expand it into a full..."
  ToolUseBlock: name="edit_file", id="toolu_01GGYESNqRPBXZ3Ct6wct8mZ"
    input={"path": "/home/yzeng/Codes/learn-claude-code/greet.py",
           "old_text": "    \"\"\"Return a greeting message for the given name.\"\"\"",
           "new_text": "    \"\"\"\n    Return a greeting message for the giv..."}
]
```

**这里有一个重要现象：`response.content` 里同时有 TextBlock 和 ToolUseBlock！**

LLM 每次回复的 `response.content` 是一个列表，里面放什么 block、放几个，**完全由 LLM 自己决定**：

| 场景 | content 里的 block | 实际例子 |
|---|---|---|
| 只说话，不调工具 | `[TextBlock]` | s01 例 3：回答"4" |
| 只调工具，不说话 | `[ToolUseBlock]` | s02 例 1：直接调 write_file |
| 先说话，再调工具 | `[TextBlock, ToolUseBlock]` | **���例轮次 2：先解释"已有 docstring，我来扩展"，再调 edit_file** |
| 同时调多个工具 | `[ToolUseBlock, ToolUseBlock]` | 同时跑两个命令 |

LLM 什么时候会加 TextBlock？当它觉得需要**解释自己在干什么**的时候。这里 LLM 发现文件已经有 docstring 了，和你预期的"添加 docstring"不完全一致，所以先说一句"已经有了，我来扩展它"，然后再调工具。这是 LLM 自己的判断，你的代码不控制这些。

回顾 s01 讲义里说过的：

- `stop_reason = "tool_use"` → 给 `while` 循环用，说"还没完"
- `content` 里的 `block.type` → 给 `for` 循环用，区分哪些是文字（跳过）、哪些是工具（执行）

**你的代码不需要关心 content 里是什么组合。** `for block in response.content` 遍历所有 block，遇到 `tool_use` 就执行，其他的自动跳过（`agent_loop` 第 295-305 行）���

**注意 LLM 发现文件已经有 docstring 了。** 因为例 1 中 LLM 写 `greet.py` 时自作主张加了一行 docstring `"""Return a greeting message for the given name."""`。现在 LLM 决定把它扩展成完整的多行 docstring。这是 LLM 根据 `read_file` 的结果自主调整了方案。

---

## 轮次 2：执行 edit_file

**终端输出：**

```
──────────────────── 轮次 2: 执行工具 ────────────────────
执行: edit_file({"path": "/home/yzeng/Codes/learn-claude-code/greet.py", "old_text": "    \"\"\"Return a greeting message for the given ...)
输出 (51 字符):
Edited /home/yzeng/Codes/learn-claude-code/greet.py
```

**对应代码：** 派发表查到 `edit_file` → 调用 `run_edit()`（第 155-167 行）：

```python
handler = TOOL_HANDLERS.get("edit_file")
output = handler(**block.input)
# → run_edit(path, old_text, new_text)
# → fp.read_text()                              读文件
# → old_text in content?                        找到了旧文本
# → content.replace(old_text, new_text, 1)      替换第 1 处
# → fp.write_text(...)                          写回文件
# → "Edited /home/.../greet.py"
```

**"51 字符"是哪来的？** 就是返回值 `"Edited /home/yzeng/Codes/learn-claude-code/greet.py"` 的字符串长度。每个工具函数最终都返回一个字符串，verbose 打印里的 `输出 (N 字符)` 就是 `len(output)`（`agent_loop` 第 303 行）。回顾三个例子里各工具的返回值：

| 工具 | 返回值 | 长度 |
|---|---|---|
| `run_write` | `"Wrote 102 bytes to /home/.../greet.py"` | 63 字符 |
| `run_read` | 文件的完整内容 | 101 字符（编辑前）/ 317 字符（编辑后） |
| `run_edit` | `"Edited /home/.../greet.py"` | 51 字符 |

`run_read` 返回的是文件内容本身，所以字符数多；`run_write` 和 `run_edit` 返回的只是一句确认信息。这些返回值都会作为 `tool_result` 传给 LLM，LLM 根据内容判断操作是否成功。

---

## 轮次 3：LLM 回复 → 最终回答

**终端输出：**

```
──────────────────── 轮次 3: LLM 回复 ────────────────────
response.stop_reason = "end_turn"
response.content = [
  TextBlock: "Updated the docstring to a full multi-line docstring that includes:

- **Description** — what the function does
- **Args..."
]

──────────────────── 轮次 3: 循环结束 ────────────────────
stop_reason = "end_turn" → 不是 "tool_use"，return!
```

---

## 轮次 3 的 messages 快照

```
──────────────────── 轮次 3: 发送给 LLM ────────────────────
messages = [
  [0] user:      "Create a file called greet.py ..."         (例1)
  [1] assistant: write_file(greet.py, ...)                    (例1)
  [2] user:      tool_result("Wrote 102 bytes")               (例1)
  [3] assistant: "Created greet.py with the following:..."     (例1)
  [4] user:      "Edit greet.py to add a docstring ..."       ← 本次输入
  [5] assistant: read_file(greet.py)                           ← 轮次1：先读
  [6] user:      tool_result("def greet(name):...")            ← 读到的内容
  [7] assistant: [TextBlock + edit_file(old_text, new_text)]   ← 轮次2：再改
  [8] user:      tool_result("Edited .../greet.py")            ← 改成功了
]
```

注意 [7] 里同时有 TextBlock 和 ToolUseBlock——这是一条 assistant 消息里包含了两个 block。

---

## 总结

```
LLM 的工具选择序列：

轮次 1: read_file   → 先看文件当前内容
轮次 2: edit_file   → 根据内容做精确替换
轮次 3: (end_turn)  → 确认完成
```

**核心洞察：**

1. **LLM 自己规划了"先读再改"的策略**——你没有告诉它要先读。
2. **一次回复可以同时包含文字和工具调用**（轮次 2 的 TextBlock + ToolUseBlock）。
3. **LLM 根据读到的内容调整了方案**——发现已有简单 docstring 后，决定扩展而不是新增。
4. **三个不同的工具通过同一个派发表执行**——循环代码完全不关心具体是哪个工具。
