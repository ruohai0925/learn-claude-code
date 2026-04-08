# s07 实际运行追踪：菱形 DAG（parse → transform/emit → test）

> prompt: `Create a task board for refactoring: parse → transform → emit → test, where transform and emit can run in parallel after parse`
>
> 结果：3 轮。第 1 轮 LLM 一口气并行 4 个 `task_create`（task_4..7，**ID 从 4 开始**！）；第 2 轮一口气并行 3 个 `task_update` 把依赖图建成菱形（task_5/6 各自依赖 task_4，task_7 依赖 task_5/6）；第 3 轮 `end_turn` 输出带 ASCII 菱形图的 task board。
>
> **重点观察：** ① **新任务 ID 从 4 开始**——这是 example1-3 留下的"考古层"。`.tasks/` 里现在同时有 example1 的 task_1/2/3 和这次的 task_4..7，跨 prompt 的累积达到了顶峰。② 菱形 DAG 是 s07 第一次真正展示"逻辑并行"——task_5 和 task_6 在依赖图上是同一层、可以并行，但 s07 还是顺序执行的（参见 [s07 讲义](../../docs/zh/s07-lecture-notes.md) "概念 2" 末尾的"s07 是地图，s08/s12 是车队"）。③ task_update 的 `addBlockedBy` 在这一轮第一次出现 `[5, 6]` 这种**多元素**列表——表达"等多个前置都完成才能开始"。

---

## 第 1 轮：并行创建 4 个新任务

**终端输出（messages 数组省略，只看回复和执行）：**

```
────────────────── 轮次 1: 回复 ──────────────────
response.stop_reason = "tool_use"
response.content = [
  TextBlock: "I'll create all 4 tasks simultaneously first!"
  ToolUseBlock: name="task_create", input={"subject": "Parse"}
  ToolUseBlock: name="task_create", input={"subject": "Transform"}
  ToolUseBlock: name="task_create", input={"subject": "Emit"}
  ToolUseBlock: name="task_create", input={"subject": "Test"}
]

────────────────── 轮次 1: 执行工具 ──────────────────
  创建 task_4.json: "Parse"        ← 注意 ID 是 4，不是 1
执行: task_create({"subject": "Parse"})
输出: {"id": 4, "subject": "Parse", ...}
  创建 task_5.json: "Transform"
执行: task_create({"subject": "Transform"})
输出: {"id": 5, ...}
  创建 task_6.json: "Emit"
执行: task_create({"subject": "Emit"})
输出: {"id": 6, ...}
  创建 task_7.json: "Test"
执行: task_create({"subject": "Test"})
输出: {"id": 7, ...}

.tasks/ 目录状态：
  task_1.json: [x] #1 "Setup project"          ← example1 + example3 留下的
  task_2.json: [ ] #2 "Write code"             ← example1 留下的（在 example3 里被解锁）
  task_3.json: [ ] #3 "Write tests" blockedBy=[2]  ← example1 留下的
  task_4.json: [ ] #4 "Parse"                   ← 这次新建
  task_5.json: [ ] #5 "Transform"               ← 这次新建
  task_6.json: [ ] #6 "Emit"                    ← 这次新建
  task_7.json: [ ] #7 "Test"                    ← 这次新建
```

**解读：这一段最关键的观察是 task ID 的连续性。**

新建的 4 个任务 ID 是 **4, 5, 6, 7**——**不是 1, 2, 3, 4**。为什么？因为这一节是在同一个 Python 进程里跑的，TaskManager 实例是同一个，它的 `_next_id` 字段已经在 example1 推到了 4（example1 创建了 1/2/3，`_next_id` 加到 4），example2 和 example3 没有创建新任务（只 update/list），所以 `_next_id` 保持在 4。这一节调用 `create()`，第一次拿 4，第二次拿 5，依此类推。

