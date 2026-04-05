# s02: Tool Use —— 给 Agent 更多工具

> **前置知识：** 请先完成 [s01-lecture-notes.md](s01-lecture-notes.md)。本讲义不重复 s01 已讲过的概念（agent loop、messages、stop_reason、JSON Schema、tool_use 信息流），只聚焦 s02 的新内容。

---

## 这一课要回答的问题

> s01 的 Agent 只有 bash 一个工具。如果我想加更多工具，需要改循环吗？

**答案：不需要。循环一行都不改。**

---

## s01 → s02：到底变了什么？

| 组件 | s01 | s02 | 变了吗？ |
|---|---|---|---|
| `while True` 循环 | 有 | 一模一样 | 不变 |
| `stop_reason` 判断 | 有 | 一模一样 | 不变 |
| `messages` 累积 | 有 | 一模一样 | 不变 |
| 工具数量 | 1 个 (bash) | **4 个** (bash, read_file, write_file, edit_file) | **变了** |
| 工具执行方式 | `run_bash(block.input["command"])` 硬编码 | **`TOOL_HANDLERS[block.name](**block.input)`** 查表 | **变了** |
| 路径安全 | 无 | **`safe_path()` 沙箱** | **新增** |

只有下半部分变了。这一课的核心就是**三个新概念**：派发表、专用工具函数、路径沙箱。

---

## 概念 1：工具派发表（dispatch map）

### s01 的问题

s01 的循环里硬编码了 `run_bash`：

```python
# s01 写法：只有一个工具，直接调
output = run_bash(block.input["command"])
```

如果加第二个工具，你得写 `if/elif`：

```python
# 如果不用派发表，4 个工具要这样写：
if block.name == "bash":
    output = run_bash(block.input["command"])
elif block.name == "read_file":
    output = run_read(block.input["path"])
elif block.name == "write_file":
    output = run_write(block.input["path"], block.input["content"])
elif block.name == "edit_file":
    output = run_edit(block.input["path"], block.input["old_text"], block.input["new_text"])
```

每加一个工具就要加一个 `elif`，循环越来越臃肿。

### s02 的解决方案：一个字典

```python
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}
```

循环里只需要两行：

```python
handler = TOOL_HANDLERS[block.name]     # 根据工具名找到处理函数
output = handler(**block.input)          # 调用处理函数
```

### 类比

s01：你（循环）只会帮专家跑终端命令，因为只有一种工具。

s02：你手边有一张对照表：

```
专家说"跑命令"  → 你去终端
专家说"读文件"  → 你去打开文件
专家说"写文件"  → 你去创建文件
专家说"改文件"  → 你去找到旧文本替换成新文本
```

你（循环）查表就行，不需要记住每个工具的细节。

### `lambda **kw` 是什么？

LLM 传来的参数是一个字典，比如 `{"path": "greet.py", "content": "def greet(name):..."}`。

`**kw` 把这个字典"展开"为关键字参数：

```python
# LLM 传来的 block.input = {"path": "greet.py", "content": "def greet(name):..."}

lambda **kw: run_write(kw["path"], kw["content"])
# 等价于：
lambda **kw: run_write("greet.py", "def greet(name):...")
```

`kw.get("limit")` 用 `.get()` 是因为 `limit` 是选填参数。`limit` 的意思是"最多读几行"——有些文件几千行，全读进来浪费 LLM 上下文窗口，LLM 可以先 `limit=10` 看一眼开头，再决定要不要读更多。

`limit` 没出现在 `input_schema` 的 `required` 里（只有 `"required": ["path"]"`），所以 LLM 可能传 `{"path": "greet.py"}`（没有 limit 字段）。这时候：

- `kw["limit"]` → 报错 `KeyError`，程序崩溃
- `kw.get("limit")` → 返回 `None`，正常运行

`run_read()` 里收到 `limit=None` 后，`if limit and limit < len(lines)` 为 `False`，跳过截断，返回全部内容。

---

## 概念 2：四个工具函数

s01 只有 `run_bash()`。s02 新增了三个文件操作函数。每个函数的模式一样：**接收参数 → 执行操作 → 返回字符串**。

### `run_read(path, limit)` —— 读文件

