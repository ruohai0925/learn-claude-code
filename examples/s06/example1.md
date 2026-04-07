# s06 实际运行追踪：读所有 Python 文件（Layer 1 + Layer 2 一次性触发）

> prompt: `Read every Python file in the agents/ directory one by one`
>
> 结果：3 轮。第 2 轮 LLM 一口气并行读取 14 个文件（~230K 字符）→ micro_compact 替换了 1 个 bash 结果、保留了 11 个 read_file 结果 → token 估算 ~60571 远超阈值 12000 → auto_compact 触发 → 5 条 messages 压缩为 1 条 summary。
>
> **重点观察：** Layer 1 和 Layer 2 在同一轮里先后触发。micro_compact 先跑，但因为 read_file 结果被 PRESERVE_RESULT_TOOLS 保护、不被替换，压缩效果有限（只替换了 1 个 bash）。然后 Layer 2 接管，一刀切全部压缩。

---

## 启动

**终端输出：**

```
=== s06 verbose 模式 ===
MODEL     = claude-sonnet-4-6
THRESHOLD = 12000 token（触发 auto_compact）
KEEP_RECENT = 3（micro_compact 保留最近 N 个 tool_result）
PRESERVE_RESULT_TOOLS = {'read_file'}（这些工具的结果不被 micro_compact 替换）
TRANSCRIPT_DIR = /home/yzeng/Codes/learn-claude-code/.transcripts

TOOLS 列表: ["bash", "read_file", "write_file", "edit_file", "compact"]
注意: compact 工具是 Layer 3（手动压缩）
```

**解读：** 对比 s05 启动，多了三个关键配置：THRESHOLD（12000）、KEEP_RECENT（3）、PRESERVE_RESULT_TOOLS（read_file）。这三个数字决定了压缩管道的行为——什么时候压、保留什么、压掉什么。

---

## 第 1 轮：LLM 先列出所有文件

**终端输出：**

```
────────────────── 轮次 1 ──────────────────
token 估算: ~22 / 12000
messages = [
  [0] user: "Read every Python file in the agents/ directory one by one"
]

→ 调用 client.messages.create(...)

────────────────── 轮次 1: 回复 ──────────────────
response.stop_reason = "tool_use"
response.content = [
  TextBlock: "I'll start by listing all the Python files in the `agents/` directory, then read them all!"
  ToolUseBlock: name="bash", id="toolu_01BXdWRP4EQLLeBEMa1JWK5u"
    input={"command": "find /home/yzeng/Codes/learn-claude-code/agents -name \"*.py\" | sort"}
]

────────────────── 轮次 1: 执行工具 ──────────────────
执行: bash({"command": "find ... -name \"*.py\" | sort"})
输出 (875 字符): /home/.../agents/__init__.py
/home/.../agents/s01_agent_loop.py
/home/.../agents/s02_tool_use.py
...（共 14 个文件）
```

**解读：** token 估算只有 22——messages 里只有 1 条用户输入，context 非常干净。

LLM 的策略和 s04 例 1 一致："先全局扫描，再精准读取"（参见 s04 例 1 的讲解）。它先用 `bash find` 列出文件列表（875 字符，很轻），然后在第 2 轮根据列表决定读哪些。

注意 `token 估算: ~22 / 12000`——离阈值 12000 还很远。这个数字会在第 2 轮剧变。

---

## 第 2 轮：一口气并行读取 14 个文件（关键轮）

**终端输出：**

