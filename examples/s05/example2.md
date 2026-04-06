# s05 实际运行追踪：加载 agent-builder skill（Layer 2 的效果）

> prompt: `Load the agent-builder skill and follow its instructions`
>
> 结果：2 轮，1 次 `load_skill` 调用。LLM 加载了 4176 字符的 skill body，然后根据内容生成了一份结构化的"我能帮你做什么"摘要。
>
> **重点观察：** 这是 Layer 2 的完整流程——`load_skill` 返回 skill body 作为 `tool_result`，LLM 读完后按照 skill 的指导行动。skill body 作为 tool_result **持久留在 messages 里**，后续轮次的 LLM 调用都能看到它。

---

## 上下文：接续 example1

这个 prompt 是在 example1 的同一个会话里输入的。messages 里已经有了 example1 的 2 条消息：

```
messages = [
  [0] user: "What skills are available?"
  [1] assistant/text: "Based on my system configuration, here are the **4 skills** currently available:..."
  [2] user: "Load the agent-builder skill and follow its instructions"    ← 新输入
]
```

---

## 第 1 轮：LLM 调用 load_skill

**终端输出：**

```
────────────────── 轮次 1: 回复 ──────────────────
response.stop_reason = "tool_use"
response.content = [
  ToolUseBlock: name="load_skill", id="toolu_015omWJRTRYRkVTcR343aogG"
    input={"name": "agent-builder"}
]

────────────────── 轮次 1: 执行工具 ──────────────────
加载 skill: "agent-builder"
返回内容 (4176 字符):
<skill name="agent-builder">
# Agent Builder

Build AI agents for any domain - customer service, research, operations...

## The Core Philosophy

> **The model already knows how to be an agent. Your job is to get out of the way.**
...
```

**解读：** 用户明确说了 `Load the agent-builder skill`，LLM 照做——调用 `load_skill("agent-builder")`。

注意返回内容被 `<skill name="agent-builder">` 标签包裹：

```python
return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"
```

在我们的 s05 里，**所有 skill 都用同一个标签格式**——`<skill name="...">...</skill>`，只是 `name` 属性不同。没有为不同 skill 定义不同的标签（比如不会用 `<code-review-skill>` 或 `<pdf-skill>`）。

**为什么用 XML 标签？为什么统一格式？**

先说为什么要包一层标签而不是直接返回裸文本。对比两种返回方式：

```
# 方式 1：裸文本（没有标签）
tool_result: "# Agent Builder\nBuild AI agents for any domain..."

# 方式 2：XML 标签包裹
tool_result: "<skill name=\"agent-builder\">\n# Agent Builder\nBuild AI agents for any domain...\n</skill>"
```

方式 1 的问题：messages 里有很多 tool_result——`read_file` 返回文件内容、`bash` 返回命令输出、`load_skill` 返回 skill body。它们都是字符串，LLM 很难区分"这段文字是一个文件的内容"还是"这段文字是一个 skill 的指导"。两者的**用途完全不同**：文件内容是数据，skill body 是指令。

方式 2 的优势：`<skill>` 标签明确告诉 LLM"这段内容是一个 skill，你应该按照里面的指导行动"。Claude 对 XML 标签特别敏感——这是 Anthropic 官方推荐的 prompt engineering 技巧。标签创建了清晰的语义边界。

**那为什么所有 skill 用统一的 `<skill>` 标签？** 因为 LLM 不需要从标签名来区分不同 skill——`name` 属性已经说明了是哪个 skill。用统一标签的好处是代码简单（一行 f-string），LLM 也只需要学一种格式。如果每个 skill 用不同标签（`<pdf-skill>`、`<review-skill>`），LLM 需要理解多种标签的含义，反而增加了认知负担。

**Claude Code 里也用类似的模式。** 你在 Claude Code 里看到的 skill 加载、system reminder、tool result 等，都用 XML 标签包裹（比如 `<skill-content>`、`<system-reminder>`、`<tool_result>`）。这是一种生态级的约定——不是 s05 独创的。

**4176 字符的 body 作为 tool_result 塞进了 messages。** 这和 s04 的子 Agent 有本质区别——s04 的 sub_messages 会被丢弃，但 load_skill 的返回值会**永久留在 messages 里**。后续所有的 LLM 调用都能看到这 4176 字符。

---

## 第 2 轮：LLM 根据 skill 内容回答

**终端输出：**

```
────────────────── 轮次 2 ──────────────────
messages = [
  [0] user: "What skills are available?"
  [1] assistant/text: "Based on my system configuration, here are the **4 skills**..."
  [2] user: "Load the agent-builder skill and follow its instructions"
  [3] assistant/tool_use: load_skill({"name": "agent-builder"})
  [4] user/tool_result: "<skill name="agent-builder">\n# Agent Builder\n\nBuild AI agents..."
]

→ 调用 client.messages.create(...)

────────────────── 轮次 2: 回复 ──────────────────
response.stop_reason = "end_turn"
response.content = [
  TextBlock: "The **agent-builder** skill is now loaded! Here's what I'm equipped to help you with:
  ...
  ### The 3 Elements of Any Agent:
  1. Capabilities — What can it *do*?
  2. Knowledge — What does it *know*?
  3. Context — What has *happened*?
  ...
  **What's your agent idea?**"
]
```

**解读：** LLM 读完 skill body 后，做了两件事：

1. **摘要提炼**——从 4176 字符的完整 body 中提取了核心概念（三要素、设计思维、反模式等）
2. **引导用户**——根据 skill 里的 `"Tell me about your agent idea"` 指导，主动询问用户想构建什么

这展示了 skill 的工作方式：**skill body 是给 LLM 看的操作手册，LLM 读完后按照手册行动。** LLM 没有把 4176 字符原样输出——它理解了内容，提炼了关键点，然后以自己的方式呈现。

---

## messages 快照

此刻 messages 共 5 条：

| 索引 | role | 内容 | 大小估算 |
|---|---|---|---|
| [0] | user | "What skills are available?" | ~30 字符 |
| [1] | assistant | skill 列表表格 | ~800 字符 |
| [2] | user | "Load the agent-builder skill..." | ~60 字符 |
| [3] | assistant | `load_skill({"name": "agent-builder"})` | ~50 字符 |
| [4] | user | **skill body（tool_result）** | **~4176 字符** |

**[4] 是最大的一条**——agent-builder 的完整 body。这 4176 字符从现在开始会出现在**每一次后续的 API 调用里**。这是两层注入的"代价"：一旦加载，skill body 就永久占据 messages 空间。

---

## 这个例子的关键收获

1. **Layer 2 的完整流程：** `load_skill` → skill body 作为 `tool_result` → LLM 读取并行动。整个过程和 `read_file` 返回文件内容的模式一模一样——因为 `load_skill` 就是一个普通工具。

2. **skill body 持久留在 messages 里。** 这是和 s04 子 Agent 最大的区别。s04 的 sub_messages 用完就丢，load_skill 的返回值会一直留着。优点是 LLM 可以反复参考，缺点是 messages 会膨胀。

3. **LLM 按照 skill 的指导行动。** skill body 里写着 `"Tell me about your agent idea"`，LLM 就问了用户 `"What's your agent idea?"`。这证明 skill 不只是"参考资料"，更是"行为指令"。
