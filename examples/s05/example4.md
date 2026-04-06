# s05 实际运行追踪：构建 MCP server（continue vs restart 的巨大差异）

> prompt: `Build an MCP server using the mcp-builder skill`
>
> 这个 prompt 被运行了**两次**——一次接着 example1-3 的会话继续（continue），一次在全新会话里（restart）。结果天壤之别。
>
> **重点观察：** 同一个 prompt，不同的 messages 上下文，LLM 的行为完全不同。这是 s05 最有教学价值的发现——**context 影响行为**。

---

## 实验设计

| | continue 模式 | restart 模式 |
|---|---|---|
| 会话状态 | 接续 example1/2/3 | 全新启动 |
| 输入前 messages 条数 | 11 条 | 1 条 |
| 已加载的 skill body | agent-builder (4176 字符) + code-review (4101 字符) | 无 |
| messages 总大小（估算） | ~15,000+ 字符 | ~50 字符 |

---

## Continue 模式：2 轮，简短回答

**终端输出（关键部分）：**

```
────────────────── 轮次 1 ──────────────────
messages = [
  [0] user: "What skills are available?"
  [1] assistant/text: "Based on my system configuration, here are the **4 skills**..."
  [2] user: "Load the agent-builder skill and follow its instructions"
  [3] assistant/tool_use: load_skill({"name": "agent-builder"})
  [4] user/tool_result: "<skill name="agent-builder">..."      ← 4176 字符，无关但还在
  [5] assistant/text: "The **agent-builder** skill is now loaded!..."
  [6] user: "I need to do a code review -- load the relevant skill first"
  [7] assistant/tool_use: load_skill({"name": "code-review"})
  [8] user/tool_result: "<skill name="code-review">..."        ← 4101 字符，无关但还在
  [9] assistant/text: "The **code-review** skill is loaded!..."
  [10] user: "Build an MCP server using the mcp-builder skill"    ← 第 11 条！
]
```

LLM 加载了 mcp-builder skill，然后在第 2 轮给出回答：

```
────────────────── 最终回答 ──────────────────
The **mcp-builder** skill is loaded! I'm ready to build an MCP server for you.

## Ready to Build Your MCP Server

MCP servers expose three types of capabilities to Claude:
| Type | Description | Example |
|------|-------------|---------|
| Tools | Functions Claude can call | Search, send email, query DB |
| Resources | Data Claude can read | Files, configs, database records |
| Prompts | Pre-built prompt templates | Reusable task templates |

### To get started, tell me:
1. What should the server do?
2. Language preference?
3. Any specific tools/actions you need?

**What would you like your MCP server to do?**
```

**LLM 的行为：只给了一个简短摘要 + 问用户"你想做什么"。没有动手建。**

完整输出参见 [example4-continue.html](example4-continue.html)。

---

## Restart 模式：17 轮，完整构建

**同样的 prompt，全新会话：**

```
────────────────── 轮次 1 ──────────────────
messages = [
  [0] user: "Build an MCP server using the mcp-builder skill"    ← 只有这 1 条
]
```

LLM 同样先加载 mcp-builder skill，但第 2 轮开始**直接动手**：

```
轮次 2:  TextBlock: "I've loaded the MCP builder skill. Now let me build a practical,
         well-structured MCP server for you. I'll create a File & Utilities server..."
         ToolUseBlock: bash("mkdir -p mcp-server && echo 'Directory ready'")

轮次 3:  bash("python3 -m venv venv && source venv/bin/activate && pip install mcp httpx")
         → 报错: /bin/sh: 1: source: not found

轮次 4:  bash("python3 -m venv venv && venv/bin/pip install mcp httpx")  ← 从错误中恢复

轮次 5:  write_file("server.py", 7191 bytes)  ← 写了一个完整的 MCP server！

轮次 6:  write_file("README.md", 2190 bytes)  ← 还写了文档

轮次 7-8:  bash 测试 → 报错 (server.tool() API 不对)

轮次 9-10: bash 调试 → 发现 MCP SDK 用的是 FastMCP

轮次 11: write_file("server.py", 6859 bytes)  ← 用 FastMCP 重写

轮次 12: bash 验证 → "Module loaded OK, FastMCP instance: file-utilities-server"

轮次 13-14: bash 测试工具列表 → 又报错 → 继续调试

轮次 14: 终于找到正确的 API → "Registered 9 tools"

轮次 15: bash 运行所有 9 个工具的功能测试 → 全部通过

轮次 16: bash("find mcp-server ...") 查看项目结构

轮次 17: end_turn → 最终报告
```

