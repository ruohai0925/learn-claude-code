# s02 实际运行追踪（例 1）：write_file 创建文件

> prompt: `Create a file called greet.py with a greet(name) function`
>
> 结果：2 轮 LLM 调用，1 次工具执行（write_file），4 条 messages
>
> **重点观察：** LLM 选择了 `write_file` 而不是 `bash("echo ... > greet.py")`。同样是创建文件，s02 有了专用工具后 LLM 会优先选更合适的。

---

## 启动

**终端输出：**

```
=== s02 verbose 模式 ===
MODEL  = claude-sonnet-4-6
SYSTEM = You are a coding agent at /home/yzeng/Codes/learn-claude-code. Use tools to solve tasks. Act, don't explain.
TOOLS  = ["bash", "read_file", "write_file", "edit_file"]
```

对比 s01 的启动：TOOLS 从 `["bash"]` 变成了 4 个工具。SYSTEM 也从 `"Use bash to solve tasks"` 变成了 `"Use tools to solve tasks"`。

---

## 用户输入

**终端输出：**

```
s02 >> Create a file called greet.py with a greet(name) function

──────────────────── 用户输入 ────────────────────
query = "Create a file called greet.py with a greet(name) function"
```

**对应代码：** `__main__` 第 320-330 行，和 s01 一样的 `input()` → `history.append()` → `agent_loop(history)`。

---

## 轮次 1：发送给 LLM

**终端输出：**

```
──────────────────── 轮次 1: 发送给 LLM ────────────────────
messages = [
  [0] user: "Create a file called greet.py with a greet(name) function"
]

→ 调用 client.messages.create(...)
```

和 s01 的第一轮一样，只有 1 条 user 消息。但这次发给 LLM 的 `tools` 参数里有 4 个工具定义，LLM 可以从中选择最合适的。

---

## 轮次 1：LLM 回复

**终端输出：**

```
──────────────────── 轮次 1: LLM 回复 ────────────────────
response.stop_reason = "tool_use"
response.content = [
  ToolUseBlock: name="write_file", id="toolu_01XQRtnUVZLmHXqX67gRgAQS"
    input={"path": "/home/yzeng/Codes/learn-claude-code/greet.py",
           "content": "def greet(name):\n    \"\"\"Return a greeting message for the given name.\"\"\"\n    return f\"Hello, {name}!\"\n"}
]
```

**关键观察——LLM 选了 `write_file` 而不是 `bash`：**

在 s01 里，LLM 创建文件只能用 `bash("echo 'print(\"hello\")' > hello.py")`——需要处理引号转义，容易出错。

现在有了 `write_file`，LLM 直接在 `content` 参数里写完整的文件内容，不需要任何转义。LLM 是怎么做选择的？它看了每个工具的 `description`：

| 工具 | description | LLM 的判断 |
|---|---|---|
| `bash` | "Run a shell command." | 能创建文件，但要用 echo + 转义 |
| `write_file` | "Write content to file." | **直接匹配"创建文件"的意图** |

**LLM 其实已经"写好"了整个文件——但它没有手。** 看 `content` 字段的值，把 `\n` 还原后就是：

```python
def greet(name):
    """Return a greeting message for the given name."""
    return f"Hello, {name}!"
```

LLM 在生成这段 JSON 的时候，文件内容就已经完整了。但它在远程服务器上，碰不到你的磁盘。所以它只能把内容塞进 JSON 参数里，请你的程序帮它写入文件。整个过程就像：

```
LLM（大脑）：  "我知道文件该写什么了" → 输出 JSON：{"path": "greet.py", "content": "..."}
你的程序（手）：收到 JSON → 调用 Path.write_text() → 文件真正写入磁盘
```

**LLM 做了所有的思考（写什么代码、文件叫什么、放在哪），但最后一步执行必须由你的程序来完成。** 这就是 Agent 架构的本质——LLM 是大脑，你的程序是手脚。

**对应代码：** `agent_loop` 第 284-285 行 `print_response(response)`

---

## 轮次 1：执行工具

**终端输出：**

```
──────────────────── 轮次 1: 执行工具 ────────────────────
执行: write_file({"path": "/home/yzeng/Codes/learn-claude-code/greet.py", "content": "def greet(name):\n    \"\"\"Return a greeting messa)
输出 (63 字符):
Wrote 102 bytes to /home/yzeng/Codes/learn-claude-code/greet.py

→ tool_result 已塞回 messages，继续下一轮...
```

**这里是 s02 和 s01 的核心区别——派发表。** 对应代码 `agent_loop` 第 296-300 行：

```python
handler = TOOL_HANDLERS.get(block.name)      # block.name = "write_file"
                                              # → handler = lambda **kw: run_write(kw["path"], kw["content"])
output = handler(**block.input)               # **block.input 展开为 path=..., content=...
                                              # → 调用 run_write("/home/.../greet.py", "def greet(name):...")
                                              # → 返回 "Wrote 102 bytes to ..."
```

s01 里这个位置是硬编码的 `run_bash(block.input["command"])`。s02 改成了查表 → 调用，循环本身没变。

`run_write()` 内部（第 146-153 行）做了什么：

```python
fp = safe_path(path)                          # 检查路径在工作目录内
fp.parent.mkdir(parents=True, exist_ok=True)  # 自动创建目录（如果需要）
fp.write_text(content)                        # 把 content 原样写入文件
return f"Wrote {len(content)} bytes to {path}" # 返回确认信息
```

---

## 轮次 2：LLM 回复 → 最终回答

**终端输出：**

```
──────────────────── 轮次 2: LLM 回复 ────────────────────
response.stop_reason = "end_turn"
response.content = [
  TextBlock: "Created `greet.py` with the following:

- **`greet(name)`** — takes a `name` parameter and returns a greeting string in ..."
]

──────────────────── 轮次 2: 循环结束 ────────────────────
stop_reason = "end_turn" → 不是 "tool_use"，return!
```

LLM 看到 `"Wrote 102 bytes to ..."` 确认写入成功，给出最终回答。和 s01 一样的 `end_turn` → `return` 流程。

---

## 最终回答

```
Created `greet.py` with the following:

- **`greet(name)`** — takes a `name` parameter and returns a greeting string in the format `"Hello, {name}!"`.

**Example usage:**
​```python
from greet import greet

print(greet("Alice"))  # Hello, Alice!
print(greet("World"))  # Hello, World!
​```
```

---

## 总结

```
messages 的增长过程：

[0] user: "Create a file called greet.py with a greet(name) function"
  ↓ 轮次 1：LLM 选择 write_file (stop_reason = "tool_use")
[1] assistant: write_file(path="greet.py", content="def greet(name):...")
  ↓ 轮次 1：执行 run_write() → "Wrote 102 bytes"
[2] user: tool_result("Wrote 102 bytes to .../greet.py")
  ↓ 轮次 2：LLM 确认完成 (stop_reason = "end_turn")
[3] assistant: "Created greet.py with the following:..."
```

**和 s01 例 2 的对比：** s01 创建文件用的是 `bash("echo ... > hello.py")`，s02 用的是 `write_file(path, content)`。循环流程完全一样（2 轮 LLM 调用，1 次工具执行），区别只在用了哪个工具。