```
────────────────── 轮次 2 ──────────────────
token 估算: ~370 / 12000
messages = [
  [0] user: "Read every Python file in the agents/ directory one by one"
  [1] assistant/text: "I'll start by listing all the Python files in the `agents/` directory, then read..."
  [1] assistant/tool_use: bash({"command": "find ... -name \"*.py\" | sort"})
  [2] user/tool_result: "/home/.../agents/__init__.py\n/home/.../agents/s01_agent_loop.py\n..."
]

→ 调用 client.messages.create(...)

────────────────── 轮次 2: 回复 ──────────────────
response.stop_reason = "tool_use"
response.content = [
  TextBlock: "Found **14 Python files**. Now I'll read them all at once!"
  ToolUseBlock: name="read_file"  →  __init__.py
  ToolUseBlock: name="read_file"  →  s01_agent_loop.py
  ToolUseBlock: name="read_file"  →  s02_tool_use.py
  ToolUseBlock: name="read_file"  →  s03_todo_write.py
  ToolUseBlock: name="read_file"  →  s04_subagent.py
  ToolUseBlock: name="read_file"  →  s05_skill_loading.py
  ToolUseBlock: name="read_file"  →  s06_context_compact.py
  ToolUseBlock: name="read_file"  →  s07_task_system.py
  ToolUseBlock: name="read_file"  →  s08_background_tasks.py
  ToolUseBlock: name="read_file"  →  s09_agent_teams.py
  ToolUseBlock: name="read_file"  →  s10_team_protocols.py
  ToolUseBlock: name="read_file"  →  s11_autonomous_agents.py
  ToolUseBlock: name="read_file"  →  s12_worktree_task_isolation.py
  ToolUseBlock: name="read_file"  →  s_full.py
]

────────────────── 轮次 2: 执行工具 ──────────────────
执行: read_file → __init__.py              (202 字符)
执行: read_file → s01_agent_loop.py        (8,924 字符)
执行: read_file → s02_tool_use.py          (11,548 字符)
执行: read_file → s03_todo_write.py        (15,164 字符)
执行: read_file → s04_subagent.py          (14,213 字符)
执行: read_file → s05_skill_loading.py     (16,541 字符)
执行: read_file → s06_context_compact.py   (19,679 字符)
执行: read_file → s07_task_system.py       (10,108 字符)
执行: read_file → s08_background_tasks.py  (9,349 字符)
执行: read_file → s09_agent_teams.py       (16,835 字符)
执行: read_file → s10_team_protocols.py    (21,028 字符)
执行: read_file → s11_autonomous_agents.py (25,021 字符)
执行: read_file → s12_worktree_task_isolation.py (25,882 字符)
执行: read_file → s_full.py               (36,454 字符)  ← 最大的一个
```

**解读：** **14 个 read_file 并行调用！** 注意用户说的是 `"one by one"`，但 LLM 选择了一口气全读——它自己说 `"Now I'll read them all at once!"`。LLM 的判断是"并行更高效"，即使用户的措辞暗示逐个读。

14 个文件的内容加起来：

| 文件 | 大小 |
|---|---|
| 最小：__init__.py | 202 字符 |
| 最大：s_full.py | 36,454 字符 |
| **总计** | **~230,948 字符** |

这些全部作为 tool_result 塞进了 messages。加上之前第 1 轮的 bash find 结果（875 字符），tool_result 总数达到 **15 个**。

**token 估算从 ~370 飙升到 ~60,000。** 输入时 messages 里只有 3 条消息（~370 token），执行完 14 个 read_file 后多了 14 个 tool_result（~230K 字符 ÷ 4 ≈ ~57,700 token）。这一轮让 context 直接从"很空"变成"爆满"。

**这和 s04 例 2（27 个 read_file）是同一个模式**——LLM 喜欢"一口气全读"。但 s04 例 2 没有压缩管道，直接撞了 rate limit 崩溃。s06 有三层压缩兜底——接下来看它们怎么工作。

---

## Layer 1 触发：micro_compact 的选择性保留

```
────────────────── Layer 1: micro_compact ──────────────────
tool_result 总数: 15, 保留最近 3 个
替换了 1 个旧 tool_result → "[Previous: used ...]"
保留了 11 个 read_file 结果（PRESERVE_RESULT_TOOLS）
压缩后 token 估算: ~60571
```

**解读：** micro_compact 扫描了 15 个 tool_result，保留最近 3 个（s11、s12、s_full 的 read_file 结果），尝试替换前 12 个。但：

- 11 个是 read_file 结果 → **PRESERVE_RESULT_TOOLS 保护，不替换**
- 1 个是 bash find 结果 → **替换为 `"[Previous: used bash]"`**

**结果：micro_compact 只替换了 1 个 tool_result。** 约 875 字符的 bash 输出被替换为 ~25 字符的占位符——省了约 850 字符（~200 token）。但 messages 里还有 230,000+ 字符的 read_file 内容，token 估算 ~60571，远超阈值 12000。