**最终产出：**

```
## MCP Server Built — file-utilities-server

### Project Structure
mcp-server/
├── server.py      ← All 9 tools defined here
├── README.md      ← Setup & usage docs
└── venv/          ← Python virtual environment

### 9 Tools Registered
| Tool | What it does |
|------|-------------|
| read_file | Read any text file from disk |
| write_file | Write/overwrite a file |
| list_directory | Directory listing with sizes |
| file_info | Metadata + MD5 checksum |
| search_in_files | Grep-style keyword search |
| word_count | Count chars/words/lines/paragraphs |
| json_format | Pretty-print JSON |
| system_info | OS, Python version, hostname |
| calculate | Safe math expression evaluator |

### Register with Claude Desktop
Add to ~/.claude/mcp.json:
{ "mcpServers": { "file-utilities": { "command": "venv/bin/python3", "args": ["server.py"] } } }
```

完整输出参见 [example4-restart.html](example4-restart.html)。

---

## 对比分析：同一个 prompt，天壤之别

| 维度 | Continue | Restart |
|---|---|---|
| 输入前 messages | 11 条（~15,000+ 字符） | 1 条（~50 字符） |
| 已加载的无关 skill | 2 个（agent-builder + code-review） | 0 |
| 总轮次 | 2 | **17** |
| 工具调用次数 | 1（load_skill） | **16**（1 load_skill + 5 bash + 2 write_file + 8 bash） |
| LLM 是否动手建 | **没有**，只问"你想做什么" | **直接建了**，还写了 9 个工具（见下文分析） |
| 错误和恢复 | 无 | 4 次错误 + 4 次恢复 |
| 最终产出 | 一段摘要 | **完整项目**（server.py + README.md + venv） |

---

## 两个值得深思的问题

### 问题 1：LLM 怎么知道要建一个 "File & Utilities" server，还造了 9 个工具？

用户只说了 `"Build an MCP server"`，没说建什么样的。LLM 自己决定了：
- 主题是 "File & Utilities"
- 包含 `read_file`、`write_file`、`list_directory`、`search_in_files`、`json_format`、`calculate` 等 9 个工具

这背后的过程是：

**第一层：skill body 给了模板和方向。** mcp-builder skill 里有一段 "Basic Server Template"，示例是一个 `hello` 工具和一个 `add_numbers` 工具。skill 还提到了 "External API Integration"（天气查询）和 "Database Access"（SQLite）。这些例子暗示了 MCP server 的典型用途是"给 Claude 提供实用工具"。

**第二层：LLM 从训练数据中"编"了一个合理的主题。** "File & Utilities" 不是 skill body 里写的——LLM 自己挑了这个方向。为什么选文件操作？因为训练数据里大量的 MCP server 示例、CLI 工具、开发者工具都和文件操作相关。在 `"Build an MCP server"` 这个模糊指令下，"文件操作工具集"是**概率最高的实例化方向**。

**如果换一种 prompt 呢？** 如果用户说 `"Build an MCP server for weather data"`，LLM 大概率会建一个天气 API server，而不是文件工具集。prompt 的具体程度决定了 LLM 的发挥空间——越模糊，LLM 越依赖训练数据里的高频模式；越具体，LLM 越忠于用户意图。

所以答案是：**一半来自 skill body 的引导（"MCP server 长什么样"），一半来自概率（"建什么类型的 server"）。**

### 问题 2：这 9 个 MCP 工具和我们 s05 自己的 5 个工具有什么区别？

对比一下：

| | s05 harness 的工具 | MCP server 的工具 |
|---|---|---|
| 定义位置 | `s05_skill_loading.py` 里的 `TOOLS` | `mcp-server/server.py` 里的 `@mcp.tool()` |
| 谁调用它们 | **当前这个 Agent**（s05） | **未来的其他 Claude 实例**（比如 Claude Desktop） |
| 运行环境 | 在 s05 进程内直接执行 | 在 MCP server 进程里执行，通过 stdio 通信 |
| 给谁用 | s05 自己 | 任何支持 MCP 的 client |

**关键区别：s05 的工具是"自己用的"，MCP server 的工具是"暴露给别人用的"。**

