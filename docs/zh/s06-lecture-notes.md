# s06: Context Compact —— 让 Agent 永远工作下去

> **前置知识：** 请先完成 [s01](s01-lecture-notes.md) - [s05](s05-lecture-notes.md)。本讲义不重复已讲过的概念，只聚焦 s06 的新内容。

---

## 这一课要回答的问题

> s05 里 skill body 加载后**永久留在 messages 里**，越来越胀。s04 例 2 里子 Agent 读了 27 个文件直接撞 rate limit。context window 是有限的——如果 Agent 要长时间工作（读几十个文件、跑几十个命令），怎么办？

**答案：三层压缩管道。温和压缩每轮自动跑，激进压缩在 token 超阈值时触发，手动压缩由 LLM 自己决定。**

---

## 核心类比：手机存储管理

你的手机存储有限（128GB），但你不会每天手动清理。系统帮你做了：

| 手机 | s06 |
|---|---|
| 自动清理缓存（你感觉不到） | **Layer 1: micro_compact**（每轮静默替换旧 tool_result） |
| 存储快满时自动把旧照片移到云端 | **Layer 2: auto_compact**（token > 阈值时保存 transcript + LLM 总结） |
| 你手动点"立即清理" | **Layer 3: compact 工具**（LLM 主动调用） |

三层逐级递进：Layer 1 最温和（只替换占位符），Layer 2 最激进（用 summary 替换全部 messages），Layer 3 和 Layer 2 相同但由 LLM 决定时机。

---

## s05 → s06：到底变了什么？

| 组件 | s05 | s06 | 变了吗？ |
|---|---|---|---|
| `while True` 循环结构 | 有 | 一样，但**三个位置插入了压缩逻辑** | **变了** |
| 工具 | 5 个（base + load_skill） | 5 个（base + **compact**） | **变了** |
| micro_compact | 无 | **新增**（每轮静默替换旧 tool_result） | **新增** |
| auto_compact | 无 | **新增**（token > 阈值时自动压缩） | **新增** |
| Transcript 保存 | 无 | **新增**（.transcripts/ 目录） | **新增** |
| SkillLoader | 有 | **去掉了**（s06 聚焦于压缩，不含 skill） | 去掉 |

**s05 的问题在 s06 得到了解决：** skill body 和大量文件内容留在 messages 里不断膨胀——s06 的三层压缩会逐步清理它们。

---

## 概念 1：Layer 1 — micro_compact（每轮静默执行）

### 做什么

每次调 LLM **之前**，扫描 messages 里所有的 `tool_result`，把**最近 3 个之前的**旧结果替换为占位符：

```
之前: {"type": "tool_result", "content": "#!/usr/bin/env python3\nimport os\nimport...（8000 字符）"}
之后: {"type": "tool_result", "content": "[Previous: used bash]"}
```

### 不替换什么

两种情况不替换：
1. **content <= 100 字符**——已经够短了，压缩没意义（比如 `"Wrote 321 bytes"`）
2. **read_file 的结果**——`PRESERVE_RESULT_TOOLS = {"read_file"}`

**这里的"100 字符"到底意味着多少 token？** 这个问题在 s04 例 2 里也出现过。三个单位经常被混用，理清一下：

| 单位 | 是什么 | 谁用 |
|---|---|---|
| **字节 (bytes)** | 磁盘上的存储大小。1 个 ASCII 字符 = 1 byte，1 个中文字符 = 3 bytes (UTF-8) | `write_file` 返回的 `"Wrote 321 bytes"` |
| **字符 (characters)** | Python `len(string)` 的结果。1 个字母 = 1 字符，1 个中文 = 1 字符 | 代码里 `len(result["content"]) <= 100` 判断的 |
| **token** | Claude tokenizer 的切分单位。大小不固定 | API 计费、context window 限制 |

**它们之间没有固定的换算公式**，因为 token 的大小取决于 tokenizer 和内容类型：

