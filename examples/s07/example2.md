# s07 实际运行追踪：列出所有任务并渲染依赖图

> prompt: `List all tasks and show the dependency graph`
>
> 结果：2 轮。第 1 轮 LLM 调一次 `task_list`（不带任何参数）拿回扁平的 9 字符状态行；第 2 轮 LLM 把这几行**翻译**成 markdown 表格 + ASCII 依赖图，然后 `end_turn`。
>
> **重点观察：** ① `task_list` 返回的是一个**人类可读的文本块**而不是 JSON——只有 96 字符，但 LLM 能从里面解析出 ID、状态、依赖关系。② **messages 数组现在包含上一次 example1 的全部对话**（看 `messages = [...]` 里第 0 条到第 5 条都是上次的内容）——这是 `s07_task_system.py:487-500` 的 `history` 列表跨 prompt 累积的结果，**和磁盘上 .tasks/ 的持久化是两回事**。

---

## 第 1 轮：单个 task_list 调用

**终端输出：**

```
s07 >> List all tasks and show the dependency graph

────────────────── 用户输入 ──────────────────
query = "List all tasks and show the dependency graph"

────────────────── 轮次 1 ──────────────────
messages = [
  [0] user: "Create 3 tasks: ..."                                  ← 来自 example1
  [1] assistant/text: "I'll create all 3 tasks simultaneously..."  ← 来自 example1
  [1] assistant/tool_use: task_create({"subject": "Setup project"})
  [1] assistant/tool_use: task_create({"subject": "Write code"})
  [1] assistant/tool_use: task_create({"subject": "Write tests"})
  [2] user/tool_result: ...
  [3] assistant/text: "All 3 tasks are created! Now I'll set up..."
  [3] assistant/tool_use: task_update({"task_id": 2, "addBlockedBy": [1]})
  [3] assistant/tool_use: task_update({"task_id": 3, "addBlockedBy": [2]})
  [4] user/tool_result: ...
  [5] assistant/text: "All done! Here's a summary..."               ← example1 的最终回答
  [6] user: "List all tasks and show the dependency graph"          ← 这次的 prompt
]
```

**解读：messages 不是空的——这是 s07 example2 最重要的细节。**

s07 的主循环用一个 `history` 列表（`s07_task_system.py:487`）跨 prompt 累积。每次你按回车提交一个新 prompt，新的 user message 被 append 到 history 末尾，**而不是开新对话**。所以这一轮 LLM 看到的 messages 包含了 example1 的全部 7 条消息 + 这次新的 user prompt。

**这是"内存里的对话历史"，和"磁盘上的 .tasks/"是两个独立的持久化层：**

| 持久化层 | 存在哪里 | 跨 prompt | 跨重启 |
|---|---|---|---|
| `history` 列表（messages） | Python 进程内存 | ✅ 累积 | ❌ 进程退出就丢 |
| `.tasks/` 目录（任务 JSON） | 磁盘文件 | ✅ 累积 | ✅ 重启后还在 |

example1 已经退出过吗？**没有**——这一节是在同一个 Python 进程里、同一个 REPL session 里跑的。所以 history 还在内存里。**但** 即使你 Ctrl-D 退出 example1 的进程，再开新进程跑这个 prompt：history 会**清空**（重新从空列表开始），但 `.tasks/` 里的 task_1/2/3 **还在**——下一次启动时 `_max_id()` 会从磁盘读到它们。**这正是 example3、example4 启动时 verbose 顶部 "启动时已有任务" 那一段的来源。**

记住这个区别——它是理解 s07 持久化设计的钥匙。

---

**LLM 的回复（轮次 1）：**

```
────────────────── 轮次 1: 回复 ──────────────────
response.stop_reason = "tool_use"
response.content = [
  ToolUseBlock: name="task_list", id="toolu_014n..."
    input={}
]
```

