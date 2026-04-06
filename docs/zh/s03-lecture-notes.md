# s03: TodoWrite —— 让 Agent 管理自己的进度

> **前置知识：** 请先完成 [s01-lecture-notes.md](s01-lecture-notes.md) 和 [s02-lecture-notes.md](s02-lecture-notes.md)。本讲义不重复已讲过的概念（agent loop、messages、派发表、JSON Schema），只聚焦 s03 的新内容。

---

## 这一课要回答的问题

> 多步任务（比如"重构这个文件：加类型注解、加文档字符串、加 main guard"）时，LLM 做着做着就忘了还剩什么没做，怎么办？

---

## s01/s02 的问题

s01/s02 的 Agent 做多步任务时，"进度"全靠 LLM 自己在 messages 历史里记住。问题是：

1. **对话越长，LLM 越容易忘。** 前面的任务计划被几十条 tool_result 淹没了，LLM 的注意力被稀释。
2. **你（人）也看不到进度。** LLM 做了 3 步还是 7 步？哪些做完了？哪些跳过了？你只能从终端输出里猜。
3. **LLM 会跑偏。** 一个 10 步重构，做完 2-3 步后 LLM 可能开始"即兴发挥"，忘了剩下的步骤。

---

## s03 的解决方案：两个新机制

| 机制 | 做什么 | 类比 |
|---|---|---|
| **TodoManager** | 给 LLM 一个"白板"，让它写下任务列表并更新状态 | 专家面前的一块白板，每做完一步打个勾 |
| **Nag reminder** | LLM 连续 3 轮没更新白板，你提醒一句"更新你的任务" | 你看到专家 3 步都没动白板，提醒他一句 |

---

## s02 → s03：到底变了什么？

| 组件 | s02 | s03 | 变了吗？ |
|---|---|---|---|
| `while True` 循环结构 | 有 | 一样 | 不变 |
| 工具数量 | 4 个 | **5 个**（+todo） | **变了** |
| TodoManager | 无 | **新增** | **新增** |
| Nag reminder | 无 | **新增** | **新增** |
| `rounds_since_todo` 计数器 | 无 | **新增** | **新增** |
| System prompt | "Use tools to solve tasks" | **"Use the todo tool to plan multi-step tasks"** | **变了** |

---

## 概念 1：TodoManager —— LLM 的白板

### 它是什么

一个 Python 类，存储一个任务列表。每个任务有三个字段：

```python
{"id": "1", "text": "Add type hints", "status": "pending"}
```

三种状态：

| 状态 | 标记 | 含义 |
|---|---|---|
| `pending` | `[ ]` | 还没开始 |
| `in_progress` | `[>]` | 正在做 |
| `completed` | `[x]` | 做完了 |

### 核心规则：同一时间只允许 1 个 `in_progress`

```python
if in_progress_count > 1:
    raise ValueError("Only one task can be in_progress at a time")
```

为什么？**强制 LLM 逐步聚焦。** 如果允许同时开多个任务，LLM 会什么都做一点、什么都没做完。一次只做一件事，做完再开下一件。

### LLM 怎么用它

LLM 通过 `todo` 工具调用 `TodoManager.update()`。注意这是**全量更新**——每次传入完整的任务列表，不是增量（"加一个"/"删一个"）。

```python
# LLM 第一次调用：规划任务
todo(items=[
    {"id": "1", "text": "Add type hints",  "status": "in_progress"},
    {"id": "2", "text": "Add docstrings",  "status": "pending"},
    {"id": "3", "text": "Add main guard",  "status": "pending"},
])

# LLM 完成第一个任务后再次调用：更新状态
todo(items=[
    {"id": "1", "text": "Add type hints",  "status": "completed"},      # ← 改成 completed
    {"id": "2", "text": "Add docstrings",  "status": "in_progress"},    # ← 改成 in_progress
    {"id": "3", "text": "Add main guard",  "status": "pending"},
])
```

为什么全量更新而不是增量？因为 LLM 一次就能输出整个列表，全量替换更简单，不容易出状态不一致的 bug。

### `TodoManager.render()` 返回什么

`update()` 内部调用 `render()`，把任务列表渲染成人类可读的文本，作为 `tool_result` 返回给 LLM：

```
[ ] #1: Add type hints
[>] #2: Add docstrings         ← 正在做
[x] #3: Add main guard         ← 已完成

(1/3 completed)
```

LLM 在下一轮能看到这段文本，知道自己做到哪了。你在终端的 verbose 输出里也能看到。