```
英文散文:  "Hello, world!"     = 13 字符, 13 bytes,  ~4 token  → ~3.3 字符/token
Python 代码: "def foo(x):\n"   = 13 字符, 13 bytes,  ~5 token  → ~2.6 字符/token
中文文本:  "你好世界"           = 4 字符,  12 bytes,  ~4 token  → ~1 字符/token
文件路径:  "/home/yzeng/Co..." = 30 字符, 30 bytes,  ~10 token → ~3 字符/token
```

所以 s06 里的"100 字符"大约是 **25-40 token**——确实很短，替换成 `"[Previous: used bash]"`（~25 字符 ≈ ~8 token）省不了几个 token，反而丢了信息。这就是为什么跳过它们。

而 `estimate_tokens` 用的 `len(str(messages)) // 4`（4 字符/token）只是一个**粗略近似**——对英文散文大致准确，对代码会低估，对中文会严重高估。生产环境（如 Claude Code）会用精确的 tokenizer 计算，而不是靠除以 4。

### 为什么保留 read_file？

```python
PRESERVE_RESULT_TOOLS = {"read_file"}
```

read_file 的输出是**参考材料**——LLM 可能需要反复查阅文件内容来做决策。如果压缩了，LLM 就得再调一次 `read_file` 重新读，白白浪费一次工具调用和 API 请求。

而 bash 的输出通常是**执行确认**（`"Directory ready"`、`"Wrote 321 bytes"`、`"Successfully installed..."`），LLM 知道命令执行成功就够了，不需要看完整输出。用 `"[Previous: used bash]"` 替代完全够用。

### 原地修改的陷阱

```python
result["content"] = f"[Previous: used {tool_name}]"
```

micro_compact 直接修改 dict 对象的 `"content"` 字段——**旧内容永久丢失**。这不是创建一个新的 messages 列表，而是改了列表里的 dict。如果你需要旧内容，唯一的来源是 auto_compact 保存的 transcript 文件。

### verbose 里看什么

```
──────────── Layer 1: micro_compact ────────────────
tool_result 总数: 8, 保留最近 3 个
替换了 4 个旧 tool_result → "[Previous: used ...]"
保留了 1 个 read_file 结果（PRESERVE_RESULT_TOOLS）
压缩后 token 估算: ~12000
```

关键数字：替换了几个、保留了几个 read_file、压缩后 token 估算。

---

## 概念 2：Layer 2 — auto_compact（token 超阈值时触发）

### 触发条件

```python
if estimate_tokens(messages) > THRESHOLD:  # THRESHOLD = 12000
    messages[:] = auto_compact(messages)
```

`estimate_tokens` 是一个粗略估算：`len(str(messages)) // 4`。不精确，但足以判断"是不是快满了"。

### 做什么

两步：

**步骤 1：保存 transcript 到磁盘**

```python
transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
with open(transcript_path, "w") as f:
    for msg in messages:
        f.write(json.dumps(msg, default=str) + "\n")
```

完整的 messages 以 JSONL 格式保存到 `.transcripts/` 目录。这是**安全网**——即使 messages 被压缩成 1 条 summary，原始对话还在磁盘上。

**步骤 2：让 LLM 总结**

```python
response = client.messages.create(
    model=MODEL,
    messages=[{"role": "user", "content":
        "Summarize this conversation for continuity. Include: "
        "1) What was accomplished, 2) Current state, 3) Key decisions made. "
        "Be concise but preserve critical details.\n\n" + conversation_text}],
    max_tokens=2000,
)
```

注意这是一次**独立的 API 调用**——不在主循环里，不使用 system prompt，**不提供 tools**。

**为什么不提供 tools？** 这是一个刻意的设计。如果提供了 tools，LLM 在总结时可能会说"让我先读一下那个文件确认一下"，然后调 `read_file`——但我们要的不是让它去核实信息，而是让它**就着现有的 messages 文本**写一段 summary。不给 tools 就断了它"我想先查查"的念头，强制它只做一件事：读文本、写总结。

