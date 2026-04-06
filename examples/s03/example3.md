# s03 实际运行追踪（例 3）：开放式任务 + 崩溃

> prompt: `Review all Python files and fix any style issues`
>
> 结果：6 轮 LLM 调用后崩溃（RateLimitError），LLM 读了 90,000+ 字符的源码塞满了 messages
>
> **重点观察：** 开放式任务暴露了 s03 的局限——没有上下文管理时，LLM 会往 messages 里塞太多内容，最终超限崩溃。这就是为什么 s06（Context Compact）要存在。

---

## 概览

```
轮次 1:  bash find → 列出所有 .py 文件                     正常
轮次 2:  bash cat × 3 → 读了 94,000+ 字符的源码！          3 个并行 bash 调用
轮次 3:  bash × 2 → 检查 flake8/pycodestyle → 都没装
         ⚠ nag reminder（3 轮没 todo！LLM 到现在都没规划）
轮次 4:  todo → 创建 4 个任务（2 个已标为 completed）       收到 nag 后补建
轮次 5:  正常继续...
轮次 6:  💥 RateLimitError: 30,000 input tokens per minute  崩溃
```

---

## 亮点 1：LLM 没有先规划就开干

对比例 1 和例 2，LLM 在第 1-2 轮就创建了 todo 列表。但例 3 里，LLM **直接跳过了规划，先去读文件**：

**轮次 1：**

```
──────────────────── LLM 回复 ────────────────────
response.content = [
  TextBlock: "I'll start by reviewing all Python files in the project."
  ToolUseBlock: name="bash", input={"command": "find ... -name \"*.py\" | sort"}
]
```

**轮次 2：一次调了 3 个 bash！**

```
response.content = [
  ToolUseBlock: name="bash", input={"command": "cat greet.py hello.py utils.py __init__.py ..."}
  ToolUseBlock: name="bash", input={"command": "cat agents/__init__.py agents/s01_agent_loop.py ..."}
  ToolUseBlock: name="bash", input={"command": "cat tests/__init__.py tests/test_agents_smoke.py ..."}
]
```

输出量：7,130 + 50,000 + 36,933 = **94,063 字符**的源代码塞进了 messages！

这是我们第一次看到**一个 response 里有 3 个 ToolUseBlock**。`for block in response.content` 循环跑了 3 遍，3 个 bash 结果都收集到 `results` 里，作为一条 user 消息塞回去。

---

## 亮点 2：Nag Reminder 拉回了 LLM

LLM 连续 3 轮（find → cat × 3 → flake8 × 2）没调用 todo：

```
⚠ 注入 nag reminder: <reminder>Update your todos.</reminder>
  (LLM 已经 3 轮没更新 todo 了)
```

messages 里的样子：

```
[6] user/tool_result: "neither available"
[6] user/tool_result: "/home/.../python: No module named flake8"
[6] user/text: "<reminder>Update your todos.</reminder>"
```

**轮次 4：LLM 收到 nag 后补建 todo**

```
执行: todo(items=[...4 项])
输出 (178 字符):
[x] #1: Read all Python files
[x] #2: Run automated linting (flake8/pycodestyle)
[>] #3: Identify style issues manually
[ ] #4: Fix style issues across all files

(2/4 completed)
```

**有趣的是：LLM 追溯性地把已经做过的事标为 completed。** 它创建了 4 个任务，其中 #1 和 #2 直接标为 completed（因为确实已经做了），#3 标为 in_progress。

这说明 **todo 不一定要在开始前创建**——LLM 可以事后补建并正确标注状态。但提前规划更好。用三个例子对比就能看出差别：

**例 2（提前规划）的执行节奏：**

```
轮次 1:  todo → 规划 3 个任务
轮次 3:  todo → #1 in_progress
轮次 4:  write_file → 写 __init__.py          ← 有目标地干活
轮次 5:  todo → #1 completed, #2 in_progress
轮次 6:  write_file → 写 utils.py              ← 有目标地干活
轮次 7:  todo → #2 completed, #3 in_progress
...
```