**更狠的情况：** 如果你**重启了 Python 进程**，TaskManager 在 `__init__` 里会调 `_max_id() + 1`（`s07_task_system.py:163`）扫描 `.tasks/` 找最大 ID（是 3）然后 +1 → 还是从 4 开始。**重启不重启，对这个例子的结果没影响——因为 `.tasks/` 里的最大 ID 已经是 3**。

**这就是讲义里反复强调的"持久化"在你眼皮底下的具体表现：** 进程死活无关紧要，磁盘上的状态决定了下一个 ID。这是 s07 区别于 s03 TodoManager 的根本——s03 重启 ID 重置为 1，s07 不会。

**.tasks/ 目录现在有 7 个文件**：

```
task_1.json: [x] #1 "Setup project"           ← 历史考古层 ↓
task_2.json: [ ] #2 "Write code"
task_3.json: [ ] #3 "Write tests" blockedBy=[2]
task_4.json: [ ] #4 "Parse"                    ← 这次的新任务 ↓
task_5.json: [ ] #5 "Transform"
task_6.json: [ ] #6 "Emit"
task_7.json: [ ] #7 "Test"
```

**两组任务彼此不相干**——task_1..3 是 "Setup/Code/Test" 的链，task_4..7 是 "Parse/Transform/Emit/Test" 的菱形管道，它们之间没有任何依赖。但它们**共享同一个 .tasks/ 目录**。这是 s07 的一个有趣性质：**任务系统不强制"工作单元"的边界**——你可以同时跑 N 个互不相干的任务图，TaskManager 不在乎，因为它只看 ID 和 blockedBy。

**这暗示了 s09+ 多 Agent 协作的一个模式：** 多个 Agent 共享 `.tasks/`，每个 Agent 通过 `owner` 字段标记"这是我的任务"，互相不用知道彼此的存在——靠 ID 和 owner 隔离工作单元。

---

## 第 2 轮：并行 3 个 task_update 建菱形依赖

**终端输出：**

```
────────────────── 轮次 2: 回复 ──────────────────
response.stop_reason = "tool_use"
response.content = [
  TextBlock: "All 4 tasks created! Now I'll wire up the dependencies — Transform and Emit both blocked by Parse, and Test blocked by both Transform and Emit."
  ToolUseBlock: name="task_update", input={"task_id": 5, "addBlockedBy": [4]}
  ToolUseBlock: name="task_update", input={"task_id": 6, "addBlockedBy": [4]}
  ToolUseBlock: name="task_update", input={"task_id": 7, "addBlockedBy": [5, 6]}     ← 多元素！
]
```

**解读：** 三个并行的 task_update，每一个表达一条依赖边：

- `task_5: addBlockedBy=[4]` —— Transform 被 Parse 阻塞
- `task_6: addBlockedBy=[4]` —— Emit 也被 Parse 阻塞
- `task_7: addBlockedBy=[5, 6]` —— **Test 被 Transform 和 Emit 同时阻塞**

**`[5, 6]` 是这一例最关键的细节**——它表达 "AND"（合取）依赖：task_7 必须等 task_5 **和** task_6 **都**完成。这种"等多个前置"是 DAG 比简单链表强的地方。

**`addBlockedBy` 用 list 而不是 single int 的原因正是为了支持这一点。** 看 schema（`s07_task_system.py:402`）：

```python
"addBlockedBy": {"type": "array", "items": {"type": "integer"}}
```

`type: "array"` 强制了它是列表。如果你只传一个依赖，你也得包成 `[N]`。这是接口的"未来证明"——一开始就允许多依赖。

**那 OR 依赖（"等任一前置完成"）能表达吗？** —— **不能。** s07 的 blockedBy 只表达 AND——必须**全部**前置完成才解锁。如果你想表达"task_7 等 task_5 OR task_6 任一完成就开始"，s07 没有原语。这是有意的简化：DAG 里的边天然是 AND，OR 通常通过额外的"哑节点"实现。

**工具执行：**