**解读：** **没有 TextBlock**——LLM 直接进入工具调用，连一句"Let me list the tasks"都没说。这很常见：当任务很机械（"列一下"），LLM 会跳过解释直接动手。

`input={}` —— task_list 的 schema（`s07_task_system.py:403-404`）是 `{"type": "object", "properties": {}}`，**没有任何参数**。这是 4 个 task 工具里最简单的一个：不需要 task_id、不需要任何过滤条件，就一个动作"列出全部"。

**工具执行：**

```
────────────────── 轮次 1: 执行工具 ──────────────────
执行: task_list({})
输出 (96 字符): [ ] #1: Setup project
[ ] #2: Write code (blocked by: [1])
[ ] #3: Write tests (blocked by: [2])

.tasks/ 目录状态：
  task_1.json: [ ] #1 "Setup project"
  task_2.json: [ ] #2 "Write code" blockedBy=[1]
  task_3.json: [ ] #3 "Write tests" blockedBy=[2]
```

**解读：** 看清楚 `task_list` 的输出格式（`TaskManager.list_all()`，`s07_task_system.py:293-308`）：

```
[ ] #1: Setup project
[ ] #2: Write code (blocked by: [1])
[ ] #3: Write tests (blocked by: [2])
```

**这是给 LLM 看的"报告"，不是 JSON。** marker 用 `[ ]` / `[>]` / `[x]` 三种字符，依赖用括号 `(blocked by: [...])` 表示。整个输出只有 96 字符——比三个 JSON 文件加起来短得多。

为什么不直接返回 JSON 让 LLM 解析？因为：

1. **更省 token**——三个 JSON 大概要 ~360 字符，文本格式只要 96 字符，省了 75%。
2. **更适合 LLM 阅读**——文本格式是 LLM 训练数据里常见的"checklist"形态，无需解析就能理解。
3. **list_all 是给 LLM 看"全局"用的**，不是给 LLM 拿数据做精细操作的；要操作单个任务的字段，应该用 `task_get` 拿到完整 JSON。**list_all 和 get 是分工的——一个粗看、一个细查**。换句话说，list_all 回答的是 "**有什么 / 卡在哪**"，task_get 回答的是 "**这一条具体长什么样**"——前者像在飞机上鸟瞰一座城市看路网形状，后者像走进某栋楼里看门牌号和房间布局。这种"先粗后细"的分工还有一个隐藏好处：它把"扫描成本"和"细节成本"分开了——`list_all` 永远是 O(N) 的轻量扫描（每个任务只读 marker + subject + blockedBy 三个字段），`task_get` 才会一次性吐出某个任务的全部字段（含 description、owner 等）。LLM 可以放心地频繁 list 而不怕 context 爆炸，发现感兴趣的任务后再用 get 钻进去——就像浏览器用列表页 + 详情页两层加载，而不是把所有商品的完整属性塞进列表页。

**注意：** verbose 输出末尾的 `.tasks/ 目录状态` 和 task_list 的 96 字符返回值**几乎一模一样**——这不是巧合，是因为 `print_tasks_dir()` 用的格式和 `list_all()` 是同一套。两者读的也是同一组文件。差别只在 `print_tasks_dir` 多打了文件名前缀（`task_N.json:`）。

---

## 第 2 轮：LLM 把扁平输出渲染成依赖图

**终端输出：**

```
────────────────── 轮次 2: 回复 ──────────────────
response.stop_reason = "end_turn"
response.content = [
  TextBlock: "Here are all the tasks and their dependency graph:

### Task List
| ID | Task | Status | Blocked By |
|----|------|------------|
..."
]
```

**解读：** `stop_reason = "end_turn"`——只用了 1 次工具就直接收尾。

**最终回答：**

````
Here are all the tasks and their dependency graph:

### Task List
| ID | Task | Status | Blocked By |
|----|------|--------|------------|
| 1 | Setup project | ⬜ Pending | — |
| 2 | Write code | ⬜ Pending | #1 |
| 3 | Write tests | ⬜ Pending | #2 |

