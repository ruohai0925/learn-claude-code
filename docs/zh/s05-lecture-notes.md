# s05: Skill Loading —— 按需加载领域知识

> **前置知识：** 请先完成 [s01](s01-lecture-notes.md)、[s02](s02-lecture-notes.md)、[s03](s03-lecture-notes.md)、[s04](s04-lecture-notes.md)。本讲义不重复已讲过的概念，只聚焦 s05 的新内容。

---

## 先搞清几个概念

在进入 s05 之前，有几个术语需要先理清。它们在 AI Agent 生态里频繁出现，但经常被混用：

### Skill（技能）

一段**领域知识文本**，告诉 LLM "怎么做某类事情"。比如：

- "PDF 技能"：教 LLM 用 PyMuPDF 读 PDF、用 pandoc 生成 PDF、怎么合并拆分
- "代码审查技能"：给 LLM 一份安全/性能/可维护性的 checklist

Skill 本身**不是代码，不是工具，不是 API**。它只是一段 Markdown 文本，塞进 messages 后，LLM 照着里面的指导去行动（调用 bash、write_file 等已有工具）。你可以把 skill 理解为**给 LLM 看的操作手册**。

### Tool（工具）

LLM 可以调用的**一个具体功能**。比如 `bash`、`read_file`、`load_skill`。Tool 有明确的 input schema 和 handler 函数——LLM 传参数，harness 执行，返回结果。

Skill 和 tool 的关系：`load_skill` 是一个 **tool**，它的作用是把某个 **skill** 的内容加载到 messages 里。Skill 是被加载的知识，tool 是加载知识的动作。

### MCP（Model Context Protocol）

一种**标准化协议**，让外部服务把自己的能力（工具、数据、prompt 模板）暴露给 LLM 使用。你写一个 MCP server，Claude 就能调用你定义的函数——比如查天气、查数据库、操作 Jira ticket。

MCP 和 skill 是不同层面的东西：

用一个具体场景来感受区别——假设用户说"帮我查一下北京今天的天气"：

**Skill 的做法（给知识）：** LLM 收到一个 "天气查询 skill"，里面写着："用 `curl` 调用 weatherapi.com 的 API，参数是 `q=Beijing`，key 填你的 API key……" LLM 读完这段文字后，自己用 `bash` 工具执行 `curl https://api.weatherapi.com/...`，拿到结果，再解析返回给用户。**每一步都是 LLM 自己在操作**——skill 只是告诉它该怎么操作。

**MCP 的做法（给能力）：** 有一个 weather MCP server 正在运行，它暴露了一个工具叫 `get_weather(city)`。LLM 只需要调用 `get_weather("Beijing")`，MCP server 在后台帮你查 API、解析 JSON，直接返回 "北京：25°C，晴"。**LLM 不需要知道 API 怎么调、JSON 怎么解析**——MCP server 全包了。

| 维度 | Skill | MCP |
|---|---|---|
| 本质 | 一段文本（操作手册） | 一个运行中的服务（API） |
| 给 LLM 的是 | 知识（"怎么做"） | 能力（"可以调用什么"） |
| 执行者 | LLM 自己用已有工具去做 | MCP server 执行，返回结果 |
| 上面的例子 | LLM 读教程 → 自己 `bash curl` → 自己解析 JSON | LLM 调 `get_weather("Beijing")` → 直接拿到结果 |

在 s05 里，`mcp-builder` 本身是一个 **skill**——它教 LLM "如何构建 MCP server"。LLM 读了这个 skill 之后，用 `bash`/`write_file` 等工具去创建一个 MCP server 的代码。Skill 提供知识，工具提供执行能力，MCP 是被创建的产物。

---

## 这一课要回答的问题

> 我想让 Agent 具备 PDF 处理、代码审查、MCP 构建等多种领域知识。如果全部塞进 system prompt，10 个 skill × 2000 token = 20,000 token——每次 API 调用都要付这个成本，哪怕用户只需要其中 1 个。怎么办？

**答案：分两层。system prompt 里只放"目录"（skill 名字 + 一句话描述），完整内容等 LLM 需要时再通过工具加载。**

---

## 核心类比：图书馆的目录卡片

你不会把图书馆所有书都摊在桌上。你会：

1. **先看目录卡片**——知道有哪些书、每本书大概讲什么（几秒钟）
2. **找到需要的那本，再去书架取**——翻开看完整内容（几分钟）

对应到 s05：

| 图书馆 | s05 |
|---|---|
| 目录卡片 | system prompt 里的 skill 描述（Layer 1） |
| 从书架取书 | `load_skill("pdf")` 返回完整 body（Layer 2） |
| 没看的书留在书架 | 没加载的 skill 不消耗 token |

---

## s04 → s05：到底变了什么？