```
────────────────── 轮次 2: 执行工具 ──────────────────
  task_5: blockedBy [] → [4]
执行: task_update({"task_id": 5, "addBlockedBy": [4]})
输出: {"id": 5, "blockedBy": [4], ...}
  task_6: blockedBy [] → [4]
执行: task_update({"task_id": 6, "addBlockedBy": [4]})
输出: {"id": 6, "blockedBy": [4], ...}
  task_7: blockedBy [] → [5, 6]
执行: task_update({"task_id": 7, "addBlockedBy": [5, 6]})
输出: {"id": 7, "blockedBy": [5, 6], ...}

.tasks/ 目录状态：
  task_1.json: [x] #1 "Setup project"
  task_2.json: [ ] #2 "Write code"
  task_3.json: [ ] #3 "Write tests" blockedBy=[2]
  task_4.json: [ ] #4 "Parse"
  task_5.json: [ ] #5 "Transform" blockedBy=[4]
  task_6.json: [ ] #6 "Emit" blockedBy=[4]
  task_7.json: [ ] #7 "Test" blockedBy=[5, 6]
```

**解读：** 看那一行 `task_7: blockedBy [] → [5, 6]`——这是 `update()` 副作用打印（`s07_task_system.py:245-246`）的"列表 → 列表"形态。它对 LLM 说："你成功表达了 multi-dependency"。

**注意 task_4 没有任何 update**——它是菱形的顶点，没有依赖。LLM 没去给它发空 update，节省了一次工具调用。这又是 LLM 在做"图的语义判断"：理解了"菱形顶点 = 无依赖"。

---

## 第 3 轮：LLM 渲染菱形 ASCII 图 + 执行计划

**终端输出（最终回答，最精彩的一段）：**

````
All dependencies are set! Here's the full picture:

### Task Board — Refactoring Pipeline

| ID | Task | Status | Blocked By |
|----|------|--------|------------|
| 4 | Parse | ⬜ Pending | — |
| 5 | Transform | ⬜ Pending | #4 |
| 6 | Emit | ⬜ Pending | #4 |
| 7 | Test | ⬜ Pending | #5, #6 |

### Dependency Graph
```
      #4 Parse
       /     \
      ▼       ▼
#5 Transform  #6 Emit
      \       /
       ▼     ▼
       #7 Test
```

### Execution Plan
- **Stage 1 — Sequential:** `#4 Parse` must go first.
- **Stage 2 — Parallel:** Once Parse is done, `#5 Transform` and `#6 Emit` can run **at the same time**.
- **Stage 3 — Sequential:** `#7 Test` only starts after **both** Transform and Emit are complete.
````

**解读：这一段是 LLM 把 blockedBy 数组翻译成"人类能执行的工作流"的全过程。**

LLM 做了三层翻译：