每一步都是"看白板 → 知道下一步该做什么 → 去做 → 回来打勾"。非常有条理。

**例 3（没有提前规划）的执行节奏：**

```
轮次 1:  bash find → 列出所有文件               ← 没有计划，先探索
轮次 2:  bash cat × 3 → 读了 94,000 字符       ← 没有边界，全部读进来
轮次 3:  bash flake8 × 2 → 工具没装            ← 没有优先级，随意尝试
         ⚠ nag reminder
轮次 4:  todo → 事后补建 4 个任务               ← 到这里才开始规划
```

没有 todo 引导时，LLM 像一个没有购物清单就进了超市的人——东看看西看看，什么都往购物车里丢（94,000 字符的源码），结果预算（context 窗口）先爆了。

**提前规划的三个好处：**

1. **限定范围**——LLM 知道只需要做 3 件事，不会无限发散
2. **提供顺序**——`[>]` 标记明确告诉 LLM"现在该做这个"，做完再做下一个
3. **防止遗忘**——对话变长后，前面的计划可能被淹没，但 todo 的 `render()` 输出在每次更新后都会提醒 LLM 还剩什么

例 3 的崩溃本质上就是"没有计划导致行为发散 → 读太多内容 → 超出限制"。如果 LLM 第一轮就规划了 todo，它可能会更有针对性地只读需要审查的文件，而不是一口气 `cat` 所有文件。

---

## 亮点 3：崩溃

```
──────────────────── 发送给 LLM (距上次 todo: 0 轮) ────────────────────
messages = [
  ... 25 条消息，包含 94,000+ 字符的源码 ...
]

→ 调用 client.messages.create(...)
anthropic.RateLimitError: Error code: 429 -
  This request would exceed your organization's rate limit of 30,000 input tokens per minute
```

**为什么崩溃？** 看报错信息里的关键数字：

```
rate limit of 30,000 input tokens per minute
```

**速率限制（rate limit）** 是 API 服务商对你的账号设的"流量上限"——不是单次能发多少，而是**每分钟**能发多少。你的账号每分钟最多只能发送 30,000 个 input tokens 给 `claude-sonnet-4-6`。

例 3 前面几轮已经消耗了不少 tokens（每次调 LLM 都要把完整的 messages 发过去），messages 里又累积了 94,000+ 字符的源码。短短几分钟内连续调了 6 轮 API，总 input tokens 超了限制。

**速率限制和什么有关？**

| 因素 | 影响 |
|---|---|
| 模型 | 不同模型有不同的限制，通常越强的模型限制越紧 |
| 账号等级 | 免费试用 < 付费入门 < 企业级，额度差很多 |
| 限制维度 | 通常有两个：每分钟 tokens 数（TPM）和每分钟请求次数（RPM） |

这不是代码 bug，而是**设计局限**：s03 没有上下文管理。messages 只增不减，每次调 API 都带上全部历史，直到超限。解决方法要么升级账号额度，要么减少每次发给 API 的 tokens 数——这正是 s06 Context Compact 做的事。

---

## 教训：为什么 s06 Context Compact 必须存在

| 问题 | s03 的表现 | s06 怎么解决 |
|---|---|---|
| messages 无限增长 | 94,000 字符塞进 messages → 崩溃 | 自动压缩：token 数超阈值时总结前面的对话 |
| 长 tool_result | `cat` 输出 50,000 字符原样保留 | micro_compact：截断过长的 tool_result |
| 没有上下文预算 | LLM 一次读完所有文件 | auto_compact：在 token 数 > 50k 时自动触发 |

**s03 的 TodoManager 管理的是"做什么"（任务状态），不管理"记住什么"（上下文大小）。这两个是不同的问题，分别在 s03 和 s06 解决。**

---

## 三个例子的完整对比