这和 s04 子 Agent 的设计形成了有趣的对比：s04 的子 Agent 有 4 个工具（bash/read_file/write_file/edit_file），因为它的任务是**去做事**；auto_compact 的总结调用没有工具，因为它的任务是**回顾和总结**。给什么工具决定了 LLM 的行为模式。

**`max_tokens=2000` 意味着什么？** 算一下压缩比：

```
输入: ~12,000 token 的对话（触发阈值时，教学演示配置）
      → 取最后 80,000 字符发给 LLM
输出: max_tokens=2000（summary 最多 2000 token）

压缩比: 12,000 → 2,000 = 6:1（教学配置）
生产环境: 100,000 → 2,000 = 50:1（更激进）
```

这是极其激进的有损压缩。打个比方：一本 250 页的书压缩成 10 页的摘要。LLM 必须在 2000 token 内回答三个问题：做了什么、当前状态、关键决策。大量细节必然丢失——具体的文件内容、中间的错误和恢复过程、工具调用的参数等，全部被浓缩成几句话。

**为什么敢这么激进？** 因为有两层保障：
1. **transcript 已经保存在磁盘上**——细节虽然不在 messages 里了，但没有真正消失
2. **LLM 还有工具可以重新获取信息**——如果压缩后 LLM 需要某个文件的内容，它可以再调 `read_file` 重新读

所以 auto_compact 的哲学是：**宁可压过头，也不要撑爆 context。** 丢信息可以补回来（重新读文件、重新跑命令），但 context 溢出了就什么都做不了。

**然后用 summary 替换全部 messages：**

```python
return [
    {"role": "user", "content": f"[Conversation compressed. Transcript: {transcript_path}]\n\n{summary}"},
]
```

从可能几十条 messages → **1 条**。这是最激进的压缩。

### `messages[:] = ...` 的讲究

```python
messages[:] = auto_compact(messages)   # ← 原地替换
messages = auto_compact(messages)      # ← 创建新变量（错误！）
```

`messages[:] = ...` 是 Python 的**切片赋值**，它原地替换列表内容。因为 `agent_loop` 外面的 `history` 变量也指向同一个列表对象，`messages[:] = ...` 会同时更新 `history`。如果用 `messages = ...`（不带 `[:]`），只会改变局部变量，`history` 不受影响——下次用户输入时 `history` 还是未压缩的旧版本。

### 总结的质量由 LLM 决定

auto_compact 的 prompt 里写了三个要求：`1) What was accomplished, 2) Current state, 3) Key decisions made.` 但 LLM 的总结质量不可控——它可能遗漏重要细节，也可能过度压缩。

**这是一种有损压缩。** 和 s04 子 Agent 返回摘要类似——信息被极度压缩，细节丢失。区别是 s04 丢的是子 Agent 的中间过程，s06 丢的是**主对话的历史**。

---

## 概念 3：Layer 3 — compact 工具（LLM 手动触发）

### 和 auto_compact 的区别

| 维度 | Layer 2 (auto_compact) | Layer 3 (compact 工具) |
|---|---|---|
| 谁决定触发 | **harness**（代码自动检查 token） | **LLM**（主动调用 compact 工具） |
| 何时触发 | token > THRESHOLD 时 | LLM 认为"该压缩了"时 |
| 最终调用的函数 | `auto_compact(messages)` | **同一个** `auto_compact(messages)` |

没错——**Layer 2 和 Layer 3 的执行逻辑没有任何区别**，都是调用同一个 `auto_compact()` 函数：保存 transcript → LLM 总结 → 替换 messages。从实现角度看，它们就是同一段代码的两个入口：

```python
# Layer 2 的入口（循环开头）：
if estimate_tokens(messages) > THRESHOLD:
    messages[:] = auto_compact(messages)       # ← 调 auto_compact

# Layer 3 的入口（循环结尾）：
if manual_compact:
    messages[:] = auto_compact(messages)       # ← 还是调 auto_compact
```

那为什么还要分成"两层"？因为区别不在执行，而在**决策者**。Layer 2 是 harness 说了算（硬性阈值，100% 确定会触发），Layer 3 是 LLM 说了算（软性判断，LLM 觉得"该清理了"才触发）。这是两种不同的控制权分配——一个是代码兜底，一个是 LLM 主动。