| 组件 | s04 | s05 | 变了吗？ |
|---|---|---|---|
| `while True` 循环结构 | 有 | 一样 | 不变 |
| 工具 | 5 个（base + task） | 5 个（base + **load_skill**） | **变了** |
| System prompt | 静态字符串 | **动态生成**（包含 skill 列表） | **变了** |
| SkillLoader | 无 | **新增**（扫描 skills/ 目录） | **新增** |
| Subagent | `run_subagent()` | **去掉了**（s05 聚焦于知识加载） | 去掉 |
| 循环代码 | 有子 Agent 分支 | **无特殊分支**（load_skill 走统一派发） | **简化** |

**最重要的变化：** s04 的 `task` 工具需要在循环里做特殊处理（if/else 分支调 `run_subagent()`），但 s05 的 `load_skill` **不需要**——它和 `bash`、`read_file` 一样，走统一的 `TOOL_HANDLERS` 派发表。循环代码完全不知道 skill 的存在。

---

## 概念 1：两层注入（Two-Layer Injection）

这是 s05 唯一的新概念，但非常重要。

### Layer 1：system prompt 里的 skill 描述

```python
SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use load_skill to access specialized knowledge before tackling unfamiliar topics.

Skills available:
  - pdf: Process PDF files - extract text, create PDFs, merge documents.
  - code-review: Perform thorough code reviews with security, performance analysis.
  - agent-builder: Design and build AI agents for any domain.
  - mcp-builder: Build MCP servers that give Claude new capabilities."""
```

**这段文字每次 API 调用都会发送。** 4 个 skill 的描述加起来约 400 token——可以接受。如果是 10 个 skill 也只有 ~1000 token。

LLM 从这段文字里学到三件事：
1. 有 4 个 skill 可用
2. 每个 skill 是做什么的（一句话描述）
3. 用 `load_skill` 工具可以加载完整内容

**注意 system prompt 是动态生成的。** `SKILL_LOADER.get_descriptions()` 在程序启动时扫描 `skills/` 目录，自动生成描述列表。如果你加了一个新的 `skills/testing/SKILL.md`，重启程序就会自动出现在 system prompt 里。

### Layer 2：tool_result 里的完整 body

```python
# 当 LLM 调用 load_skill("pdf") 时：
SKILL_LOADER.get_content("pdf")
# 返回：
# <skill name="pdf">
# # PDF Processing Skill
# You now have expertise in PDF manipulation...
# ## Reading PDFs
# ...（完整的 Markdown 教程，~2000 token）
# </skill>
```

这段内容作为 `tool_result` 塞进 messages——**不在 system prompt 里**。只有 LLM 主动调用 `load_skill` 时才加载。

### 两层对比

| 维度 | Layer 1（system prompt） | Layer 2（tool_result） |
|---|---|---|
| 内容 | skill 名字 + 一句话描述 | 完整的 Markdown body |
| 大小 | ~100 token/skill | ~2000 token/skill |
| 何时发送 | **每次** API 调用 | **按需**，LLM 请求时 |
| 谁决定加载 | 总是发送 | **LLM 自己决定** |
| 对应代码 | `get_descriptions()` | `get_content(name)` |

**为什么不全用 Layer 2？** 如果 system prompt 里不提 skill 的存在，LLM 根本不知道可以 `load_skill`——它不会调用一个它不知道的工具。Layer 1 是"告诉 LLM 有这个选项"，Layer 2 是"给它具体内容"。两层缺一不可。

---

## 概念 2：SKILL.md 的文件格式

```markdown
---
name: pdf
description: Process PDF files - extract text, create PDFs, merge documents.
---

# PDF Processing Skill

You now have expertise in PDF manipulation. Follow these workflows:

## Reading PDFs
...（完整教程）
```

`---` 分隔的是 **YAML frontmatter**——一种在 Markdown 文件头部嵌入结构化元数据的约定（Jekyll、Hugo 等静态站点生成器也用这个格式）。

`SkillLoader._parse_frontmatter()` 用正则把文件拆成两部分：

```python
match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
# match.group(1) → YAML 部分 → yaml.safe_load → meta dict
# match.group(2) → Markdown body → skill body
```

- `meta` 里的 `name` 和 `description` → 给 Layer 1 用
- `body`（frontmatter 之后的全部内容）→ 给 Layer 2 用

---

## 概念 3：load_skill 是一个"普通工具"

```python
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_LOADER.get_content(kw["name"]),  # ← 就这一行
}
```

`load_skill` 在派发表里和 `bash`、`read_file` 地位平等。循环代码里没有 `if block.name == "load_skill"` 的特殊分支——它走的是统一的 `handler(**block.input)` 路径。