| | 例 1 | 例 2 | 例 3 |
|---|---|---|---|
| prompt | 重构单文件 | 创建多文件包 | 审查所有文件 |
| 任务范围 | 明确（3 步） | 明确（3 个文件） | **开放式** |
| LLM 先规划吗？ | 第 2 轮 todo | 第 1 轮 todo | **第 4 轮才 todo（被 nag 催的）** |
| "Only one in_progress" 错误 | 是 | 是 | 否（没机会犯，todo 来得太晚） |
| Nag reminder | 未触发 | **2 次** | **1 次** |
| 读入的数据量 | 14 字符 | ~8,500 字符 | **94,000+ 字符** |
| 结果 | 成功 (3/3) | 成功 (3/3) | **崩溃 (RateLimitError)** |
| 核心教训 | LLM 从错误中学习 | todo 生命周期 + nag 有效 | **需要上下文管理** |

**核心洞察：**

1. **开放式任务比明确任务难得多。** "重构 hello.py"有明确的 3 步，LLM 很容易规划。"审查所有文件"没有边界——有多少文件？每个文件检查什么？修到什么程度算完？LLM 不知道，所以它选择了最暴力的方式：全部读进来再说。这在人类工作中也很常见——任务越模糊，越容易做无用功。

2. **LLM 不一定先规划。** 例 1 和例 2 里 LLM 都在前 1-2 轮就创建了 todo，但例 3 里它直接跳过规划去读文件了。为什么？可能因为"Review all Python files"这个 prompt 暗示了"先看看有什么"，LLM 觉得不看完所有文件就没法规划。nag reminder 是一个软约束——它提醒 LLM"你忘了更新 todo"，但不能强制 LLM 在第一轮就创建 todo。如果你想让 LLM 必须先规划，需要在 system prompt 里写更强的指令，或者用硬约束（代码层面检查第一轮是否调了 todo）。

3. **todo 管理进度，不管理上下文。** 这是 s03 最根本的局限。TodoManager 知道"3 个任务完成了 2 个"，但它不知道也不关心 messages 列表有多大。即使 todo 状态是 3/3 completed，messages 里的 94,000 字符不会消失——它们会一直被带在每次 API 调用里，直到超限。进度管理和上下文管理是两个独立的问题。

---

## 展望：后续课程如何解决这些问题

例 3 暴露的每个问题，在后面的课程里都有对应的解决方案：

| 例 3 暴露的问题 | 哪一课解决 | 怎么解决 |
|---|---|---|
| messages 无限膨胀 → 超限崩溃 | **s06 Context Compact** | 三层压缩：截断过长的 tool_result、自动总结旧对话、手动触发压缩 |
| todo 状态在对话压缩后会丢失 | **s07 Task System** | 任务状态持久化到 `.tasks/` 目录的 JSON 文件，压缩也丢不掉 |
| 单个 Agent 读 94,000 字符全塞进自己的 messages | **s04 Subagent** | 子 Agent 用独立的 messages 处理子任务，只返回摘要给父 Agent，不污染主对话 |
| 开放式任务 LLM 不知道边界 | **s05 Skill Loading** | 按需加载知识/指令，不把所有东西一次性塞进 system prompt |
| 多文件任务串行执行太慢 | **s08 Background Tasks** | 耗时命令放后台线程，Agent 可以同时做别的事 |

可以把后续课程想象成一条**打补丁的链条**：

```
s03 的问题                    对应的补丁
─────────────                ──────────
messages 太大 ──────────────→ s06 压缩上下文
todo 被压缩丢了 ────────────→ s07 持久化任务
一个 Agent 扛所有 ──────────→ s04 子 Agent 分担
不知道该读哪些文件 ─────────→ s05 按需加载
一个个串行干活太慢 ─────────→ s08 后台并行
```

**s03 不是终点——它暴露了 Agent 在真实场景中会遇到的问题，后面的每一课都在解决其中一个。** 这就是为什么这个系列要从 s01 一路讲到 s12。