```python
def run_read(path: str, limit: int = None) -> str:
    text = safe_path(path).read_text()          # 读取完整文件内容
    lines = text.splitlines()
    if limit and limit < len(lines):
        lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
    return "\n".join(lines)[:50000]              # 截断到 50000 字符
```

返回文件内容的字符串。如果文件有 1000 行但 `limit=10`，只返回前 10 行。

### `run_write(path, content)` —— 写文件

```python
def run_write(path: str, content: str) -> str:
    fp = safe_path(path)
    fp.parent.mkdir(parents=True, exist_ok=True)  # 目录不存在则自动创建
    fp.write_text(content)
    return f"Wrote {len(content)} bytes to {path}"
```

返回 `"Wrote 42 bytes to greet.py"` 这样的确认信息。LLM 看到后知道写入成功了。

### `run_edit(path, old_text, new_text)` —— 编辑文件

```python
def run_edit(path: str, old_text: str, new_text: str) -> str:
    fp = safe_path(path)
    content = fp.read_text()
    if old_text not in content:
        return f"Error: Text not found in {path}"     # 找不到旧文本 → 报错
    fp.write_text(content.replace(old_text, new_text, 1))  # 只替换第 1 次出现
    return f"Edited {path}"
```

`replace(old_text, new_text, 1)` 的第三个参数 `1` 表示只替换第一次出现。用一个具体例子说明：

假设 `greet.py` 里碰巧有两个 `def greet(name):`：

```python
def greet(name):
    return f"Hello, {name}!"

def greet(name):
    return f"Hi, {name}!"
```

LLM 想给第一个加 docstring，调用 `edit_file(old_text="def greet(name):", new_text="def greet(name):\n    \"\"\"Greet someone.\"\"\"")`：

| 写法 | 第一个函数 | 第二个函数 |
|---|---|---|
| `replace(old, new)` 不传第三个参数 | 被替换了 | **也被替换了**（意外！） |
| `replace(old, new, 1)` 传 `1` | 被替换了 | **保持原样**（安全） |

这个 `1` 是**代码设计者**（写这个工具的人）的保守默认值，不是 LLM 决定的。LLM 甚至不知道背后有个 `1`——它只看到工具描述 `"Replace exact text in file."`，自然理解为"替换一处"。实际运行时：

- 大多数情况下，LLM 给的 `old_text` 足够精确，文件里只有一处匹配，`1` 不起作用
- 如果 LLM 想改多处，可以多次调用 `edit_file`，每次改一处
- `1` 真正防的是意外：LLM 给的 `old_text` 太短太泛（比如只写了 `return`），碰巧匹配了多处，没有 `1` 就全改了

如果你想让 LLM 能一次替换所有匹配，可以加一个 `replace_all` 参数。实际上 Claude Code 的 Edit 工具就是这么做的——它的工具定义里有 `"replace_all": {"default": false}` 这个选填参数。

如果 `old_text` 在文件中找不到，返回错误信息，LLM 看到后可以调整重试。

### 这些工具函数本质上是"包装层"

你可能注意到，`run_read` / `run_write` / `run_edit` 做的事情，Python 原生就能做——`Path.read_text()`、`Path.write_text()`、`str.replace()`。这些工具函数就是在原生能力上包了一层，加了三样东西：

| 包装层加了什么 | 为什么需要 |
|---|---|
| `safe_path()` 安全检查 | 原生 `Path` 可以读写任意路径，LLM 可能访问 `/etc/passwd` |
| `try/except` 错误处理 | 原生操作报错会崩掉整个程序，包装后返回错误字符串让 LLM 自己决定下一步 |
| 返回值统一为字符串 | LLM 只能读文字。`Path.write_text()` 原生返回字节数（int），LLM 看不懂 |

整个信息流就是一条翻译链：

```
LLM 输出 JSON → 包装函数把 JSON 翻译成 Python 操作 → 操作结果变回字符串 → 传给 LLM
```

### 为什么不全用 bash？

你可能会想：`bash` 也能 `cat`、`echo >`、`sed` 啊，为什么还要专用工具？