**对比 s04 的 `task` 工具：** s04 的循环里有一个显式的 `if block.name == "task": output = run_subagent(...)` 分支，因为 `task` 不在 `TOOL_HANDLERS` 里。s05 不需要这种特殊处理——`load_skill` 就是一个返回字符串的函数。

**这意味着什么？** 添加新的"知识注入"类工具非常简单：写一个 SKILL.md → 放进 skills/ 目录 → 重启程序。不需要改循环代码、不需要改工具派发逻辑、不需要改 system prompt（它会自动更新）。**这是一种"非侵入式"的扩展机制。**

**展开想想：什么是"非侵入式"，什么是"侵入式"？**

回顾 s01-s05，我们其实已经见过两种模式了：

**非侵入式——加东西不用改循环代码：**

| 例子 | 怎么加 | 为什么不用改循环 |
|---|---|---|
| **s02 加新工具**（比如加一个 `grep` 工具） | 在 `TOOL_HANDLERS` 里加一行，`TOOLS` 里加一个定义 | 循环只认 `handler(**block.input)`，不关心具体是哪个工具 |
| **s05 加新 skill**（比如加一个 `testing` skill） | 在 `skills/` 下新建 `testing/SKILL.md` | SkillLoader 动态扫描目录，system prompt 自动更新，`get_content` 按 name 查字典 |

这两个的共同点是：有一个**间接层**（派发表 / 目录扫描）把"具体有哪些"和"怎么执行"解耦了。循环代码只和间接层打交道，不和具体的工具/skill 耦合。

**侵入式——加东西必须改循环代码：**

| 例子 | 改了循环的什么 | 为什么不得不改 |
|---|---|---|
| **s03 的 todo nag** | 循环里加了 `rounds_since_todo` 计数器，每轮检查是否需要注入提醒 | nag 逻辑和工具派发无关，它是"循环层面"的行为——在 messages 里插入额外内容 |
| **s04 的 task 工具** | 循环里加了 `if block.name == "task": run_subagent(...)` 分支 | `task` 不是一个"调用函数返回字符串"的普通工具——它要启动一个子循环，有自己的 messages |

侵入式不一定是坏事。s04 的 `task` 之所以需要特殊分支，是因为它**本质上做的事和普通工具不同**——普通工具是"输入→输出"的纯函数，`task` 是"启动一个新的 agent 循环"。这种质的差异不是靠派发表能抹平的。强行把它塞进 `TOOL_HANDLERS` 只会让代码更难理解。

**判断标准：** 如果新功能的行为模式和已有工具一样（输入参数 → 执行 → 返回字符串），就用非侵入式（加进派发表）。如果新功能需要改变循环本身的行为（插入 messages、启动子循环、改变控制流），就不得不侵入式。

**一个有趣的对比：** s05 的 `load_skill` 和 s02 的 `read_file` 在循环里的地位完全一样——都是普通工具。但从"功能意图"看，它们非常不同：`read_file` 读的是项目文件（变化的数据），`load_skill` 读的是预定义的知识模板（相对固定的指导）。**循环不关心你的意图，只关心你的接口。** 只要你能实现 `(input) → str` 这个接口，你就能享受非侵入式的好处。

---

## 概念 4：LLM 自己决定何时加载

system prompt 里有一句关键指令：

```
Use load_skill to access specialized knowledge before tackling unfamiliar topics.
```

这是一个**软约束**（参见 s03/s04 讲义里对硬约束 vs 软约束的讨论）。LLM 可能会：

- **主动加载**：用户说 "review this code"，LLM 自己决定先 `load_skill("code-review")` 再开始
- **被提示加载**：用户说 "load the code-review skill first"，LLM 照做
- **跳过加载**：用户问 "what skills are available?"，LLM 直接从 system prompt 里读取描述列表，不需要调 `load_skill`
- **无视指令**：用户说 "review this code"，但 LLM 觉得自己已经会了，直接 review 不加载 skill

前三种都是合理的行为。第四种是软约束的固有风险——LLM 可能认为自己不需要额外知识就能完成任务。对于简单任务这没问题，但对于需要严格遵循特定流程的任务（比如安全审计 checklist），跳过 skill 可能会遗漏步骤。

---

## 概念 5：token 经济学

假设有 10 个 skill，每个完整 body 约 2000 token：

| 方案 | 每次 API 调用的 token 开销 |
|---|---|
| 全部塞进 system prompt | 10 × 2000 = **20,000 token**（固定） |
| 两层注入，用户用 1 个 skill | 10 × 100（Layer 1） + 1 × 2000（Layer 2） = **3,000 token** |
| 两层注入，用户不用任何 skill | 10 × 100（Layer 1） = **1,000 token** |

**节省了 85%-95% 的 token。** 而且随着 skill 数量增加，节省比例更高——20 个 skill 时，全塞 system prompt 要 40,000 token，两层注入只需要 2,000 + 按需。

