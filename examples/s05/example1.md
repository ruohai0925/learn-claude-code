# s05 实际运行追踪：查看可用 skill（Layer 1 的效果）

> prompt: `What skills are available?`
>
> 结果：1 轮，0 次工具调用。LLM 直接从 system prompt 里读取 skill 列表回答，没有调用 `load_skill`。
>
> **重点观察：** Layer 1 的设计目的——让 LLM "知道有什么可用"——在这里完美体现。LLM 不需要加载任何 skill 的完整内容就能回答这个问题。

---

## 启动

**终端输出：**

```
=== s05 verbose 模式 ===
MODEL  = claude-sonnet-4-6

────────────────── SkillLoader 扫描结果 ──────────────────
skills_dir = /home/yzeng/Codes/learn-claude-code/skills
扫描到 4 个 skill:
  agent-builder: Design and build AI agents for any domain. Use when users:...
    Layer 1 (system prompt): ~515 字符描述
    Layer 2 (tool_result):   ~4138 字符完整 body
  code-review: Perform thorough code reviews with security...
    Layer 1 (system prompt): ~159 字符描述
    Layer 2 (tool_result):   ~4065 字符完整 body
  mcp-builder: Build MCP (Model Context Protocol) servers...
    Layer 1 (system prompt): ~175 字符描述
    Layer 2 (tool_result):   ~4701 字符完整 body
  pdf: Process PDF files - extract text, create PDFs...
    Layer 1 (system prompt): ~131 字符描述
    Layer 2 (tool_result):   ~2416 字符完整 body
```

**解读：** 这是 s05 启动时的 verbose 输出，首次展示了两层注入的**成本对比**：

| skill | Layer 1（system prompt） | Layer 2（tool_result） | 比率 |
|---|---|---|---|
| agent-builder | ~515 字符 | ~4138 字符 | 1:8 |
| code-review | ~159 字符 | ~4065 字符 | 1:25 |
| mcp-builder | ~175 字符 | ~4701 字符 | 1:27 |
| pdf | ~131 字符 | ~2416 字符 | 1:18 |
| **总计** | **~980 字符** | **~15,320 字符** | **1:16** |

Layer 1 总共 ~980 字符（始终在 system prompt 里），Layer 2 总共 ~15,320 字符（按需加载）。如果全塞 system prompt，每次 API 调用多付 ~15,320 字符的成本。两层注入节省了 **94%**。

---

## 用户输入

```
s05 >> What skills are available?
```

这个问题的答案完全在 system prompt 里——skill 名字和描述已经在 Layer 1 里了。LLM 不需要看任何 skill 的 body 就能回答。

---

## 第 1 轮（也是唯一一轮）：LLM 直接回答

**终端输出：**

```
────────────────── 轮次 1 ──────────────────
messages = [
  [0] user: "What skills are available?"
]

→ 调用 client.messages.create(...)

────────────────── 轮次 1: 回复 ──────────────────
response.stop_reason = "end_turn"
response.content = [
  TextBlock: "Based on my system configuration, here are the **4 skills** currently available:

| Skill | Description | Use When |
|--..."
]

────────────────── 轮次 1: 循环结束 ──────────────────
stop_reason = "end_turn" → return!
```

**解读：** `stop_reason = "end_turn"`——LLM 直接回答，**没有调用任何工具**。没有 `load_skill`，没有 `bash`，没有 `read_file`。

这证明了 Layer 1 的设计是成功的：LLM 从 system prompt 里读到了 4 个 skill 的名字和描述，直接用这些信息生成了一张漂亮的表格。

**关键对比：如果没有 Layer 1 会怎样？** 如果 system prompt 里不提 skill 的存在，LLM 根本不知道有 `load_skill` 这个工具可用（虽然 TOOLS 定义里有，但没有 system prompt 的引导，LLM 可能不会想到去用它）。Layer 1 不仅告诉 LLM "有什么 skill"，更重要的是告诉它 "可以用 load_skill 加载它们"。

---

## 最终回答

```
Based on my system configuration, here are the **4 skills** currently available:

| Skill | Description | Use When |
|-------|-------------|----------|
| agent-builder | Design and build AI agents for any domain | ... |
| code-review | Thorough code reviews with security... | ... |
| mcp-builder | Build MCP servers | ... |
| pdf | Process PDF files | ... |

You can ask me to use any of these skills! For example:
- "Review my code for security issues" → uses code-review
- "Build me an AI agent that monitors emails" → uses agent-builder
...
```

**解读：** LLM 不仅列出了 4 个 skill，还**主动给出了使用示例**——这是 LLM 的"热心"行为，不是我们代码控制的。

---

## 这个例子的关键收获

1. **Layer 1 的成本极低但信息足够。** ~980 字符的 skill 描述让 LLM 完整回答了"有什么可用"，不需要加载任何 Layer 2 内容。

2. **LLM 懂得"不该用工具时不用"。** 这个问题的答案已经在 system prompt 里了，LLM 没有多此一举地去 `load_skill` 每一个 skill 来获取详情。这种判断力和 s04 例 1 里"先扫描再精选"是一样的——LLM 知道最高效的做法是什么。

3. **零工具调用 = 最低 API 成本。** 只有 1 次 LLM 调用，没有工具循环。这是所有例子中最便宜的一个。