| 操作 | 用 bash | 用专用工具 |
|---|---|---|
| 读文件 | `cat file.py` — 遇到特殊字符可能截断 | `read_file(path="file.py")` — 稳定 |
| 写文件 | `echo '...' > file.py` — 引号转义容易出错 | `write_file(path="file.py", content="...")` — 内容原样写入 |
| 改文件 | `sed -i 's/old/new/' file.py` — 特殊字符需转义 | `edit_file(path="file.py", old_text="old", new_text="new")` — 精确匹配 |
| 安全性 | LLM 可以 `cat /etc/passwd` | `safe_path()` 限制在工作目录内 |

---

## 概念 3：路径沙箱 `safe_path()`

```python
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()           # 拼接并解析 .. 等符号
    if not path.is_relative_to(WORKDIR):     # 解析后是否还在工作目录下？
        raise ValueError(f"Path escapes workspace: {p}")
    return path
```

`.resolve()` 会把 `../../../etc/passwd` 这样的路径解析成绝对路径。然后检查解析后的路径是否还在 `WORKDIR` 下。

```
safe_path("greet.py")             → /home/user/project/greet.py       ✓ 在工作目录下
safe_path("sub/dir/file.py")      → /home/user/project/sub/dir/file.py ✓
safe_path("../../etc/passwd")     → /etc/passwd                        ✗ 逃逸了！抛异常
```

bash 工具没有这个保护——LLM 可以通过 bash 执行 `cat /etc/passwd`。这就是为什么文件操作应该用专用工具而不是全走 bash。

---

## 工具定义（TOOLS 列表）

s01 的 TOOLS 只有 1 个工具。s02 有 4 个，结构和 s01 完全一样（详见 [s01-lecture-notes.md](s01-lecture-notes.md) "第 2 部分"）。

值得注意的是不同工具的参数差异：

| 工具 | 必填参数 | 选填参数 |
|---|---|---|
| `bash` | `command` (string) | 无 |
| `read_file` | `path` (string) | `limit` (integer) |
| `write_file` | `path` (string), `content` (string) | 无 |
| `edit_file` | `path` (string), `old_text` (string), `new_text` (string) | 无 |

LLM 根据每个工具的 `input_schema` 知道该填什么参数。你在 s01 已经学过这个机制。

---

## agent_loop：和 s01 的对比

把 s01 和 s02 的循环放在一起看，唯一的区别用 `<<<` 标注：

```python
# s01 的循环（工具执行部分）：
for block in response.content:
    if block.type == "tool_use":
        output = run_bash(block.input["command"])          # ← 硬编码 run_bash

# s02 的循环（工具执行部分）：
for block in response.content:
    if block.type == "tool_use":
        handler = TOOL_HANDLERS.get(block.name)            # ← 查表找到 handler
        output = handler(**block.input) if handler \       # ← 调用 handler
            else f"Unknown tool: {block.name}"
```

**循环的其他部分（`while True`、`client.messages.create()`、`stop_reason` 判断、`messages.append()`）一字不差。**

---

## 自己动手试试

```sh
python agents/s02_tool_use.py
```

按顺序输入以下 3 个 prompt，观察 LLM 选择了哪个工具：

| 试这个 prompt | 预期 LLM 选择的工具 | 详细追踪 |
|---|---|---|
| `Create a file called greet.py with a greet(name) function` | `write_file` | [s02_example1.md](../../agents/s02_example1.md) |
| `Edit greet.py to add a docstring to the function` | `edit_file` | [s02_example2.md](../../agents/s02_example2.md) |
| `Read greet.py to verify the edit worked` | `read_file` | [s02_example3.md](../../agents/s02_example3.md) |

三个 prompt 刚好覆盖三个新工具（write → edit → read）。注意 LLM 是**自己选**用哪个工具——你的 prompt 里没有指定工具名。

---

## 这一课的关键收获

1. **循环不变。** 加工具 = 加 `TOOL_HANDLERS` 里的一行 + 加 `TOOLS` 里的一个定义。
2. **派发表替代 if/elif。** `TOOL_HANDLERS[block.name]` 一行搞定，工具再多也不臃肿。
3. **专用工具比全走 bash 更安全、更稳定。** `safe_path()` 是第一层安全边界。
4. **LLM 自己选工具。** 你说"创建文件"，它选 `write_file`；你说"编辑文件"，它选 `edit_file`。选择依据是每个工具的 `description`。
