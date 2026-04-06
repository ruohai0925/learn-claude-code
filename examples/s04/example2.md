# s04 实际运行追踪：子 Agent 读所有 .py 文件（压力转嫁的活例子）

> prompt: `Delegate: read all .py files and summarize what each one does`
>
> 结果：父 Agent 2 轮（第 2 轮崩溃），子 Agent 3 轮。子 Agent 成功返回 6407 字符摘要，但父 Agent 在收到摘要后调 LLM 时触发 **rate limit**。
>
> **重点观察：** 子 Agent 一次性读了 27 个 .py 文件（~250,000 字符），消耗了大量 API token 额度。父 Agent 的 messages 虽然只有 3 条，但 rate limit 是**共享的**——子 Agent 烧掉的额度，父 Agent 也用不了。这就是讲义里说的"压力转嫁"。

---

## 启动 + 用户输入

**终端输出：**

```
s04 >> Delegate: read all .py files and summarize what each one does

────────────────── 用户输入 ──────────────────
query = "Delegate: read all .py files and summarize what each one does"
```

用户说 `Delegate`——明确要求用子 Agent。任务是读**所有** `.py` 文件。这个项目有 27 个 `.py` 文件，内容加起来超过 250,000 字符。回忆 s03 例 3 的教训：94,000 字符就崩了。这次更猛。

---

## 父 Agent 第 1 轮：派发子任务

**终端输出：**

```
────────────────── 父 Agent 轮次 1 ──────────────────
messages = [
  [0] user: "Delegate: read all .py files and summarize what each one does"
]

→ 调用 client.messages.create(...)

────────────────── 父 Agent 轮次 1: 回复 ──────────────────
response.stop_reason = "tool_use"
response.content = [
  ToolUseBlock: name="task", id="toolu_01JsaWNHs93yMG7VV7zv8iCv"
    input={"description": "Read all .py files and summarize each one", "prompt": "Go to /home/yzeng/Codes/learn-claude-code and find all .py files. Read each one and provide a summary of what each file does. Be...
]
```

**解读：** 父 Agent 立刻使用 `task` 工具——一切看起来和例 1 一样正常。父 Agent 的 messages 只有 1 条，非常干净。

---

## 子 Agent 第 1 轮：找到 27 个 .py 文件

**终端输出：**

```
  │ ────────────────── 子 Agent 轮次 1 ──────────────────
  │ messages = [
  │   [0] user: "Go to /home/yzeng/Codes/learn-claude-code and find all .py files. Read each one ..."
  │ ]
  │ → 调用 client.messages.create(...)

  │ ────────────────── 子 Agent 轮次 1: 回复 ──────────────────
  │ response.stop_reason = "tool_use"
  │ response.content = [
  │   ToolUseBlock: name="bash", id="toolu_01LivU9u1bZhAEQ5DyshTynu"
  │     input={"command": "find /home/yzeng/Codes/learn-claude-code -name \"*.py\" -type f"}
  │ ]

  │ ────────────────── 子 Agent 轮次 1: 执行工具 ──────────────────
  │ 执行: bash({"command": "find ... -name \"*.py\" -type f"})
  │ 输出 (1776 字符): /home/yzeng/Codes/learn-claude-code/agents/s10_team_protocols.py
  /home/yzeng/Codes/learn-claude-code/agents/s12_worktree_task_isolation.py
  /home/yzeng/Codes/learn-claude-code/agents/s05_skill_loading.
  ...
```

**解读：** 子 Agent 的第一步很合理：先用 `bash find` 列出所有 `.py` 文件。返回了 27 个文件路径，共 1776 字符。到这里一切正常。

---

## 子 Agent 第 2 轮：一次读 27 个文件（灾难的伏笔）

**终端输出：**

