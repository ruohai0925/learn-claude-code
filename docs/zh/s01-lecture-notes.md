# 从零拆解 AI Coding Agent —— 逐课讲义

> 基于 [learn-claude-code](https://github.com/anthropics/learn-claude-code) 的 12 个渐进式 Python 示例，
> 从最简单的 30 行 Agent 一路搭建到多人协作的自主 Agent 团队。

---

## 全局路线图

在开始之前，先看看整条路长什么样。每一课都只加一个新机制，像搭积木一样往上叠：

```
s01  Agent Loop        ← 最小闭环：LLM + 一个工具 + 一个循环
s02  Tool Use          ← 多工具 + 派发表
s03  TodoWrite         ← 任务状态 + 催更提醒
s04  Subagent          ← 子进程隔离 + 摘要返回
s05  Skill Loading     ← 按需加载知识，不撑爆 system prompt
s06  Context Compact   ← 上下文压缩，让 Agent 能"一直干活"
s07  Task System       ← 持久化任务状态（压缩也丢不掉）
s08  Background Tasks  ← 多线程，后台跑耗时命令
s09  Agent Teams       ← 多 Agent + 消息总线
s10  Team Protocols    ← 结构化握手协议
s11  Autonomous Agents ← 空闲轮询 + 自动领任务
s12  Worktree Isolation← Git worktree 目录隔离
s_full                 ← 以上全部组装在一起的完整参考实现
```

每一课你只需要弄懂**一个新概念**，其余的都是上一课已经见过的。

---

## 前置知识

在读代码之前，确保你对下面几个东西不陌生：

| 你需要知道的 | 一句话解释 | 不熟的话去哪看 |
|---|---|---|
| Python 基础 | 列表、字典、`while`、函数 | 任意 Python 入门教程 |
| API 调用 | 给一个 URL 发 JSON，拿回 JSON | 想象成点外卖：发订单 → 收外卖 |
| LLM 是什么 | 给一段话，它续写下一段 | 你用过 ChatGPT 就行 |

**不需要** 提前懂 Anthropic SDK、tool use 协议、prompt engineering。讲义会从头讲。

---

## s01: The Agent Loop —— 最小可运行的 Agent

### 这一课要回答的问题

> 为什么 ChatGPT/Claude 只能"说"，不能"做"？怎么让它学会"做"？

### 核心类比：你和一个蒙眼专家

想象你找了一个专家来修电脑。但这个专家被蒙着眼，手也被绑着——他很聪明，但**碰不到任何东西**。

你们之间只能靠**对话**协作：

```
你：    "电脑开不了机。"
专家：  "帮我看一下电源灯亮不亮。"         ← 专家发出"指令"
你：    "灯不亮。"                           ← 你执行后告诉他结果
专家：  "帮我拔掉电源线，等10秒，再插上。"   ← 又一条指令
你：    "好了，灯亮了。"                     ← 又一个结果
专家：  "应该是电源接触不良，现在试试开机。"  ← 专家觉得搞定了，不再发指令
```

在这个故事里：

| 角色 | 对应代码里的谁 |
|---|---|
| 你 | 程序（harness / agent loop） |
| 蒙眼专家 | LLM（Claude） |
| "帮我看一下…" | `tool_use`（LLM 请求调用工具） |
| "灯不亮" | `tool_result`（工具执行结果） |
| "应该是电源接触不良" | `end_turn`（LLM 最终回答） |

**关键洞察：LLM 自己不能执行任何操作。它只能说"我想做 X"，然后等你把结果告诉它。**

### 把类比映射到代码

下面我们把这个故事一步步变成代码。

#### 第 1 部分：对话记录 = 一个列表

专家和你之间的所有对话，按顺序记在一张纸上。在代码里，这就是 `messages` 列表：

```python
messages = []
```

每次有人说话，就往列表末尾追加一条：

```python
# 你说的话 → role: "user"
messages.append({"role": "user", "content": "电脑开不了机"})

# 专家说的话 → role: "assistant"
messages.append({"role": "assistant", "content": "帮我看一下电源灯亮不亮"})

# 你执行完后告诉专家结果 → 还是 role: "user"！
messages.append({"role": "user", "content": "灯不亮"})
```

注意：**工具执行结果也是以 `"role": "user"` 的身份塞回去的**。对 LLM 来说，"人说的话" 和 "工具返回的结果" 没有本质区别——都是 user 消息。

#### 第 2 部分：告诉 LLM 它有什么工具

在把对话交给 LLM 之前，你要告诉它："你有一个工具叫 `bash`，可以跑 shell 命令。"

```python
TOOLS = [{
    "name": "bash",
    "description": "Run a shell command.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}]
```

这就像告诉蒙眼专家："你可以让我帮你跑终端命令。你只需要说出命令是什么，我来执行。"

LLM **不会自己跑命令**，它只是在回复里写"我想调用 bash，参数是 `ls -la`"。

##### 为什么工具定义长这样？——逐层拆解 TOOLS

初看这个结构可能不直觉。根本原因是：**LLM 只能读文字**。它没有手、没有终端、没有文件系统。你要让它"用工具"，唯一的办法是**用文字描述**这个工具长什么样、接受什么参数。LLM 读懂后，如果它想用，就在回复里按这个格式写出来。

所以 `TOOLS` 不是代码，不是函数指针——它是一份**说明书**，发给 LLM 读的。

**第 1 层：`TOOLS` 是一个列表**

```python
TOOLS = [ ... ]
```

因为可以有多个工具。s01 只有一个 bash，但 s02 会有 `bash`、`read_file`、`write_file`、`edit_file` 四个。所以用列表装。

**第 2 层：每个工具是一个字典，有 3 个字段**

```python
{
    "name": "bash",                        # ① 工具叫什么
    "description": "Run a shell command.", # ② 这个工具干什么（给 LLM 读的）
    "input_schema": { ... },              # ③ 需要什么参数（给 LLM 读的）
}
```

| 字段 | 给谁看的 | 作用 |
|---|---|---|
| `name` | LLM + 你的程序 | LLM 用它来说"我要调 bash"，你的程序用它来找对应的处理函数 |
| `description` | LLM | LLM 根据这个描述来决定**什么时候**用这个工具 |
| `input_schema` | LLM | LLM 根据这个来知道**怎么填参数** |

**第 3 层：`input_schema` 是 JSON Schema**

```python
"input_schema": {
    "type": "object",                          # 参数整体是一个对象（字典）
    "properties": {                            # 里面有哪些字段：
        "command": {"type": "string"}          #   command 字段，类型是字符串
    },
    "required": ["command"],                   # command 是必填的
}
```

这不是 Anthropic 发明的格式，而是业界通用的 [JSON Schema](https://json-schema.org/) 标准。它的作用是**用 JSON 来描述"一个 JSON 应该长什么样"**。为什么用它？因为 LLM 需要一种机器也能读、人也能读的方式来理解参数格式。

##### 深入理解 `input_schema`：JSON vs JSON Schema

先分清两个东西：

```
普通 JSON（数据本身）：     {"command": "ls"}
JSON Schema（数据的规格书）：描述上面那个 JSON "应该长什么样"
```

用点菜来类比：
- 普通 JSON = 你写的点菜单："宫保鸡丁一份"
- JSON Schema = 餐厅的点单模板："请写菜名（必填，文字），份数（选填，数字）"

`input_schema` 就是模板，LLM 按模板填内容。

**`type`、`properties`、`required` 是固定的吗？**

不是都需要。取决于你的参数是什么类型。JSON Schema 的规则很简单——**先用 `type` 说明是什么类型，再根据类型补充细节**：

```
type: "string"  → 就这一个字段就够了，没有 properties
type: "number"  → 同上
type: "boolean" → 同上
type: "object"  → 需要 properties（告诉里面有哪些字段）
type: "array"   → 需要 items（告诉里面每个元素是什么类型）
```

用几个具体例子对比：

**例 1：只要一个字符串参数**（搜索代码，参数只有一个关键词）

```python
"input_schema": {
    "type": "object",
    "properties": {
        "keyword": {"type": "string"}     # 只需要 type
    },
    "required": ["keyword"]
}
```

LLM 会填：`{"keyword": "TODO"}`

**例 2：一个必填 + 一个选填**（读文件，路径必填，行数选填）

```python
"input_schema": {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "limit": {"type": "number"}       # 没放进 required → 选填
    },
    "required": ["path"]                   # 只有 path 是必填的
}
```

LLM 可以填：`{"path": "/tmp/a.py"}` 或 `{"path": "/tmp/a.py", "limit": 50}`

**例 3：没有任何参数**（获取当前时间，不需要任何参数）

```python
"input_schema": {
    "type": "object",
    "properties": {}                       # 空的
}
                                           # 没有 required → 全都不必填
```

LLM 会填：`{}`

**回到 s01 的 bash 工具**，现在再看就清楚了：

```python
"input_schema": {
    "type": "object",          # ← 最外层永远是 object，因为参数整体是个字典
    "properties": {            # ← 字典里有哪些 key？
        "command": {           # ←   有一个 key 叫 "command"
            "type": "string"   # ←   它的值是字符串
        }
    },
    "required": ["command"]    # ← "command" 必须填
}
```

翻译成人话：**"这个工具接受一个参数，名叫 command，是字符串，必填。"**

LLM 读到后就知道：我想跑 `ls` 的话，回复 `{"command": "ls"}` 就行。

**为什么最外层永远是 `"type": "object"`？** 因为 Anthropic API 的约定——工具参数整体必须是一个对象（字典），不能是裸的字符串或数字。所以所有工具定义都是这个壳子：

```python
"input_schema": {
    "type": "object",       # ← 永远是这个，不用纠结
    "properties": { ... },  # ← 你自己定义的参数放这里
    "required": [ ... ]     # ← 哪些参数必填放这里（可以省略）
}
```

**你只需要关心 `properties` 里面放什么。外面的壳子是固定的。**

##### 完整信息流：工具定义 → LLM 回复 → 你的程序

把工具定义、LLM 回复、你的程序串在一起看：

```
你发给 LLM 的：
┌──────────────────────────────────────────────────┐
│  messages: [用户的问题]                            │
│  tools: [{                                        │
│    name: "bash",                                  │
│    description: "Run a shell command.",            │
│    input_schema: { command: string (必填) }        │
│  }]                                               │
└──────────────────────────────────────────────────┘
                      ↓
              LLM 读懂后回复：
┌──────────────────────────────────────────────────┐
│  stop_reason: "tool_use"                          │
│  content: [{                                      │
│    type: "tool_use",                              │
│    name: "bash",              ← 对应你定义的 name  │
│    input: { "command": "ls" } ← 按你的 schema 填的 │
│    id: "toolu_abc123"                             │
│  }]                                               │
└──────────────────────────────────────────────────┘
                      ↓
              你的程序：
┌──────────────────────────────────────────────────┐
│  看到 name == "bash"                              │
│  取出 input["command"] == "ls"                    │
│  执行 run_bash("ls")                              │
│  把结果塞回 messages                               │
└──────────────────────────────────────────────────┘
```

**LLM 的回复格式和你的工具定义是镜像关系**：你定义了 `name: "bash"`，它就回 `name: "bash"`；你定义了参数叫 `command`，它就填 `input: {"command": "ls"}`。

##### 为什么不直接传一个 Python 函数？

你可能会想：为什么不直接 `tools=[run_bash]` 这样传函数？

因为 **LLM 是一个远程 API**。你的代码在你的电脑上，LLM 在 Anthropic 的服务器上。你不可能把一个 Python 函数传到它的服务器上去执行。你们之间只能传 JSON。所以：

- 你用 JSON 告诉 LLM："有个工具叫 bash，接受一个 command 参数"
- LLM 用 JSON 告诉你："我想调 bash，command 是 ls"
- 你在本地执行，再用 JSON 把结果传回去

**一切都是 JSON 文本，因为这是你和远程 LLM 之间唯一能传递的东西。**

#### 第 3 部分：LLM 的两种回复

每次你把对话发给 LLM，它会回一个 `response`。这个 response 里有一个关键字段：**`stop_reason`**。

| stop_reason | 含义 | 类比 |
|---|---|---|
| `"tool_use"` | "我想调用一个工具，请帮我执行" | 专家说"帮我看一下电源灯" |
| `"end_turn"` | "我说完了" | 专家说"问题解决了" |

只有这两种情况。你的程序只需要根据这个字段决定：**继续？还是结束？**

##### `stop_reason` 和 `content[].type` 里都有 `tool_use`，重复了吗？

看完整信息流那张图，你可能注意到 `tool_use` 出现了两次：

```python
response.stop_reason = "tool_use"                    # ← 这里一次
response.content = [{ "type": "tool_use", ... }]     # ← 这里又一次
```

它们不是重复，而是给**不同的循环**用的：

- **`stop_reason`** → 给你的 **`while` 循环**用，回答："还要不要继续？"
- **`content[].type`** → 给你的 **`for` 循环**用，回答："这个 block 是什么？要怎么处理？"

为什么需要分开？因为 `content` 是一个**列表**，一次回复里可以同时有多种 block：

```python
# LLM 的一次回复可能同时包含文字和多个工具调用：
response.content = [
    TextBlock("让我来查一下..."),       # type = "text"      ← 文字，跳过
    ToolUseBlock(bash, "ls"),           # type = "tool_use"  ← 要执行
    ToolUseBlock(bash, "pwd"),          # type = "tool_use"  ← 也要执行
]
response.stop_reason = "tool_use"       # 告诉 while 循环：别停，有工具要执行
```

这时候：
- `stop_reason = "tool_use"` 让 `while` 循环知道不该 `return`
- `for block in content` 遍历时，靠 `block.type` 区分哪些是要执行的工具（`"tool_use"`）、哪些是纯文字（`"text"`，跳过）

如果没有 `stop_reason`，你就得自己遍历 content 去找有没有 tool_use block。`stop_reason` 相当于 API 帮你做了这个判断，让 while 循环的代码更简洁。

#### 第 4 部分：循环 —— 把你自动化

如果没有循环，你需要手动完成每一步：

```
1. 把对话发给 LLM        （手动）
2. 看 LLM 想调什么工具     （手动）
3. 执行命令                （手动）
4. 把结果塞回对话           （手动）
5. 再把对话发给 LLM        （手动）
6. ...                     （你就是人肉循环）
```

`while` 循环做的事情，就是**把上面的"手动"全部自动化**：

```python
def agent_loop(messages):
    while True:
        # 1. 把对话交给 LLM
        response = client.messages.create(
            model=MODEL, system=SYSTEM,
            messages=messages, tools=TOOLS, max_tokens=8000,
        )

        # 2. 把 LLM 的回复追加到对话记录
        messages.append({"role": "assistant", "content": response.content})

        # 3. LLM 不想调工具了？结束！
        if response.stop_reason != "tool_use":
            return

        # 4. LLM 想调工具 → 执行每个工具，收集结果
        results = []
        for block in response.content:
            if block.type == "tool_use":
                output = run_bash(block.input["command"])
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })

        # 5. 把工具结果作为 user 消息塞回对话
        messages.append({"role": "user", "content": results})
        # → 回到 while True 的顶部，重复
```

#### 完整流程图解

用一个具体例子走一遍。假设用户说："帮我看看当前目录有什么 Python 文件"。

```
  ┌─ 轮次 1 ─────────────────────────────────────────────────┐
  │                                                           │
  │  messages = [                                             │
  │    { role: "user", content: "帮我看看当前目录..." }        │
  │  ]                                                        │
  │                                                           │
  │  → 发给 LLM                                               │
  │  ← LLM 回复: "我来调用 bash: ls *.py"                     │
  │     stop_reason = "tool_use"  ← 还没完！                  │
  │                                                           │
  │  messages = [                                             │
  │    { role: "user",      content: "帮我看看当前目录..." },  │
  │    { role: "assistant", content: [调用 bash: ls *.py] },  │
  │  ]                                                        │
  │                                                           │
  │  执行 bash("ls *.py") → 输出: "s01_agent_loop.py\n..."   │
  │                                                           │
  │  messages = [                                             │
  │    { role: "user",      content: "帮我看看当前目录..." },  │
  │    { role: "assistant", content: [调用 bash: ls *.py] },  │
  │    { role: "user",      content: [tool_result: "s01..."] }│
  │  ]                                                        │
  └───────────────────────────────────────────────────────────┘

  ┌─ 轮次 2 ─────────────────────────────────────────────────┐
  │                                                           │
  │  → 发给 LLM（此时 messages 有 3 条）                      │
  │  ← LLM 回复: "当前目录有以下 Python 文件: s01_..."        │
  │     stop_reason = "end_turn"  ← 说完了！                  │
  │                                                           │
  │  messages = [                                             │
  │    { role: "user",      content: "帮我看看当前目录..." },  │
  │    { role: "assistant", content: [调用 bash: ls *.py] },  │
  │    { role: "user",      content: [tool_result: "s01..."] }│
  │    { role: "assistant", content: "当前目录有以下..." },    │
  │  ]                                                        │
  │                                                           │
  │  → return，循环结束                                        │
  └───────────────────────────────────────────────────────────┘
```

### 其余代码：外围部分

核心就是上面 `agent_loop` 函数。文件里剩下的代码做的是外围工作：

| 代码段 | 做什么 | 为什么需要 |
|---|---|---|
| `run_bash()` | 执行 shell 命令 | 工具的具体实现，带危险命令拦截和超时 |
| `SYSTEM = "..."` | 系统提示词 | 告诉 LLM 它的角色和工作目录 |
| `client = Anthropic(...)` | 创建 API 客户端 | 用来调 Claude API |
| `if __name__ == "__main__"` | 交互式 REPL | 让你在终端里反复输入问题 |

### 自己动手试试

```sh
python agents/s01_agent_loop.py
```

| 试这个 prompt | 观察什么 | 详细追踪 |
|---|---|---|
| `What python files are in this directory?` | LLM 调了几次工具？（1 次 find，2 轮 LLM 调用） | [s01_example1.md](../../agents/s01_example1.md) |
| `Create hello.py that prints hello, then run it` | LLM 调了几次工具？（2 次：先写文件再运行，3 轮 LLM 调用） | [s01_example2.md](../../agents/s01_example2.md) |
| `What is 2+2?` | LLM 调工具了吗？（不调，直接回答，只有 1 轮） | [s01_example3.md](../../agents/s01_example3.md) |

第 3 个例子很重要：**LLM 自己判断要不要调工具**。它觉得不需要就直接回答（`stop_reason = "end_turn"`），不会强制调用。三个例子的对比见 [s01_example3.md](../../agents/s01_example3.md#总结三个例子的对比) 末尾的总结表格。

### 这一课的关键收获

1. **Agent = LLM + 工具 + 循环**。少任何一个都不算 Agent。
2. **LLM 不执行任何操作**。它只"请求"，你的程序负责"执行"。
3. **循环的退出条件**只有一个：`stop_reason != "tool_use"`。
4. **messages 列表是累积的**——每一轮的对话都追加进去，LLM 能"看到"之前所有的交互。
5. 后面 11 课的**所有机制**都是在这个循环上叠加的。循环本身永远不变。

---
