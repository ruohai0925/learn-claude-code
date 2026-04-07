# s06 实际运行追踪：手动调用 compact 工具（Layer 3）

> prompt: `Use the compact tool to manually compress the conversation`
>
> 结果：接续 example2。1 轮，LLM 调用 `compact` 工具 → Layer 3 触发 → auto_compact 保存 transcript + LLM 总结 → 5 条 messages 压缩为 1 条。
>
> **重点观察：** LLM 在调用 compact 时传了一个 `focus` 参数，指定了摘要应该保留的信息。这是 Layer 3 比 Layer 2 多出的一个细节——LLM 可以告诉总结者"什么最重要"。但当前代码并没有使用这个参数。

---

## 起始状态

```
token 估算: ~598 / 12000
messages = [
  [0] user: "[Conversation compressed...]..."   ← example2 的 summary
  [1] assistant/text: "I have the context from the compressed conversation..."
  [2] user: "Use the compact tool to manually compress the conversation"
]
```

只有 3 条 messages，~598 token。远没到 12000 的 auto_compact 阈值——如果没有 Layer 3，这个对话不会被压缩。

---

## 第 1 轮：LLM 调用 compact 工具

```
────────────────── 轮次 1: 回复 ──────────────────
response.stop_reason = "tool_use"
response.content = [
  ToolUseBlock: name="compact", id="toolu_01TsiCLYW95T8zmNwh9Jxecx"
    input={"focus": "Repository structure of learn-claude-code project, including agents (s01-s12),
    docs (EN/ZH/JA), examples (s01-s05 with MCP server at s05), Python 3.13 venv with
    mcp/fastapi/uvicorn/httpx/py..."}
]

────────────────── 轮次 1: 执行工具 ──────────────────
compact 工具被调用! 将在本轮结束后执行压缩
```

**解读：** LLM 用了 `compact` 工具，并传了一个 `focus` 参数——列出了它认为摘要应该保留的关键信息（项目结构、agents 列表、技术栈等）。

**但这个 `focus` 参数被浪费了。** 看代码：

```python
# 循环里的处理：
if block.name == "compact":
    manual_compact = True
    output = "Compressing..."    # ← focus 参数被完全忽略了

# auto_compact 里的总结 prompt：
"Summarize this conversation for continuity. Include:
 1) What was accomplished, 2) Current state, 3) Key decisions made."
# ← 没有使用 focus 参数
```

`compact` 工具的 input schema 定义了 `focus` 参数（`"What to preserve in the summary"`），LLM 也确实传了值——但我们的代码既没有把 `focus` 传给 `auto_compact`，也没有把它加进总结 prompt。**这是一个未完成的功能。**

如果要用起来，只需要在 `auto_compact` 里把 `focus` 拼进 summary prompt：

```python
"Summarize this conversation for continuity. Focus on: {focus}. Include: ..."
```

这样 LLM 就能告诉总结者"重点保留什么"——比如在代码审查场景下保留安全问题列表，在构建场景下保留项目结构。

---

## Layer 3 执行："标记 → 延迟执行"模式

```
────────────────── Layer 3: manual compact 执行 ──────────────────

────────────────── Layer 2: auto_compact — 保存 transcript ──────────────────
transcript 保存到: .transcripts/transcript_1775519844.jsonl
原始 messages: 5 条

────────────────── Layer 2: auto_compact — LLM 总结 ──────────────────
→ 调用 client.messages.create(...)（总结用，非主循环）
发送 conversation_text 最后 2993 字符给 LLM 做总结

────────────────── Layer 2: auto_compact — 压缩结果 ──────────────────
原始: 5 条 messages → 压缩后: 1 条
summary (1299 字符):
## Conversation Summary
### 1) What Was Accomplished
- Repository structure exploration was performed
- A manual compact tool call was attempted
```

**"原始 messages: 5 条"——这 5 条是怎么来的？** 查看 transcript 文件的内容：

| 索引 | role | 内容 | 来源 |
|---|---|---|---|
| [0] | user | `"[Conversation compressed...]\n\n## Summary..."` | example2 的 auto_compact 生成的 summary |
| [1] | assistant | `"I have the context... What would you like to work on?"` | LLM 基于 summary 的回复 |
| [2] | user | `"Use the compact tool to manually compress the conversation"` | 用户输入（example3 的 prompt） |
| [3] | assistant | `ToolUseBlock: name="compact", input={focus: "..."}` | LLM 调用 compact 工具 |
| [4] | user | `tool_result: "Compressing..."` | 塞回的假 tool_result |

关键：`[3]` 和 `[4]` 是在 auto_compact **之前**就已经 append 到 messages 里了。回忆代码的执行顺序：