```
  │ ────────────────── 子 Agent 轮次 2: 回复 ──────────────────
  │ response.stop_reason = "tool_use"
  │ response.content = [
  │   ToolUseBlock: name="read_file"  →  agents/s10_team_protocols.py
  │   ToolUseBlock: name="read_file"  →  agents/s12_worktree_task_isolation.py
  │   ToolUseBlock: name="read_file"  →  agents/s05_skill_loading.py
  │   ToolUseBlock: name="read_file"  →  agents/s_full.py
  │   ToolUseBlock: name="read_file"  →  agents/s03_todo_write.py
  │   ToolUseBlock: name="read_file"  →  agents/s02_tool_use.py
  │   ToolUseBlock: name="read_file"  →  agents/s09_agent_teams.py
  │   ToolUseBlock: name="read_file"  →  agents/s06_context_compact.py
  │   ToolUseBlock: name="read_file"  →  agents/__init__.py
  │   ToolUseBlock: name="read_file"  →  agents/s08_background_tasks.py
  │   ToolUseBlock: name="read_file"  →  agents/s04_subagent.py
  │   ToolUseBlock: name="read_file"  →  agents/s11_autonomous_agents.py
  │   ToolUseBlock: name="read_file"  →  agents/s01_agent_loop.py
  │   ToolUseBlock: name="read_file"  →  agents/s07_task_system.py
  │   ToolUseBlock: name="read_file"  →  tests/test_agents_smoke.py
  │   ToolUseBlock: name="read_file"  →  tests/test_s_full_background.py
  │   ToolUseBlock: name="read_file"  →  skills/agent-builder/scripts/init_agent.py
  │   ToolUseBlock: name="read_file"  →  skills/agent-builder/references/minimal-agent.py
  │   ToolUseBlock: name="read_file"  →  skills/agent-builder/references/subagent-pattern.py
  │   ToolUseBlock: name="read_file"  →  skills/agent-builder/references/tool-templates.py
  │   ToolUseBlock: name="read_file"  →  examples/s03/tests/test_utils.py
  │   ToolUseBlock: name="read_file"  →  examples/s03/utils.py
  │   ToolUseBlock: name="read_file"  →  examples/s03/hello.py
  │   ToolUseBlock: name="read_file"  →  examples/s02/greet.py
  │   ToolUseBlock: name="read_file"  →  examples/ansi_to_html.py
  │   ToolUseBlock: name="read_file"  →  examples/s03/__init__.py
  │   ToolUseBlock: name="read_file"  →  examples/s03/tests/__init__.py
  │ ]
```

**解读：** **27 个 `read_file` 并行调用！** 子 Agent 决定一口气全读了。

这是 LLM "并行工具调用"能力的一个**极端案例**——它一次返回了 27 个 `ToolUseBlock`。我们的 harness 逐个执行，把 27 个文件的内容全部收集到 `results` 里：

```
  │ 执行: read_file → s10_team_protocols.py    (21028 字符)
  │ 执行: read_file → s12_worktree_task_isolation.py (25882 字符)
  │ 执行: read_file → s05_skill_loading.py     (8523 字符)
  │ 执行: read_file → s_full.py                (36454 字符)  ← 最大的一个
  │ 执行: read_file → s03_todo_write.py        (15164 字符)
  │ 执行: read_file → s02_tool_use.py          (11548 字符)
  │ ...
```

**粗算总量：** 27 个文件的内容加起来超过 **250,000 字符**。这些全部以 `tool_result` 的形式塞进了子 Agent 的 `sub_messages`。

**对比 s03 例 3 的 94,000 字符——这次是它的 2.5 倍以上。**

**此时子 Agent 的 sub_messages 结构：**

| 消息索引 | 角色 | 内容 | 大小估算 |
|---|---|---|---|
| [0] | user | prompt | ~100 字符 |
| [1] | assistant | bash tool_use | ~200 字符 |
| [2] | user | tool_result（find 输出） | ~1,776 字符 |
| [3] | assistant | 27 个 read_file tool_use | ~5,000 字符 |
| [4] | user | **27 个 tool_result** | **~250,000 字符** |

第 [4] 条消息就是灾难的根源——一条消息里塞了 27 个文件的完整内容。

---

## 子 Agent 第 3 轮：居然成功了

**终端输出：**

```
  │ ────────────────── 子 Agent 轮次 3: 回复 ──────────────────
  │ response.stop_reason = "end_turn"
  │ response.content = [
  │   TextBlock: "Here is a summary of all 27 `.py` files found in the project:
  │
  │   ---
  │
  │   ## agents/ — Core Agent Harness Implementations
  │   ..."
  │ ]

  │ ────────────────── 子 Agent 结束 ──────────────────
  │ 共 3 轮，子 Agent messages 有 6 条 → 全部丢弃
  │ 只返回摘要 (6407 字符):
  │ Here is a summary of all 27 `.py` files found in the project:
  │ ...
──────────────────────────────────────────────────
子任务完成，摘要返回给父 Agent (6407 字符)
```

**解读：** 子 Agent 居然没崩！它成功地把 250,000+ 字符的文件内容消化成了 6407 字符的摘要。从"信息压缩"的角度看，这是 **40:1** 的压缩比。

但代价是什么？子 Agent 的第 3 轮调用向 API 发送了 250,000+ 字符的 `sub_messages`——这消耗了大量的 input token 额度。

**"全部丢弃"——子 Agent 的 6 条 messages 不再存在。** 如果故事到这里结束，这就是一个完美的上下文隔离案例。但是...

---

## 父 Agent 第 2 轮：崩了——rate limit

**终端输出：**

```
────────────────── 父 Agent 轮次 2 ──────────────────
messages = [
  [0] user: "Delegate: read all .py files and summarize what each one does"
  [1] assistant/tool_use: task({"description": "Read all .py files and summarize each one", "prompt": "Go to /h)
  [2] user/tool_result: "Here is a summary of all 27 `.py` files found in the project:

---

## agents..."
]

→ 调用 client.messages.create(...)
```