具体来说：s05 的 `read_file` 是 LLM 在当前对话里调用的——LLM 说 `read_file({"path": "foo.py"})`，harness 直接执行 `Path("foo.py").read_text()` 返回结果。一切发生在同一个 Python 进程里。

MCP server 的 `read_file` 是**另一个独立进程**暴露的——Claude Desktop 通过 JSON-RPC 协议发消息给 `server.py`，`server.py` 执行后把结果发回去。它们是两个进程之间的通信。

虽然功能名字相似（都叫 `read_file`），但用途完全不同：

```
s05 的 read_file:
  用户 → s05 Agent → LLM 说 "read_file" → harness 执行 → 返回给 LLM

MCP 的 read_file:
  用户 → Claude Desktop → Claude 说 "read_file" → MCP server 执行 → 返回给 Claude
```

打个比方：s05 的工具是**厨师手里的刀**（自己用来切菜），MCP server 的工具是**厨具店里卖的刀**（给别的厨师用）。LLM 在 restart 模式下做的事情，相当于"用自己手里的刀（bash、write_file）造了一套新刀（MCP tools），然后打包放进厨具店（mcp.json）供别人购买使用"。

### 揭开神秘面纱：MCP server 到底是什么？

说了这么多，MCP server 最终产出的其实就是**一个 Python 文件**（`server.py`，221 行）。核心结构极其简单：

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("file-utilities-server")    # 创建 server 实例

@mcp.tool()                                # 用装饰器注册一个工具
def read_file(path: str) -> str:
    """Read the contents of a file from disk."""   # ← docstring 就是工具描述
    return Path(path).read_text()

@mcp.tool()                                # 再注册一个
def calculate(expression: str) -> str:
    """Safely evaluate a mathematical expression."""
    return str(eval(expression, ...))

# ... 共 9 个 @mcp.tool() 函数 ...

if __name__ == "__main__":
    mcp.run(transport="stdio")             # 启动 server，通过 stdin/stdout 通信
```

**就这样。** 没有 HTTP 服务器，没有 REST API，没有数据库。MCP server 就是一个 Python 脚本，通过 stdin/stdout 和 Claude 通信（JSON-RPC 协议）。`FastMCP` 框架帮你处理了协议细节——你只需要写普通的 Python 函数，加上 `@mcp.tool()` 装饰器。

**函数的 docstring 自动变成工具描述。** Claude 看到的不是源代码，而是从 docstring 提取的工具名 + 描述 + 参数 schema（从类型标注自动生成）。这和 s05 里 `TOOLS` 列表手动写 `"description": "Run a shell command."` 是同一个机制，只是 FastMCP 帮你自动化了。

**注册到 Claude Desktop 也只需要一行配置：**

```json
{ "mcpServers": { "file-utilities": { "command": "python3", "args": ["server.py"] } } }
```

告诉 Claude Desktop：启动 `python3 server.py` 这个进程，通过 stdio 和它通信。Claude Desktop 会自动发现里面注册的 9 个工具，就像 s05 的 `TOOLS` 列表一样呈现给 LLM。

**整个 MCP 的"复杂性"其实在协议层（FastMCP 帮你处理了），不在你的代码层。** 你的代码就是一堆普通的 Python 函数。

### 用户调用 MCP server 的完整流程

假设你已经把 `server.py` 注册到了 `mcp.json`，现在你打开 Claude Desktop（或 Claude Code），问了一句 `"帮我看看 main.py 有多少行"`。整个流程是这样的：

```
┌──────────┐      ┌────────────────┐      ┌──────────────────┐
│   用户   │      │  Claude Desktop │      │  MCP server.py   │
│          │      │  (MCP client)   │      │  (独立进程)       │
└────┬─────┘      └───────┬────────┘      └────────┬─────────┘
     │                    │                         │
     │ ① "帮我看看        │                         │
     │  main.py 有多少行"  │                         │
     │ ──────────────────>│                         │
     │                    │                         │
     │              ② Claude Desktop 启动时          │
     │                 已经启动了 server.py 进程，    │
     │                 发现它注册了 9 个工具           │
     │                 （read_file, word_count 等）   │
     │                    │                         │
     │              ③ Claude Desktop 把这 9 个工具    │
     │                 加进 Claude 的 TOOLS 列表      │
     │                 （和 s05 的 TOOLS 一模一样）     │
     │                    │                         │
     │              ④ Claude（LLM）看到 TOOLS 里有    │
     │                 read_file 和 word_count，      │
     │                 决定先 read_file("main.py")    │
     │                    │                         │
     │                    │ ⑤ JSON-RPC via stdin:   │
     │                    │ {"method":"tools/call",  │
     │                    │  "params":{"name":       │
     │                    │  "read_file","arguments":│
     │                    │  {"path":"main.py"}}}    │
     │                    │ ───────────────────────> │
     │                    │                         │
     │                    │      ⑥ server.py 执行    │
     │                    │      Path("main.py")     │
     │                    │      .read_text()        │
     │                    │                         │
     │                    │ ⑦ JSON-RPC via stdout:   │
     │                    │ {"result":"import os\n.."}│
     │                    │ <─────────────────────── │
     │                    │                         │
     │              ⑧ Claude Desktop 把结果作为       │
     │                 tool_result 塞回 messages      │
     │                 （和 s05 的 harness 做的        │
     │                   一模一样！）                  │
     │                    │                         │
     │              ⑨ Claude 继续调                   │
     │                 word_count(text=文件内容)       │
     │                    │ ──────────────────────>  │
     │                    │ <──────────────────────  │
     │                    │                         │
     │              ⑩ Claude: "main.py 有 42 行"     │
     │ <──────────────────│                         │
     │                    │                         │