**这暴露了 PRESERVE_RESULT_TOOLS 的双刃剑效应：** 保留 read_file 结果避免了 LLM 重新读文件的浪费，但当一次性读了大量文件时，这些结果会把 micro_compact 架空——它几乎没法压缩任何东西。

---

## Layer 2 触发：auto_compact 接管

```
────────────────── Layer 2: 触发! token 估算 ~60571 > 12000 ──────────────────

────────────────── Layer 2: auto_compact — 保存 transcript ──────────────────
transcript 保存到: .transcripts/transcript_1775519642.jsonl
原始 messages: 5 条

────────────────── Layer 2: auto_compact — LLM 总结 ──────────────────
→ 调用 client.messages.create(...)（总结用，非主循环）

────────────────── Layer 2: auto_compact — 压缩结果 ──────────────────
原始: 5 条 messages → 压缩后: 1 条
summary (1736 字符):
## Conversation Summary
### What Was Accomplished
A progressive series of Python agent harness implementations was reviewed...
```

**5 条 messages（~60571 token）→ 1 条（~477 token）。** 压缩比约 127:1。

**transcript 里保存的是什么？** transcript 是在 auto_compact 开头保存的——此时 micro_compact 已经跑过了，但因为 PRESERVE_RESULT_TOOLS 保护了所有 read_file 结果，14 个文件的**完整内容都还在 messages 里**。唯一被 micro_compact 替换掉的是第 1 轮的 bash find 输出（变成了 `"[Previous: used bash]"`）。所以 transcript 文件（278KB）保存了几乎完整的原始对话——14 个文件的全部内容都在里面。

这意味着：如果未来需要从 transcript 恢复，你能拿回所有文件内容。但前提是这是**第一次** auto_compact——后续的 transcript 保存的是 summary 而不是原始内容（参见讲义"累积压缩损失"）。

注意 summary 的内容：LLM 总结了 14 个文件的核心功能——s01 的 agent loop、s04 的 subagent、s06 的 compression 等等。230,000 字符的文件内容被浓缩成了 1736 字符。

---

## 第 3 轮：压缩后的 LLM

```
────────────────── 轮次 3 ──────────────────
token 估算: ~477 / 12000
messages = [
  [0] user: "[Conversation compressed. Transcript: .transcripts/transcript_1775519642.jsonl]..."
]

response.stop_reason = "end_turn"
response.content = [
  TextBlock: "I'm ready to help! What would you like to work on?"
]
```

**解读：** 压缩后 messages 只有 1 条（summary），LLM 从 summary 里知道"刚才读了 14 个 agent 文件"，然后简短地说"准备好了，想做什么？"。

**LLM 丢失了什么？** 所有 14 个文件的具体内容。如果你现在问它 "s04_subagent.py 的第 210 行是什么？"，它回答不了——需要重新 `read_file`。但如果你问 "s04 是做什么的？"，它能从 summary 里回答"子 Agent，上下文隔离"。

---

## 这个例子的关键收获

1. **Layer 1 和 Layer 2 可以在同一轮先后触发。** micro_compact 先跑（温和压缩），发现不够（read_file 被保护），然后 auto_compact 接管（激进压缩）。两层是顺序执行的，不是互斥的。

2. **PRESERVE_RESULT_TOOLS 在大量读取时会被"架空"。** 14 个 read_file 结果全部被保留，micro_compact 只替换了 1 个 bash 结果——杯水车薪。这说明 PRESERVE_RESULT_TOOLS 的设计假设是"LLM 不会一次读太多文件"，一旦违反这个假设，Layer 1 就失效了，完全依赖 Layer 2 兜底。

3. **auto_compact 的 127:1 压缩比极其激进。** 230K 字符 → 1736 字符。代价是丢失了所有文件的具体内容，LLM 只记得"读过什么、每个文件大概做什么"。

4. **这和 s04 例 2 形成了对比。** s04 例 2（无压缩）读 27 个文件后直接撞 rate limit 崩溃了。s06 读 14 个文件后，压缩管道自动触发，Agent 继续工作。**压缩让 Agent 从"读几十个文件就崩"变成了"永远不崩"。**