这就是为什么 Claude Code 自己也用类似的机制（参见 Claude Code 的 skill 系统）：skill 的 metadata 始终可见，body 按需加载。

---

## verbose 输出里看什么

s05 的 verbose 打印重点展示两层注入的效果：

### 启动时

```
──────────── SkillLoader 扫描结果 ────────────────
skills_dir = /home/.../skills
扫描到 4 个 skill:
  pdf: Process PDF files - extract text, create PDFs, merge documents....
    Layer 1 (system prompt): ~80 字符描述
    Layer 2 (tool_result):   ~2500 字符完整 body
  code-review: Perform thorough code reviews with security...
    Layer 1 (system prompt): ~170 字符描述
    Layer 2 (tool_result):   ~4200 字符完整 body
  ...

──────────── SYSTEM prompt (包含 Layer 1) ────────────────
You are a coding agent at /home/.../learn-claude-code.
Use load_skill to access specialized knowledge before tackling unfamiliar topics.

Skills available:
  - pdf: Process PDF files...
  - code-review: Perform thorough code reviews...
  - agent-builder: Design and build AI agents...
  - mcp-builder: Build MCP servers...
```

关键看：每个 skill 的 Layer 1 vs Layer 2 大小差距（~100 字符 vs ~2500-4200 字符）。

### 运行时（当 LLM 调用 load_skill）

```
──────────── 轮次 1: 执行工具 ────────────────
加载 skill: "code-review"
返回内容 (4200 字符):
<skill name="code-review">
# Code Review Skill

You now have expertise in conducting comprehensive code reviews...
</skill>

→ tool_result 已塞回 messages，继续下一轮...
```

关键看：`load_skill` 返回的内容被 `<skill>` 标签包裹，作为 `tool_result` 塞进 messages。

---

## 和 s04 的对比：两种不同的"按需"

| 维度 | s04（子 Agent） | s05（skill loading） |
|---|---|---|
| 解决什么问题 | 探索任务污染父 Agent 上下文 | 领域知识膨胀 system prompt |
| "按需"的含义 | 按需启动新循环 | 按需加载文本 |
| 复杂度 | 高（独立 messages、独立循环） | 低（只是一个返回字符串的工具） |
| 对循环的侵入 | 需要特殊 if/else 分支 | 零侵入，走统一派发表 |
| 加载后的效果 | 子 Agent 做完事，返回摘要 | skill body 留在 messages 里，LLM 照着做 |

两者可以组合使用：父 Agent 加载一个 skill，然后派一个子 Agent 按照 skill 的指导去执行。

---

## 自己动手试试

```sh
python agents/s05_skill_loading.py
```

| 试这个 prompt | 观察什么 | 详细追踪 |
|---|---|---|
| `What skills are available?` | LLM 是否调用 load_skill？还是直接从 system prompt 读取？ | [example1.md](../../examples/s05/example1.md) |
| `Load the agent-builder skill and follow its instructions` | load_skill 返回了多少字符？LLM 如何根据 skill 内容行动？ | [example2.md](../../examples/s05/example2.md) |
| `I need to do a code review -- load the relevant skill first` | LLM 能否从描述中选对 skill？加载后的行为有什么变化？ | [example3.md](../../examples/s05/example3.md) |
| `Build an MCP server using the mcp-builder skill` | **同一个 prompt，continue vs restart 结果天壤之别**——context 如何影响 LLM 行为 | [example4.md](../../examples/s05/example4.md) |

---

## 这一课的关键收获

1. **两层注入是 token 经济学的最优解。** Layer 1（目录）始终存在但很便宜，Layer 2（正文）按需加载。既保证 LLM 知道"有什么可用"，又避免为用不到的知识付费。

2. **load_skill 是一个"普通工具"，不需要特殊处理。** 和 `bash`、`read_file` 地位平等，走统一的派发表。添加新 skill 不需要改任何代码——放个 SKILL.md 到 skills/ 目录就行。

3. **LLM 自己决定何时加载。** system prompt 里的 `"Use load_skill to access specialized knowledge"` 是软约束，LLM 可能主动加载、被提示加载、或跳过加载。这是一个"信任 LLM 判断力"的设计。

4. **skill body 作为 tool_result 留在 messages 里。** 和 s04 的子 Agent 不同（sub_messages 丢弃），load_skill 返回的内容会**持久存在于 messages 中**——后续的 LLM 调用都能看到它。这是优点（LLM 可以反复参考），也是潜在的缺点（如果 skill body 很大，会膨胀 messages）。

5. **这就是 Claude Code 里 Skill tool 的原理。** 当你在 Claude Code 里看到 `"Loading skill: pdf"`，背后就是这个模式：两层注入 + 按需加载。