1. **markdown 表格** —— 把 task JSON 字段渲染成行
2. **ASCII 菱形图** —— 用 `/`、`\`、`▼` 画出"分叉-合并"的结构
3. **Execution Plan** —— **这才是最关键的一层**——LLM 把图分成了 Stage 1/2/3，明确指出 Stage 2 是 "**Parallel**"。

**注意 Execution Plan 里的 "at the same time"——这是 LLM 自己得出的结论，TaskManager 没有任何"并行"的概念。** TaskManager 只存了 blockedBy=[4]，从没说过"task_5 和 task_6 可以并行"。**LLM 做的是图的拓扑分层**：

```
拓扑层 0: {task_4}            (没有依赖)
拓扑层 1: {task_5, task_6}   (依赖只在 layer 0 里)
拓扑层 2: {task_7}            (依赖在 layer 1)
```

同一层的任务**没有彼此依赖**，所以可以并行。**这是图论里的标准操作（Kahn 算法），LLM 不需要被教就会做**。

**但这里的"可以并行"是逻辑上的——s07 不会真的并行执行**。这正是 [s07 讲义](../../docs/zh/s07-lecture-notes.md) "概念 2" 末尾那句话："s07 是地图，s08 和 s12 是车队。s07 的 DAG 告诉你哪几条路可以同时走，但车还是只有一辆。" 等到 s08 + s12 才会真的让 task_5 和 task_6 在两个后台线程或两个 worktree 里同时跑起来。

**另一个细节：** LLM 的 ASCII 图只画了 task_4..7，**没画 task_1..3**。但 .tasks/ 里其实还有 task_1..3——LLM 知道这次 prompt 是 "refactoring pipeline"，所以只渲染了相关的任务子图。**这是 LLM 的"语义过滤"**：blockedBy 没有把 task_1..3 和 task_4..7 连起来，LLM 就知道它们是两个独立的工作单元，分开渲染。

---

## 这个例子的关键收获

1. **task ID 的连续性是持久化最直接的证据。** task_4..7 这次新建——**不是因为 LLM 要求 ID 从 4 开始**，而是因为 TaskManager 看到 `.tasks/` 里已有的最大 ID 是 3。这个机制让 example1-3 留下的"考古层"和这一次的"新建层"在同一个 ID 命名空间里和平共存。

2. **`.tasks/` 不强制"工作单元"边界，多组任务图可以共存。** 现在 .tasks/ 里同时有"链 task_1→2→3"和"菱形 task_4→{5,6}→7"两个独立的任务图。TaskManager 不知道、也不在乎它们是不是相关——它只看 ID 和 blockedBy。**这是 s09+ 多 Agent 协作的隐含基础**：多个 Agent 共享 .tasks/，每人维护自己的 task 子图，靠 owner 字段隔离。

3. **`addBlockedBy` 用 list 是为了支持 multi-dependency（AND）。** task_7 的 `[5, 6]` 表达了"等 5 和 6 都完成"，这是菱形 DAG 必须的能力。s07 只有 AND 依赖，没有 OR——OR 通常用"哑节点"实现，s07 没做这个简化层。

4. **LLM 自动做拓扑分层得出"哪些可以并行"。** task_5 和 task_6 都依赖 task_4，没有彼此依赖 → LLM 推理出"它们在同一拓扑层 → 可以并行"。**TaskManager 本身没有"层"或"并行"的概念**——这全是 LLM 在最终回复里现场分析的。这是把"图论查询外包给 LLM"的另一个例子（example2 已经看过一次：list_all 不告诉你 ready/blocked，是 LLM 自己推的）。

5. **s07 的"并行"是逻辑上的，不是执行上的。** Execution Plan 写的 "Parallel" 是一个 hint——告诉将来的 s08（背景线程）或 s12（worktree）"这两个任务安全地放在一起跑"。但在 s07 里，task_5 和 task_6 还是会顺序执行——LLM 只能一次发一个工具调用执行任务。**s07 是 s08/s12 的协调语言，不是并行执行引擎。** 这一点必须区分清楚，否则会高估 s07 的能力。

6. **LLM 的"语义过滤"——只画相关的子图。** task_1..3 还在 .tasks/ 里，但 LLM 的 ASCII 图只画了 task_4..7，因为它们之间没有依赖边。这个判断不是基于"哪个 ID 大"或"哪个新建"——是基于**"blockedBy 没把它们连起来"**。LLM 把不连通的子图视为独立的工作单元。这暗示了一种 future-feature：如果未来你想给 TaskManager 加 `task_subgraph(root_id)` 工具，可以用 BFS/DFS 实现"返回 root_id 所在的连通子图"。但 s07 没做——LLM 自己会判断。

---

> **回到讲义：** 这 4 个例子覆盖了 s07 的全部核心概念——创建/更新/查询/完成（example1-3）和复杂依赖图（example4）。回 [s07 lecture notes](../../docs/zh/s07-lecture-notes.md) 看完整的理论总结。

> **下一节：** s08 background tasks —— 把"逻辑并行"变成"真的并行"，让 task_5 和 task_6 同时在后台线程里跑起来。