**LLM 调用的是什么？** 就是我们在 `TOOLS` 列表里定义的一个名叫 `compact` 的工具：

```python
{"name": "compact", "description": "Trigger manual conversation compression.",
 "input_schema": {"type": "object", "properties": {
     "focus": {"type": "string", "description": "What to preserve in the summary"}}}}
```

它和 `bash`、`read_file` 一样出现在 LLM 的工具列表里。LLM 看到它的描述 `"Trigger manual conversation compression"`，就知道可以在需要时调用它。调用方式和其他工具一模一样——LLM 返回一个 `ToolUseBlock(name="compact", input={...})`。

但**执行逻辑完全不同**。`bash` 和 `read_file` 的执行是"调函数返回字符串"，而 `compact` 的执行是"设一个标志位，等循环结束后替换全部 messages"。从 LLM 的角度看，它只是调了一个普通工具；从 harness 的角度看，这个工具触发了一次全局压缩。

Layer 3 给了 LLM 一个主动权：如果 LLM 觉得对话太长了、或者当前任务告一段落想"清理桌面"，它可以自己调 `compact` 工具。

### 在循环里的特殊处理

```python
if block.name == "compact":
    manual_compact = True           # 只标记，不立即执行
    output = "Compressing..."       # 先塞一个假的 tool_result

# ... 塞完所有 tool_result 后 ...

if manual_compact:
    messages[:] = auto_compact(messages)   # 现在才真正执行
    return                                  # 压缩后结束循环
```

为什么不在工具执行时立刻压缩？因为 API 要求**每个 tool_use 必须有对应的 tool_result**。如果立刻压缩（替换全部 messages），`compact` 工具的 tool_result 就没有被塞进去，API 下次调用会报错。

**这个"先塞 result 再动手"的设计思想贯穿整个 harness。** 回顾 s01 以来的循环结构：

```python
# 每一轮的固定顺序（不能乱）：
messages.append({"role": "assistant", "content": response.content})  # ① 先存 LLM 回复
# ... 执行工具 ...
messages.append({"role": "user", "content": results})                # ② 再存 tool_result
# ③ 只有 ①② 都完成后，才能做"破坏性"操作（压缩、返回等）
```

Claude API 对 messages 的格式有严格约束：`assistant` 消息里如果有 `tool_use` block，紧接着的 `user` 消息里**必须**有对应 `tool_use_id` 的 `tool_result`。这不是 best practice，是**硬性要求**——不满足就 400 报错。

这个约束意味着：**任何想修改 messages 的操作（压缩、清理、替换），都必须等 tool_result 塞完之后。** s06 的 `manual_compact` 用了"标记 → 延迟执行"模式来遵守这个约束：

```
LLM 返回 tool_use: compact
    │
    ▼
执行阶段: manual_compact = True, output = "Compressing..."
    │     （只标记，不压缩。同时塞一个假的 tool_result）
    ▼
所有 tool_result 塞完
    │
    ▼
检查标记: if manual_compact → 现在才真正调 auto_compact()
```

这个模式在更复杂的 harness 里也很常见——凡是需要"执行完工具后改变全局状态"的操作（压缩 context、切换模式、结束会话），都是先标记、后执行。Claude Code 里的 `/compact` 命令也是这个逻辑。

这和 s04 的 `task` 工具一样是**侵入式**的（参见 s05 讲义的"非侵入式 vs 侵入式"讨论）——需要在循环里加 `if/else` 特殊分支。

---

## 概念 4：三层的协作关系

```
用户输入 → 循环开始
              │
              ▼
         [Layer 1: micro_compact]          ← 每轮都跑，温和
              │
              ▼
         token > 12000?
          │         │
          no        yes
          │         ▼
          │   [Layer 2: auto_compact]      ← 超阈值时跑，激进
          │         │
          ▼         ▼
         调 LLM → 获得 response
              │
              ▼
         LLM 调了 compact 工具?
          │         │
          no        yes
          │         ▼
          │   [Layer 3: manual compact]    ← LLM 主动触发
          │         │
          ▼         ▼
         继续循环    结束循环
```