### todo 工具的 input_schema

这是目前为止最复杂的 schema——`items` 是一个**数组**，数组里每个元素是一个**对象**：

```python
"input_schema": {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",                          # items 是数组
            "items": {                                 # 数组里每个元素的 schema
                "type": "object",
                "properties": {
                    "id":     {"type": "string"},
                    "text":   {"type": "string"},
                    "status": {"type": "string",
                               "enum": ["pending", "in_progress", "completed"]},
                },
                "required": ["id", "text", "status"],
            },
        },
    },
    "required": ["items"],
}
```

注意 `"enum": ["pending", "in_progress", "completed"]`——这告诉 LLM `status` 只能从这三个值里选，不能随便填。

**这个 schema 里有两个 `items`，含义完全不同——别搞混了：**

```python
"properties": {
    "items": {              # ← 第 1 个 items：这是参数名，你自己取的，叫 "tasks" 也行
        "type": "array",
        "items": {          # ← 第 2 个 items：这是 JSON Schema 的关键字，描述数组元素的类型
            "type": "object",
            ...
        },
    },
},
```

| 哪个 `items` | 它是什么 | 谁定义的 | 能改名吗？ |
|---|---|---|---|
| 第 1 个（`"properties"` 下面的） | **参数名**——LLM 传参时用的 key | 你自己取的 | 能，改成 `"tasks"` 也行 |
| 第 2 个（`"type": "array"` 下面的） | **JSON Schema 关键字**——描述"数组里每个元素长什么样" | JSON Schema 规范规定的 | 不能，必须叫 `items` |

回顾 s01 讲义里的 JSON Schema 规则——不同 `type` 需要不同的描述字段：

```
type: "object"  → 用 properties 描述里面有哪些字段
type: "array"   → 用 items 描述里面每个元素的类型
type: "string"  → 不需要额外描述
```

这里碰巧参数名也叫 `items`，和 JSON Schema 关键字 `items` 撞名了，所以看起来像是重复。实际上一个是你的参数（第 1 层），另一个是 schema 语法（第 2 层）。如果把参数名改成 `tasks`，就没有混淆了：

```python
"properties": {
    "tasks": {              # ← 参数名改成 tasks，不再混淆
        "type": "array",
        "items": { ... },   # ← JSON Schema 关键字，还是叫 items
    },
},
```

---

## 概念 2：Nag Reminder —— 催更机制

> **Nag** 的英文意思是"唠叨、反复催促"，就像家长反复催你写作业——"作业写了吗？""作业写了吗���"——这种行为就叫 nagging��Nag reminder 就是"唠叨式提醒"——LLM 连续 3 轮没更新 todo，程序就催一次，每次都催，直到 LLM 更新为止。

### 问题

即使给了 LLM todo 工具，它也可能忘记用。对话越长、中间工具调用越多，LLM 越容易忘记更新任务状态。

### 解决方案：一个计数器 + 一条提醒

```python
rounds_since_todo = 0 if used_todo else rounds_since_todo + 1

if rounds_since_todo >= 3:
    results.append({"type": "text", "text": "<reminder>Update your todos.</reminder>"})
```

逻辑很简单：

1. 每轮检查 LLM 是否调用了 `todo` 工具
2. 调用了 → `rounds_since_todo` 归零
3. 没调用 → `rounds_since_todo` +1
4. 连续 3 轮没调用 → 在 `tool_result` 后面追加一条 `<reminder>` 提醒

### 提醒是怎么注入的？

提醒作为 `{"type": "text", "text": "<reminder>..."}` 追加到 `results` 列表里，然后整个 `results` 作为 `user` 消息塞回 messages。LLM 在下一轮调用时会看到这条提醒。

```python
# results 列表里可能同时有 tool_result 和 text：
results = [
    {"type": "tool_result", "tool_use_id": "toolu_xxx", "content": "Edited hello.py"},
    {"type": "text", "text": "<reminder>Update your todos.</reminder>"},   # ← nag
]
messages.append({"role": "user", "content": results})
```

### 为什么用 `<reminder>` 标签？

`<reminder>...</reminder>` 是给 LLM 看的标记——LLM 在训练数据中见过这种 XML 风格的标签，知道这是系统层面的提示，不是用户说的话。它会因此想起来更新任务状态。

### 类比