```python
# 工具执行阶段：
results.append({"tool_result", ..., "content": "Compressing..."})  # ← [4] 在这里产生
messages.append({"role": "user", "content": results})              # ← [4] 塞进 messages

# 然后才压缩：
if manual_compact:
    messages[:] = auto_compact(messages)    # ← 此时 messages 已经有 5 条
```

**"先塞 result 再压缩"**——所以 transcript 保存的 5 条 messages 里包含了 compact 工具的 tool_result（`"Compressing..."`）。这个假的 tool_result 也被写进了 transcript，作为"LLM 曾经调用过 compact 工具"的历史记录。

**注意 verbose 输出的顺序：** 先打印 "Layer 3: manual compact 执行"，然后打印 "Layer 2: auto_compact" 的过程——因为 Layer 3 调用的就是 `auto_compact()` 函数。

"发送 conversation_text 最后 **2993 字符**" —— 对比 example1 的 80000 字符，这次只有 ~3K 字符要总结（因为 messages 本来就只有 5 条，大部分是之前的 summary）。这是"summary 的 summary" —— 信息进一步衰减。

---

## 最终状态

```
────────────────── 最终回答 ──────────────────
[Conversation compressed. Transcript: .transcripts/transcript_1775519844.jsonl]

## Conversation Summary
### 1) What Was Accomplished
- Repository structure exploration was performed
- A manual compact tool call was attempted

### 2) Current State
- Project: learn-claude-code repository
- Structure:
  - agents/: 12 agent example scripts (s01–s12)...
```

**注意：** Layer 3 触发后 `return` 结束了 `agent_loop`，所以最终回答不是 LLM 的回复，而是**压缩后的 summary 本身**（作为 messages 里唯一的一条）。LLM 没有机会基于 summary 再说一句话——那是下一次用户输入时才会发生的。

---

## 三次压缩的 transcript 文件

```
.transcripts/
├── transcript_1775519642.jsonl  (283 KB)  ← example1: 14个文件内容
├── transcript_1775519700.jsonl  (155 KB)  ← example2: summary_1 + 读了几个文件
├── transcript_1775519844.jsonl  (2.9 KB)  ← example3: summary_2 + compact调用
```

**文件大小递减**——每次 auto_compact 后 messages 变少，transcript 也变小。第三个 transcript 只有 2.9 KB，里面存的主要是前两次压缩的 summary。

---

## 三个 Layer 的全程回顾

| 时机 | Layer | 做了什么 |
|---|---|---|
| example1 轮次 2 后 | **Layer 1** | 替换了 1 个 bash 结果，但 11 个 read_file 被保护 |
| example1 轮次 2 后 | **Layer 2** | token ~60571 > 12000，5条→1条 |
| example2 轮次 2 后 | **Layer 1** | 替换了 1 个 bash 结果 |
| example2 轮次 3 后 | **Layer 1** | 保留了 1 个 read_file，替换了 0 个 |
| example2 轮次 4 后 | **Layer 1** | 保留了 2 个 read_file，替换了 0 个 |
| example2 轮次 5 后 | **Layer 1** | 保留了 4 个 read_file，替换了 0 个 |
| example2 轮次 5 后 | **Layer 2** | token ~35639 > 12000，13条→1条 |
| example3 轮次 1 | **Layer 3** | LLM 主动调 compact，5条→1条 |

**Layer 1 频繁触发但效果有限**（read_file 保护太多），**Layer 2 两次兜底**，**Layer 3 一次手动触发**。

---

## 这个例子的关键收获

1. **Layer 3 调用的就是 Layer 2 的 `auto_compact()`。** 从执行结果看完全一样——保存 transcript、LLM 总结、替换 messages。区别只是谁触发的。

2. **`focus` 参数是一个好设计但未实现。** LLM 传了它认为重要的信息，但代码没有使用。这是一个值得注意的改进方向——让 LLM 参与"决定保留什么"。

3. **Layer 3 触发后直接 return，完全不管 `stop_reason`。** 正常的循环流程是先检查 `response.stop_reason != "tool_use"` 来决定是否继续循环。但 `manual_compact` 的 `return` 在那个检查**之后**、**下一轮循环之前**执行——它直接跳出了整个 `while True`，不给 LLM 机会基于压缩后的 summary 再说一句话。所以最终回答是 summary 本身，不是 LLM 的回复。下一次用户输入时，LLM 才会看到 summary 并做出反应。

4. **三次压缩后信息衰减严重。** 从"14 个文件的完整内容"到"知道有个 learn-claude-code 项目"。transcript 文件大小的递减（283KB → 155KB → 2.9KB）直观地展示了这种衰减。