正常情况下，Layer 1 每轮都在工作（你在 verbose 里能看到），Layer 2 偶尔触发（token 积累到阈值），Layer 3 很少用（LLM 不常主动调 compact）。

**Layer 1 是"拖延" Layer 2 的手段。** 如果没有 Layer 1，messages 会更快地膨胀到阈值（12000 token），Layer 2 触发更频繁。Layer 1 通过替换旧 tool_result，延缓了 token 的增长速度，让 Agent 在不丢失对话历史的情况下多跑几轮。

---

## 概念 5：什么丢了，什么没丢

| 层级 | 丢了什么 | 保留了什么 |
|---|---|---|
| Layer 1 | 旧 tool_result 的具体内容 | tool_result 的存在（`"[Previous: used bash]"`），read_file 的完整内容 |
| Layer 2/3 | **全部 messages 的细节** | LLM 生成的 summary，transcript 文件（磁盘上） |

**Layer 1 是可逆的吗？** 不可逆。旧 tool_result 被原地修改，内存里的内容永久丢失。但如果之后触发了 Layer 2，transcript 里保存的是 Layer 1 修改后的版本（已经是占位符了），所以原始内容也找不回来。

**Layer 2 是可逆的吗？** 理论上部分可逆——transcript 文件保存在磁盘上，包含了压缩前的 messages。但实际上有两个问题：

**问题 1：transcript 保存的可能已经是 Layer 1 处理过的版本。** 如果 Layer 1 先把旧 tool_result 替换成了 `"[Previous: used bash]"`，然后 Layer 2 触发保存 transcript——transcript 里存的就是替换后的占位符，原始内容已经找不回来了。

**问题 2：后面的 transcript 会"覆盖"前面的恢复价值。** 看文件名的生成方式：

```python
transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
```

每次 auto_compact 都会生成一个新的 transcript 文件（时间戳不同，不会物理覆盖）。但考虑这个场景：

```
第 1 次 auto_compact:
  transcript_1712419200.jsonl ← 保存了完整的 25 条 messages
  messages 被压缩成 1 条 summary

... 继续工作，messages 再次膨胀 ...

第 2 次 auto_compact:
  transcript_1712419800.jsonl ← 保存了什么？
    [0] "[Conversation compressed...]\n\n{第 1 次的 summary}"  ← 第 1 次压缩的结果
    [1] user: "..."
    [2] assistant: ...
    ...
```

第 2 个 transcript 的第 [0] 条消息是**第 1 次压缩后的 summary**，不是原始的 25 条 messages。如果你想恢复到最初的完整对话，需要从 `transcript_1712419200.jsonl`（第 1 个文件）开始，而且它可能已经被 Layer 1 处理过了。**每次压缩都是在上一次压缩的基础上再压缩——信息损失是累积的、不可逆的。**

当前代码也没有实现从 transcript 恢复的功能——它只管保存，不管读回来。transcript 更像是**事后审计的日志**，而不是**可操作的备份**。

---

## 和 s04/s05 的对比：三种"减负"策略

| 维度 | s04（子 Agent） | s05（skill loading） | s06（context compact） |
|---|---|---|---|
| 解决什么问题 | 探索任务污染父 context | 领域知识膨胀 system prompt | messages 无限增长 |
| 减负方式 | 隔离（独立 messages） | 按需加载（不用就不加载） | 压缩（替换/总结/丢弃） |
| 信息丢失 | 子 Agent 的中间过程 | 无（只是延迟加载） | 旧 tool_result 细节 + 对话历史 |
| 可恢复性 | 不可恢复（sub_messages 被 GC） | 不适用 | 部分可恢复（transcript 文件） |

三者可以组合使用：子 Agent 隔离大任务（s04）→ skill 按需加载知识（s05）→ context compact 定期清理（s06）。这就是 Claude Code 的实际做法。

---

## verbose 输出里看什么