```

**看出来了吗？⑤-⑧ 就是 s01-s05 里反复看到的 tool_use → 执行 → tool_result 模式。** 唯一的区别是执行工具的不是 harness 自己（同进程），而是一个独立进程（通过 stdin/stdout 通信）。从 LLM 的角度看，**MCP 工具和 s05 的 bash、read_file 没有任何区别**——都是"我发一个 tool_use，等一个 tool_result 回来"。

**那"云端的其他用户"呢？** 上面画的是本地场景——server.py 和 Claude Desktop 在同一台机器上，通过 stdio 通信。如果想让远程用户访问你的 MCP server，需要换一种传输方式：

| 传输方式 | 适用场景 | 配置 |
|---|---|---|
| **stdio**（默认） | 本地使用，server.py 在你自己机器上 | `mcp.run(transport="stdio")` |
| **SSE / HTTP** | 远程使用，server 部署在服务器上 | `mcp.run(transport="sse", host="0.0.0.0", port=8000)` |

用 SSE 模式部署后，远程用户只需要把 `mcp.json` 里的 `"command"` 换成服务器地址就能使用你的 MCP server。**工具定义、调用流程、tool_use/tool_result 协议完全一样**——只是传输层从 stdin/stdout 变成了 HTTP。

---

## 为什么会有这种差异？

### 原因 1：context 重量影响 LLM 的"行动意愿"

Continue 模式下，messages 里已经有 11 条消息、~15,000+ 字符。LLM 在处理这些上下文时，倾向于"保守"——它看到之前的对话模式都是"加载 skill → 简短总结 → 问用户想做什么"，于是延续了这个模式。

Restart 模式下，messages 干净到只有 1 条。LLM 没有之前的对话模式可以模仿，于是按照用户的原始意图 `"Build an MCP server"` 直接执行——**"Build" 意味着动手建**。

### 原因 2：无关 skill body 占据了 context 空间

Continue 模式下，agent-builder（4176 字符）和 code-review（4101 字符）的 body 还在 messages 里——虽然和 MCP 构建完全无关。这 ~8,300 字符不仅占空间，还可能分散 LLM 的注意力。LLM 需要在更多噪声中找到相关信息。

Restart 模式下，加载 mcp-builder skill 后，messages 里只有 skill body + 用户请求。LLM 100% 的注意力都在 MCP 构建上。

### 原因 3：对话历史建立了"角色惯性"

Continue 模式下，前 3 个 example 建立了一个模式：用户问 → LLM 加载 skill → LLM 总结 → LLM 问用户想做什么。这种"问答"模式的惯性让 LLM 认为自己应该继续做"顾问"角色。

Restart 模式下，没有历史模式的束缚。用户说 "Build"，LLM 就 build。

---

## Restart 模式里的精彩细节

### 错误恢复链

```
轮次 3:  source venv/bin/activate → 失败（/bin/sh 不认识 source）
轮次 4:  改用 venv/bin/pip → 成功！