### Dependency Graph
```
#1 Setup project
        │
        ▼
#2 Write code
        │
        ▼
#3 Write tests
```

All 3 tasks are currently **pending**. The chain is linear — each task unlocks the next, so the only task available to start right now is **#1 Setup project**.
````

**解读：这就是"LLM 作为渲染层"的能力。** task_list 给的是一行行扁平文本，LLM 把它转成了三种表达：

1. **markdown 表格** —— 用 emoji ⬜ 替换文本 marker `[ ]`，把 `(blocked by: [N])` 改成 `#N`
2. **ASCII 依赖图** —— 用 │ 和 ▼ 画出顺序，让"链"的形态肉眼可见
3. **结论摘要** —— "available to start right now is #1 Setup project"——这是 LLM 自己**推理**出来的（task_list 没显式说"哪些可以开始"，但 LLM 看到 task_1 没有 `(blocked by: ...)` 后面跟着的依赖，就知道它是入口）

**这是 [s07 讲义](../../docs/zh/s07-lecture-notes.md) "概念 2: blockedBy" 提到的"图能回答三个问题"的具体实现：**

| 问题 | LLM 怎么回答 |
|---|---|
| What's ready? | 看哪个 task 没有 `blocked by` —— "the only task available to start right now is #1" |
| What's blocked? | 看哪个 task 有 `blocked by` —— task_2 和 task_3 |
| What can run in parallel? | 这个例子里没有，链结构没有并行——example4 才会出现 |

**关键认知：TaskManager 不需要实现"What's ready"这种查询接口——LLM 自己会从 list_all 输出推理出来。** 这是把"图论查询"外包给 LLM 的典型例子，让 TaskManager 保持极简。

---

## 这个例子的关键收获

1. **task_list 的输出格式是给 LLM 看的"checklist"，不是 JSON。** 96 字符塞下了 3 个任务的关键信息（id/status/dependency）——比 JSON 省 75% 的 token。这是一个**"为消费者格式化"** 的设计典范：知道下游是 LLM，就用 LLM 最容易消化的格式（checklist 文本），而不是机器最容易解析的格式（JSON）。

2. **list 和 get 是分工的：list_all 给全局粗看，get 给单个细查。** 想看整个 .tasks/ 状态？用 list_all。想看 task_2 的完整字段（description、owner 等）？用 task_get。这种"粗-细"分工避免了 list_all 输出爆炸。

3. **history 列表（内存）和 .tasks/ 目录（磁盘）是两个独立的持久化层。** history 跨 prompt 累积、跨重启清空；.tasks/ 跨 prompt 累积、跨重启保留。**这两层是 s07 持久化设计的核心区分**——messages 是"对话连续性"，文件系统是"任务连续性"。s06 的 context compact 是为"对话连续性"做的；s07 的文件系统是为"任务连续性"做的。两者解决不同问题。

4. **LLM 是图的"渲染层和查询层"。** TaskManager 只存了 ID 和 blockedBy 数组——它不画图、不算"哪些 ready"、不输出 emoji。这些全部是 LLM 在最终回复里现场加工出来的。**这种分工让 TaskManager 可以保持几十行代码的简洁，而把"用户友好"外包给 LLM 的天然能力**。这是 LLM 工具系统设计的一个反直觉点：**不要在工具里做 LLM 已经擅长的事**。

5. **没有 TextBlock 也是合法的回复。** 第 1 轮 LLM 直接返回 ToolUseBlock 而没有任何前导文字。这告诉我们 Anthropic API 允许 assistant message content 是纯工具调用的列表——`stop_reason="tool_use"` 时不需要有 TextBlock。这在简单/机械任务里是常见的，LLM 会"少废话直接干"。

---

> **下一例：** [example3.md](example3.md) —— 让 LLM 完成 task_1，亲眼看 `_clear_dependency` 自动解除 task_2 的阻塞。