你和蒙眼专家在做一个大项目。专家面前有一块白板（TodoManager）。你们约定：专家每做完一步就在白板上更新。但专家有时候忙着干活忘了更新，你数了数——他已经连续 3 步都没动白板了——你就提醒一句："记得更新你的任务列表。"

---

## agent_loop 的变化

把 s02 和 s03 的循环放在一起看，新增部分用 `# ← NEW` 标注：

```python
def agent_loop(messages: list):
    rounds_since_todo = 0                                    # ← NEW: 计数器
    while True:
        response = client.messages.create(...)
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return

        results = []
        used_todo = False                                    # ← NEW: 本轮是否用了 todo
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                output = handler(**block.input)
                results.append({"type": "tool_result", ...})
                if block.name == "todo":                     # ← NEW: 检查是否是 todo
                    used_todo = True

        # ── s03 新增：nag reminder 逻辑 ──
        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1   # ← NEW
        if rounds_since_todo >= 3:                                       # ← NEW
            results.append({"type": "text",                              # ← NEW
                            "text": "<reminder>Update your todos.</reminder>"})

        messages.append({"role": "user", "content": results})
```

**注意 `for block in response.content` 可能执行多个工具。** 一次 LLM 回复的 `response.content` 里可以有多个 ToolUseBlock，`for` 循环会逐个执行。比如 LLM 可能一次同时调用 `todo` 和 `edit_file`：

```python
response.content = [
    ToolUseBlock(name="todo",      input={...}),   # 先更新任务状态
    ToolUseBlock(name="edit_file", input={...}),   # 再编辑文件
]

# for 循环走两遍：
# 第 1 遍：block.name = "todo"      → 执行 TODO.update() → used_todo = True
# 第 2 遍：block.name = "edit_file" → 执行 run_edit()    → used_todo 不变（还是 True）
```

两个工具的结果都收集到 `results` 列表里，一起作为一条 `user` 消息塞回 messages。不过实际运行中，LLM 大多数时候一次只调一个工具。在 s03 里，你更可能看到 LLM 交替调用：一轮调 `todo` 更新状态，下一轮调 `edit_file` 干活。

循环的"骨架"（while → create → append → check → execute → append）和 s01/s02 完全一样。新增的只是计数器和提醒注入。

---

## verbose 输出里看什么

s03 的 verbose 打印比 s02 多了几样：

| 新增打印 | 位置 | 看什么 |
|---|---|---|
| `当前 TODO 状态:` | 每轮发送给 LLM 前 | 任务列表的实时快照（`[ ]`/`[>]`/`[x]`） |
| `✓ 本轮调用了 todo` | 执行工具后 | LLM 是否更新了任务 |
| `○ 距上次 todo: N 轮` | 执行工具后 | 计数器当前值 |
| `⚠ 注入 nag reminder` | `rounds_since_todo >= 3` 时 | 提醒被注入了 |
| `最终 TODO 状态:` | 循环结束时 | 所有任务是否都 completed |

---

## 自己动手试试

```sh
python agents/s03_todo_write.py
```

| 试这个 prompt | 观察什么 | 详细追踪 |
|---|---|---|
| `Refactor the file hello.py: add type hints, docstrings, and a main guard` | LLM 是否先用 todo 规划 3 步？每步做完后是否更新状态？ | [s03_example1.md](../../examples/s03/example1.md) |
| `Create a Python package with __init__.py, utils.py, and tests/test_utils.py` | LLM 规划了几个任务？有没有触发 nag reminder？ | [s03_example2.md](../../examples/s03/example2.md) |
| `Review all Python files and fix any style issues` | 开放式任务，LLM 怎么规划？任务数量会不会超过预期？ | [s03_example3.md](../../examples/s03/example3.md) |

---

## 这一课的关键收获

1. **LLM 会忘事。** 对话越长，早期的计划越容易被淹没。外部状态管理（TodoManager）比纯靠 LLM 记忆可靠。
2. **TodoManager 是一个"工具"，不是魔法。** 它和 `bash`、`read_file` 一样，在派发表里注册、通过 `tool_use` 调用。LLM 决定什么时候调用、传什么参数。
3. **Nag reminder 是"催更"，不是"控制"。** 你没有强制 LLM 必须更新 todo，只是在它连续 3 轮忘记时提醒一句。LLM 看到提醒后自主决定怎么做。
4. **同一时间只允许 1 个 in_progress** 是一个设计选择——强制逐步聚焦。这不是 LLM 的限制，是你的程序给 LLM 设的规则。
5. **循环还是没变。** 新增的只是一个计数器和一条提醒注入。