轮次 7:  @server.tool() → 失败（Server 对象没有 tool 方法）
轮次 8:  再试 → 同样失败
轮次 9:  检查 API → 发现是 MCP SDK 版本问题
轮次 10: 发现 FastMCP
轮次 11: 用 FastMCP 重写整个 server.py → 成功！
```

LLM 连续遇到 4 次错误，每次都从 error message 中学习并调整策略。这和 s01/s03/s04 例子里看到的"错误即教学"模式一致——error 信息作为 tool_result 塞回 messages，LLM 在下一轮从中学习。

### skill body 作为"知识基础"

LLM 写的 server.py 代码结构直接来自 mcp-builder skill body 里的模板：

```python
# skill body 里的模板：
server = Server("my-server")
@server.tool()
async def hello(name: str) -> str:
    ...

# LLM 第一版写的代码（轮次 5）：
server = Server("file-utilities-server")
@server.tool()
async def read_file(path: str) -> str:
    ...
```

但 skill body 里的 API 是过时的（`@server.tool()` 不存在于新版 MCP SDK）。LLM 照着 skill 写了第一版，发现不对后通过调试找到了正确的 API（`FastMCP`），然后重写。

**这是 skill 的局限性：skill body 是静态文本，可能过时。** LLM 需要用实际环境来验证 skill 里的信息是否还正确。这恰好是 LLM + tool 组合的优势——它不只是读手册，还能实际运行代码来检验。

**更进一步：LLM 其实可以反过来修改 skill 本身。** 在这个例子里，LLM 发现 mcp-builder skill 里的 `@server.tool()` API 过时了，正确的 API 是 `FastMCP`。它完全有能力执行：

```python
edit_file(
    path="skills/mcp-builder/SKILL.md",
    old_text="@server.tool()\nasync def hello(name: str) -> str:",
    new_text="@mcp.tool()\ndef hello(name: str) -> str:"
)
```

当前 s05 的代码**没有任何机制阻止这么做**——`skills/` 目录在 `WORKDIR` 内，`safe_path` 校验能通过，`edit_file` 工具可以正常修改 SKILL.md 文件。

这意味着一种"自我进化"的可能性：LLM 在实践中发现 skill 过时 → 用工具修正 skill body → 下次重启后，修正后的 skill 自动生效（因为 SkillLoader 每次启动都重新扫描）。**skill 不再是只读的参考资料，而是 LLM 可以维护的活文档。**

但这也带来了风险：
- **LLM 可能改错。** 它以为某个 API 变了，但其实只是自己的用法不对，结果把正确的 skill 改坏了。
- **改动是永久的。** 不像 messages 会随会话结束而消失，文件修改会持久影响所有未来的会话。
- **没有审核机制。** 当前代码里没有 "修改 skill 需要人类确认" 的逻辑。

生产环境中通常会加一层保护：要么把 `skills/` 目录设为只读（`safe_path` 加一条规则拒绝写入），要么加一个审批流程（LLM 提出修改建议，人类确认后才执行）。**完全信任 LLM 自我修改知识库，目前还太早。**

---

## 这个例子的关键收获

1. **Context 影响行为。** 同一个 prompt，干净的 context（restart）让 LLM 直接动手建了一个完整项目；臃肿的 context（continue）让 LLM 只给了一个简短摘要。这不是 bug——是 LLM 从上下文中推断"该做什么"的方式。

2. **skill body 只增不减是一个真实的问题。** 到 continue 模式时，messages 里有 2 个无关的 skill body（~8,300 字符），影响了 LLM 的行为。这就是讲义里说的"潜在缺点"——需要 s06 的 context compact 机制来解决。

3. **对话历史建立"角色惯性"。** 前面 3 个 example 建立的"顾问"模式（问 → 答 → 问）让 LLM 在 continue 模式下延续了这个角色。重启会话打破了这个惯性。

4. **skill 可能过时，LLM 需要实际验证。** mcp-builder skill 里的 API 示例是旧版的，LLM 照着写了第一版后发现不对。但它通过 bash 调试找到了正确的 API，说明 LLM 不是盲目照抄 skill——它会用工具来验证和纠正。

5. **这解释了为什么 Claude Code 要做 context management。** 在生产环境中，context 不能无限增长。Claude Code 用了 context compact（s06）、子 Agent 上下文隔离（s04）等多种机制来保持 context 干净。s05 的 skill loading 虽然简单优雅，但**不含 context 管理**——这是它的设计局限，需要和其他机制配合使用。