### Layer 1 触发时

```
──────────── Layer 1: micro_compact ────────────────
tool_result 总数: 8, 保留最近 3 个
替换了 4 个旧 tool_result → "[Previous: used ...]"
保留了 1 个 read_file 结果（PRESERVE_RESULT_TOOLS）
压缩后 token 估算: ~12000
```

### Layer 2 触发时

```
──────────── Layer 2: 触发! token 估算 ~13000 > 12000 ────────────────

──────────── Layer 2: auto_compact — 保存 transcript ────────────────
transcript 保存到: .transcripts/transcript_1712419200.jsonl
原始 messages: 23 条

──────────── Layer 2: auto_compact — LLM 总结 ────────────────
→ 调用 client.messages.create(...)（总结用，非主循环）

──────────── Layer 2: auto_compact — 压缩结果 ────────────────
原始: 23 条 messages → 压缩后: 1 条
summary (856 字符): ...
```

### Layer 3 触发时

```
──────────── 轮次 N: 执行工具 ────────────────
compact 工具被调用! 将在本轮结束后执行压缩

──────────── Layer 3: manual compact 执行 ────────────────
（然后和 Layer 2 相同的输出）
```

---

## 自己动手试试

```sh
python agents/s06_context_compact.py
```

| 试这个 prompt | 观察什么 | 详细追踪 |
|---|---|---|
| `Read every Python file in the agents/ directory one by one` | micro_compact 何时开始替换？哪些 tool_result 被保留（read_file）？ | [example1.md](../../examples/s06/example1.md) |
| `Keep reading files until compression triggers automatically` | token 估算什么时候超过 12000？auto_compact 的 summary 质量如何？ | [example2.md](../../examples/s06/example2.md) |
| `Use the compact tool to manually compress the conversation` | LLM 什么时候决定调 compact？和 auto_compact 有什么行为差异？ | [example3.md](../../examples/s06/example3.md) |

---

## 这一课的关键收获

1. **三层压缩逐级递进。** Layer 1（温和，每轮）→ Layer 2（激进，超阈值）→ Layer 3（激进，LLM 主动）。层级越高，丢失的信息越多，但释放的空间也越大。

2. **micro_compact 的"选择性保留"是关键设计。** read_file 的结果不被替换，因为它是参考材料；bash 的结果可以替换，因为 LLM 只需要知道"执行过了"。这种**按工具类型区分**的压缩策略，比一刀切地压缩所有 tool_result 更智能。

3. **auto_compact 用 LLM 总结 LLM 自己的对话。** 这是一种"元认知"——让 LLM 回顾自己做了什么，提取关键信息。summary 的质量直接决定了压缩后 Agent 还能否继续正确工作。

4. **transcript 是安全网，不是恢复机制。** 当前代码只保存 transcript，没有实现从 transcript 恢复的功能。它更像是"黑匣子"——出了问题可以事后分析，但不能实时恢复。

5. **`messages[:] = ...` 是关键的 Python 技巧。** 切片赋值原地替换列表内容，保持外部引用有效。这是 s06 能在 `agent_loop` 内部改变 `history` 的原因。

6. **`api_call_with_retry` 是教学演示的必要补丁。** s06 的场景特别容易撞 rate limit：读大量文件 → messages 膨胀 → 每次 API 调用发送大量 input token → micro_compact 保护 read_file 结果不替换 → auto_compact 的总结调用本身也消耗额度。所以 s06 在两个 API 调用点（主循环 + auto_compact 总结）都加了重试包装：捕获 429 → 等 60 秒 → 重试（最多 3 次）。这不是 s06 的核心概念，但没有它教学演示会半途崩溃，看不到压缩管道的效果。生产环境应该用指数退避（exponential backoff）而不是固定等待。

7. **这就是 Claude Code 里 context compact 的原理。** 当你在 Claude Code 里看到 `"Conversation compressed"` 提示，背后就是这个三层管道。Claude Code 的实现更复杂（多种压缩策略、token 精确计算、多种 transcript 格式），但核心思路一致。