```
anthropic.RateLimitError: Error code: 429 - {'type': 'error', 'error': {'type': 'rate_limit_error',
'message': "This request would exceed your organization's rate limit of 30,000 input tokens per minute
(org: ..., model: claude-sonnet-4-6). ... Please reduce the prompt length or the maximum tokens requested,
or try again later."}}
```

**解读：** 父 Agent 的 messages 只有 3 条——完全不大。它发给 LLM 的 input token 远不到 30,000。但 API 报错说**已经超过了每分钟 30,000 input token 的限制**。

为什么？因为子 Agent 刚刚用掉了几乎所有的额度。

---

## 崩溃原因分析：rate limit 是共享的

```
父 Agent 和子 Agent 共用同一个 API client → 共享同一个 API key → 共享同一个 rate limit
```

时间线：

```
子 Agent 轮次 1:  发送 ~1,000 token   (prompt)           ← API 扣额度
子 Agent 轮次 2:  发送 ~3,000 token   (prompt + find输出) ← API 扣额度
子 Agent 轮次 3:  发送 ~80,000 token  (prompt + 全部文件) ← API 扣额度!!! 
                                                           (30,000/分钟 限额直接爆表)
父 Agent 轮次 2:  发送 ~2,000 token   (3条消息)          ← 429! 额度已用完
```

子 Agent 的第 3 轮把 250,000+ 字符的 `sub_messages` 发送给了 API。具体消耗了多少 input token？我们不知道确切数字——token 数取决于 Claude 的 tokenizer 怎么切分这些内容（英文散文大约 4 字符/token，代码通常更短，约 2.5-3.5 字符/token，文件路径又不一样）。但不管怎么算，25 万字符至少是数万 token，远超 30,000 的每分钟限额。API 记住了这个消耗，所以父 Agent 紧接着的调用就被拒绝了。

**这就是讲义里说的"压力转嫁"：**

| 维度 | s03 例 3（无子 Agent） | s04 例 2（有子 Agent） |
|---|---|---|
| 谁的 messages 膨胀？ | 父 Agent | 子 Agent |
| context 问题解决了？ | 没有 | **是的**——父 Agent 只有 3 条 messages |
| API 消耗减少了？ | — | **没有**——子 Agent 一样要发送大量 token |
| 最终结果 | messages 崩溃 | **rate limit 崩溃** |

**子 Agent 解决的是上下文隔离问题，不是数据量问题。** 数据量问题需要**分治**——比如把 27 个文件拆成多个子 Agent，每个读几个。

---

## 如果要修复：分治策略

一种可能的改进（超出 s04 范围，但值得思考）：

```
父 Agent:  "请 3 个子 Agent 分别 review 不同的文件"
  → task 1: "Read agents/s01 - s04 and summarize"
  → task 2: "Read agents/s05 - s09 and summarize"
  → task 3: "Read agents/s10 - s12, tests, skills and summarize"

每个子 Agent 只读 ~8 个文件，单个子 Agent 的 context 可控。
```

这样做解决了 **context 膨胀**问题——每个子 Agent 的 `sub_messages` 不会撑爆。但 **rate limit 问题不一定能解决**。当前的 s04 代码里，多个 `task` 是串行执行的（`for block in response.content` 是顺序循环），如果 3 个子 Agent 跑得都很快、恰好都在同一个分钟窗口内完成，它们消耗的 input token 加起来照样超过 30,000/分钟的限额——分治并不自动分散 rate limit。

真正要解决 rate limit，需要的是**限速**（比如在子 Agent 之间加 `time.sleep()`、或用 token bucket 算法控制发送速率），而不仅仅是拆分任务。分治解决的是"单次请求太大"，限速解决的是"单位时间请求太多"——两个不同的问题。

---

## 这个例子的关键收获

1. **子 Agent 和父 Agent 共享 rate limit。** 因为它们用同一个 `client`（API key），子 Agent 消耗的 token 额度会挤占父 Agent 的额度。上下文隔离了，但 API 额度没有隔离。

2. **子 Agent 不能解决"数据量太大"的根本问题。** 把 250,000 字符从父 Agent 转移到子 Agent，子 Agent 一样要把这些字符发送给 API。真正的解法是**减少每次发送的数据量**（分治、摘要、增量读取）。

3. **LLM 的"一口气全读"策略有风险。** 子 Agent 选择了一次性并行读取 27 个文件，而不是分批读取。这是 LLM 追求效率的本能，但在 token 有限的场景下是一个糟糕的策略。如果 system prompt 里加一句 `"Read files in batches of 5 to avoid overloading"`，可能就不会崩。

4. **错误发生在"返回后"，不是"读取时"。** 子 Agent 成功完成了任务并返回了摘要。崩溃发生在父 Agent 的下一次 API 调用——因为 rate limit 有延迟效应。这种"延迟崩溃"比"当场崩溃"更难排查。

5. **这就是为什么生产级 Agent 需要 rate limit 管理。** Claude Code 内部有复杂的 token budget 管理和 retry 逻辑。我们的 s04 没有——崩了就是崩了。
