# s07 实际运行追踪：创建 3 个任务并串成依赖链

> prompt: `Create 3 tasks: "Setup project", "Write code", "Write tests". Make them depend on each other in order.`
>
> 结果：3 轮。第 1 轮 LLM **并行** 调用 3 次 `task_create` 把任务全建出来；第 2 轮再 **并行** 调用 2 次 `task_update` 用 `addBlockedBy` 把它们串成 `1 → 2 → 3` 的依赖链；第 3 轮 LLM 输出总结表格 `end_turn`。
>
> **重点观察：** ① `task_create` 不接受 `blockedBy` 参数，所以 LLM 必须用"先 create、后 update"的两阶段写法。② 每一轮 verbose 都打印 `.tasks/` 目录状态，让你**亲眼看到**磁盘上的 JSON 文件如何随着工具调用一步步变化——这正是 s07 "状态搬到磁盘" 的可视化证据。

---

## 启动：干净的 .tasks/ 目录

**终端输出：**

```
(learncc) yzeng@USLT751:~/Codes/learn-claude-code$ python agents/s07_task_system.py
=== s07 verbose 模式 ===
MODEL     = claude-sonnet-4-6
TASKS_DIR = /home/yzeng/Codes/learn-claude-code/.tasks
下一个 task ID: 1（启动时扫描了已有文件）

────────────────── TOOLS 列表 ──────────────────
["bash", "read_file", "write_file", "edit_file", "task_create", "task_update", "task_list", "task_get"]
注意: task_* 工具操作磁盘上的 .tasks/ 目录
```

**解读：** 启动横幅里有两个数字值得盯：

- `下一个 task ID: 1` —— 这是 `TaskManager._max_id() + 1` 的结果（`agents/s07_task_system.py:163`）。`.tasks/` 是空的，所以从 1 开始。**对比一下：** 如果你之前跑过别的例子，这里就不是 1 了——它会从上次留下的最大 ID + 1 继续。这就是 [s07 讲义](../../docs/zh/s07-lecture-notes.md) "概念 5：持久化的真正含义" 里的核心机制。
- `TOOLS 列表` 一共 8 个工具：4 个 base（bash/read/write/edit）+ **4 个 task 工具**（task_create/task_update/task_list/task_get）。这 4 个 task 工具就是 `TaskManager` 类那 4 个公开方法的对外名片——参见讲义"概念 3：TaskManager 的接口结构"。

启动时**没有**打印"启动时已有任务"那一段（`s07_task_system.py:482-485`），因为 `.tasks/` 目录里还没东西。这一段会在 example2 启动时出现——届时你会亲眼看到上一次跑的产物没消失。

---

## 第 1 轮：LLM 一口气并行 task_create

**终端输出：**

```
────────────────── 用户输入 ──────────────────
query = "Create 3 tasks: "Setup project", "Write code", "Write tests". Make them depend on each other in order."

────────────────── 轮次 1 ──────────────────
messages = [
  [0] user: "Create 3 tasks: "Setup project", "Write code", "Write tests". Make them depend o..."
]

→ 调用 client.messages.create(...)

────────────────── 轮次 1: 回复 ──────────────────
response.stop_reason = "tool_use"
response.content = [
  TextBlock: "I'll create all 3 tasks simultaneously, then set up the dependencies in order!"
  ToolUseBlock: name="task_create", id="toolu_01CR..."
    input={"subject": "Setup project"}
  ToolUseBlock: name="task_create", id="toolu_01Cg..."
    input={"subject": "Write code"}
  ToolUseBlock: name="task_create", id="toolu_01MX..."
    input={"subject": "Write tests"}
]
```

**解读：** 这一轮的关键观察有四个：

1. **LLM 一次返回了 3 个 ToolUseBlock。** 不是 3 轮、不是 3 次循环——是**单个 response 里的 3 个并行工具调用**。Anthropic API 允许 assistant 在一次响应里返回多个 tool_use；harness 拿到后会**逐个执行**，把所有 tool_result 一起塞回下一轮 messages。
2. **LLM 自己说出了策略：** `"I'll create all 3 tasks simultaneously, then set up the dependencies in order!"` 这是它把"创建"和"加依赖"分成两步的明确意图。为什么要分两步？因为——
3. **`task_create` 的 schema 不接受 `blockedBy`！** 看 `agents/s07_task_system.py:399-400` 的 input_schema，`task_create` 只有 `subject` 和 `description`。LLM 想表达"task_2 依赖 task_1"必须靠 `task_update` 的 `addBlockedBy` 参数（schema 在 `s07_task_system.py:401-402`）。这是一个**故意的简化设计**——讲义里专门提到（"概念 1" 后面的注释）："实际使用中往往需要'创建时直接指定依赖'"，但 s07 没做。**这种简化逼出了"两阶段写法"**，反而让 LLM 的步骤更显式。
4. **Tool ID 是 Anthropic 给每个 tool_use 分配的全局唯一 ID**（`toolu_01CR...`），后面的 tool_result 必须用 `tool_use_id` 引用对应的 ID。这是 API 的约束，让多个并行工具调用的结果能正确配对。

**接下来是工具执行环节：**

```
────────────────── 轮次 1: 执行工具 ──────────────────
  创建 task_1.json: "Setup project"
执行: task_create({"subject": "Setup project"})
输出 (121 字符): {
  "id": 1,
  "subject": "Setup project",
  "description": "",
  "status": "pending",
  "blockedBy": [],
  "owner": ""
}
  创建 task_2.json: "Write code"
执行: task_create({"subject": "Write code"})
输出 (118 字符): {...同上但 id=2...}
  创建 task_3.json: "Write tests"
执行: task_create({"subject": "Write tests"})
输出 (119 字符): {...同上但 id=3...}

.tasks/ 目录状态：
  task_1.json: [ ] #1 "Setup project"
  task_2.json: [ ] #2 "Write code"
  task_3.json: [ ] #3 "Write tests"
```

**解读：**

- **绿色的 "`创建 task_N.json`" 一行是 verbose 专用的副作用打印**（`s07_task_system.py:204`）——LLM 看不到这行，它只看到下面那个 121 字符的 JSON 输出。verbose 是给屏幕前的人看的"显微镜"，让你看到 TaskManager 内部的动作；LLM 看到的只是工具的返回值。
- 三个 task 都被创建，每个的 `status` 都是 `"pending"`、`blockedBy` 都是 `[]`、`owner` 是 `""`。这是 `TaskManager.create()` 的默认值（`agents/s07_task_system.py:196-199`）。owner 字段在 s07 里没用，是为 s09+ 多 Agent 协作铺路。
- **最后一段 `.tasks/ 目录状态`** —— 这是 `print_tasks_dir()` 在每轮 task 工具调用后的"显微镜快照"（`s07_task_system.py:462-464`）。它扫描 `.tasks/` 目录，按数字 ID 排序，把每个文件画成 `marker #id "subject" blockedBy=...` 的一行。

**关键价值：这一段把"任务真的写到磁盘上了"变成了肉眼可验证的事实**——你可以在另一个终端里 `ls .tasks/` 看到 `task_1.json` `task_2.json` `task_3.json` 三个文件，内容跟上面绿色 JSON 一模一样。这是"状态搬到磁盘"最直接的证据。

---

## 第 2 轮：用 task_update 把依赖串起来

**终端输出（messages 数组省略，只看 LLM 的回复）：**

```
────────────────── 轮次 2: 回复 ──────────────────
response.stop_reason = "tool_use"
response.content = [
  TextBlock: "All 3 tasks are created! Now I'll set up the dependencies — "Write code" blocked by "Setup project", and "Write tests" blocked by "Write code"."
  ToolUseBlock: name="task_update", id="toolu_0183..."
    input={"task_id": 2, "addBlockedBy": [1]}
  ToolUseBlock: name="task_update", id="toolu_01Jz..."
    input={"task_id": 3, "addBlockedBy": [2]}
]
```

**解读：** 又是**两个并行 tool_use**——LLM 把两个独立的依赖关系一次提交。注意几个细节：

- **没有 `task_2 依赖 task_1` 这种描述**，LLM 直接传 `{"task_id": 2, "addBlockedBy": [1]}`。这是 schema 的引导：input_schema 写明 `addBlockedBy` 是 `array of integer`，LLM 就知道用整数列表表达"被这些 ID 阻塞"。
- **依赖的方向很重要：** `task_update(task_id=2, addBlockedBy=[1])` 表示"**task_2 被 task_1 阻塞**"——也就是 task_1 是前置，task_2 在后。改的是被阻塞者的 blockedBy，**不是**前置任务。这个方向和 Jira 的 "is blocked by" 链接是一致的（参见讲义"核心类比"那节的 Jira 走读）。
- **LLM 没碰 task_1。** task_1 没有任何依赖（它是链条的起点），所以 LLM 不需要给它发 update。**这是 LLM 在做"图的语义判断"**——它理解了"按顺序串起来"意味着"中间的两个各自有一个前置"，而不是给所有 3 个都加依赖。

**工具执行：**

```
────────────────── 轮次 2: 执行工具 ──────────────────
  task_2: blockedBy [] → [1]
执行: task_update({"task_id": 2, "addBlockedBy": [1]})
输出 (127 字符): {
  "id": 2,
  "subject": "Write code",
  ...
  "blockedBy": [1],
  ...
}
  task_3: blockedBy [] → [2]
执行: task_update({"task_id": 3, "addBlockedBy": [2]})
输出: {...task_3 with blockedBy: [2]...}

.tasks/ 目录状态：
  task_1.json: [ ] #1 "Setup project"
  task_2.json: [ ] #2 "Write code" blockedBy=[1]
  task_3.json: [ ] #3 "Write tests" blockedBy=[2]
```

**解读：** verbose 输出的 `task_2: blockedBy [] → [1]` 是 `TaskManager.update()` 里的副作用打印（`s07_task_system.py:245-246`），把"改变"用 `→` 形象地表达出来。

注意 `addBlockedBy` 的实现细节（`s07_task_system.py:236-237`）：

```python
if add_blocked_by:
    task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
```

它用 `set(...)` 去重——如果 LLM 不小心传了 `addBlockedBy=[1, 1]`，最后存进去的也是 `[1]`。这是一个"防 LLM 抖手"的小防御。

最后的 `.tasks/ 目录状态` 显示了 DAG 已经建好：链 `1 → 2 → 3`。在磁盘上验证一下，`cat .tasks/task_2.json` 你会看到 `"blockedBy": [1]`——和 verbose 输出一致。

---

## 第 3 轮：LLM 总结，end_turn

**终端输出：**

```
────────────────── 轮次 3: 回复 ──────────────────
response.stop_reason = "end_turn"
response.content = [
  TextBlock: "All done! Here's a summary of the 3 tasks and their dependencies:

| ID | Task | Blocked By |
|----|------|------------|..."
]

────────────────── 轮次 3: 循环结束 ──────────────────
stop_reason = "end_turn" → return!
```

**解读：** `stop_reason` 从 `tool_use` 变成 `end_turn`——LLM 觉得任务完成了，不再调用工具，开始输出最终回复。这是 agent loop 退出的信号（`s07_task_system.py:434-437`）。

### 一个值得停下来想一想的现象：example1 全程没用 `task_list`、也没用 `task_get`

整个 example1 共调用了 **5 次工具** —— 3 次 `task_create` + 2 次 `task_update`，**0 次 `task_list`**，**0 次 `task_get`**。注册给 LLM 的 4 个 task 工具里只用了一半。这不是 LLM 偷懒，而是因为它**根本不需要**那两个查询工具——它已经有了它需要的所有信息。

#### 第 3 轮开始时，LLM 的 messages 里到底有什么？

让我们逐条数一下 LLM 在写最终回复时手里握着的"事实"：

| messages 索引 | 类型 | 内容（精简） |
|---|---|---|
| `[0]` | user | "Create 3 tasks..." 原始 prompt |
| `[1]` | assistant | TextBlock + 3 个 `task_create` ToolUseBlock |
| `[2]` | user | **3 个 tool_result，每个是一份完整的 task JSON：**<br>① `{id:1, subject:"Setup project", status:"pending", blockedBy:[], owner:""}`<br>② `{id:2, subject:"Write code", status:"pending", blockedBy:[], owner:""}`<br>③ `{id:3, subject:"Write tests", status:"pending", blockedBy:[], owner:""}` |
| `[3]` | assistant | TextBlock + 2 个 `task_update` ToolUseBlock |
| `[4]` | user | **2 个 tool_result，每个是更新后的完整 task JSON：**<br>④ `{id:2, subject:"Write code", status:"pending", blockedBy:[1], owner:""}`<br>⑤ `{id:3, subject:"Write tests", status:"pending", blockedBy:[2], owner:""}` |

**LLM 手里有 5 个完整的 task JSON 快照。** 用 ID 去重、保留最新的：

- task_1 → 只有 ① 一份（从未被 update 过，所以创建时的快照就是当前状态）
- task_2 → ② 是旧的，④ 是新的 → **取 ④**
- task_3 → ③ 是旧的，⑤ 是新的 → **取 ⑤**

把最新的三份合在一起，LLM 已经知道：

```
task_1: pending, blockedBy=[]
task_2: pending, blockedBy=[1]
task_3: pending, blockedBy=[2]
```

**这就是 task_list 会返回的全部信息**——LLM 已经在内存里了，再调一次 task_list 就是浪费 1 次 LLM round-trip + 1 次工具调用。

#### 为什么会这样？关键在于"每个写操作都返回完整的写后状态"

回头看 `TaskManager.create` 和 `update` 的最后一行（`agents/s07_task_system.py:206` 和 `s07_task_system.py:248`）：

```python
def create(self, subject, description=""):
    task = {...}
    self._save(task)
    ...
    return json.dumps(task, indent=2, ensure_ascii=False)   # ← 返回完整 task

def update(self, task_id, status=None, ...):
    task = self._load(task_id)
    ...修改 task...
    self._save(task)
    ...
    return json.dumps(task, indent=2, ensure_ascii=False)   # ← 返回完整 task
```

**两个写工具都不是"返回 OK 就完事"——它们返回的是写完之后的完整 task JSON。** 这是一个看起来不起眼、但对 LLM agent 极其关键的设计选择。给它起个名字：**"write-through tool"**——每次写入都顺带把当前状态"穿透"回客户端。

#### 对比一个反面例子：如果是"返回 OK"的设计

想象一下，如果 `task_update` 的实现改成这样：

```python
def update(self, task_id, ...):
    task = self._load(task_id)
    ...修改...
    self._save(task)
    return "OK"   # ← 只说成功了
```

LLM 调 `task_update(2, addBlockedBy=[1])` 拿到 `"OK"`。它知道写成功了，但**不知道写后的样子**。它现在 task_2 的最新印象停留在 `[2]` 那条 create 的输出（`blockedBy=[]`）。如果它要在第 3 轮总结依赖关系，它必须再调一次 `task_get(2)` 才能拿到 `blockedBy=[1]`——**这一次额外的 get 就是一次完整的 LLM round-trip**（response → tool_use → tool_result → 下一轮 response），白白多花一次模型调用。

如果有 5 个写操作、每个都要 follow-up 一个 get，就是 5 次额外的 round-trip，对 latency 和 token 成本都是直接翻倍。

**所以 "write-through" 设计的真正价值是：把 N 次"写 + 读"合并成 N 次"写"，省掉一半的工具调用次数。** 在 LLM agent 里，工具调用次数 = 模型调用次数 = latency × cost。这一招省的不是字节，是**轮次**。

#### 这是 RESTful 设计里的一个老问题

熟悉 REST API 设计的人应该见过这个争论：

- **PUT /tasks/2 → 204 No Content**（"写成功了，自己 GET 去看"）—— 严格 RESTful，HTTP/1.1 推荐
- **PUT /tasks/2 → 200 OK + updated resource body**（"写成功了，顺便给你看新样子"）—— 务实派，节省 round-trip

对人类客户端来说，这两种风格差别不大——浏览器可以异步发 GET，用户感知不到延迟。**但对 LLM 客户端来说，差别巨大**：每一次"额外的 GET"都意味着模型要再被叫醒一次、再过一次注意力机制、再吐一次 token。**LLM 的每一次推理都是几百毫秒到几秒的延迟、几十到几百个 token 的成本**。

`TaskManager.create` 和 `update` 选了第二种——返回完整资源——**这是为 LLM 客户端做的明显优化，不是巧合**。

#### 那 `task_list` 和 `task_get` 是用来干什么的？

既然 write-through 让 LLM 总是知道自己写过的任务的最新状态，那为什么还要 list 和 get 这两个查询工具？因为有**三种情况** LLM 会"失忆"，必须主动 query：

1. **LLM 没碰过的任务。** 假设 example2 / example3 / example4 一连串 prompt 跑下来，磁盘上有 7 个任务，但当前 prompt 只让 LLM 改了 task_4 一个。它需要看 task_1..3、task_5..7 的当前状态时，没办法从 messages 里凑出来——**必须 task_list 或 task_get**。example2 就是这种情况：用户开口就要 "list all tasks"，LLM 没改过任何任务，只能 list。
2. **状态被 LLM 自己看不见的副作用改了。** 这是 example3 里 `_clear_dependency` 的精确情况——LLM 调 `task_update(1, completed)`，`TaskManager._clear_dependency` 在背后**默默改了 task_2 的 blockedBy**，但这个改动**不进入** task_update 的返回值。LLM 拿到的 tool_result 只有 task_1 的 JSON，对 task_2 的认知还停留在 `blockedBy=[1]`。要发现 task_2 现在解锁了，**只能 task_list**。这就是 example3 的 prompt 必须显式说 "and then list" 的根本原因。
3. **历史被压缩或者跨进程丢失了。** 如果 [s06](../../docs/zh/s06-lecture-notes.md) 的 auto_compact 在中途触发、把前几轮的 messages 替换成 summary，那些 task JSON 就消失了——LLM 只剩"我之前做过 task 操作"的模糊印象，没有具体字段。这时候**必须重新 task_list 重建认知**。或者跨进程：你今天创建了任务、明天重启 Agent，新进程的 messages 是空的，要找回"目前有什么任务"也只能 task_list。

**所以 list 和 get 不是冗余——它们是为"LLM 失忆的三种情况"准备的兜底**。example1 因为是从空目录开始、单进程内、没有 _clear_dependency 触发、又恰好 LLM 自己改了它需要追踪的所有任务，所以四种条件都没踩到，就用 0 次查询工具完成了任务。

**下一例 example2 就会用到 task_list（LLM 没碰过任务，必须 query），example3 也会用到 task_list（_clear_dependency 的隐藏副作用，必须 query）**。把这三个例子合在一起看，list/get 出现的位置就成了一个"LLM 失忆雷达"——它在哪里出现，就标记着在哪里 LLM 单靠 messages 不足以重建当前状态。

#### 一个隐藏假设：单进程下"我没碰过 = 它没变"

example1 的零查询能行得通，还有一个**隐藏前提**：task_1 从创建后就没被 update 过——LLM 假设"我没碰过 task_1，那它的 blockedBy 现在还是 `[]`"。在单进程的 s07 里这个假设是安全的，因为**只有 LLM 通过工具改 .tasks/，没有别的写入者**。

但这个假设到了 [s09 多 Agent 协作](../../docs/zh/s09-agent-teams.md) 就**直接破产**——多个 Agent 共享 `.tasks/` 目录，Agent A 没碰过的 task 完全可能被 Agent B 改掉。那时候即使是 write-through 也不够了，LLM 必须**重新 list 才能信任自己的状态**——因为"我没碰过"不再蕴含"它没变"。

s07 的 example1 之所以这么简洁优雅，本质上是因为 s07 是"单写者世界"。这种简洁性在 s09 之后会被打破——不是 s07 设计不好，是分布式系统天然不能像单机系统那样"信任本地状态"。**这也是为什么 list/get 工具一开始就要存在：它们不是为 example1 准备的，是为 example1 之外的世界准备的**。

**最终回答（LLM 自己渲染的 markdown 表格）：**

```
All done! Here's a summary of the 3 tasks and their dependencies:

| ID | Task | Blocked By |
|----|------|------------|
| 1 | Setup project | *(none — start here)* |
| 2 | Write code | Task 1 (Setup project) |
| 3 | Write tests | Task 2 (Write code) |

The order is enforced as a chain: **Setup project → Write code → Write tests**.
Each task must be completed before the next one can begin.
```

**解读：** LLM 用自然语言把 DAG 翻译给人看——"start here"、"chain"、"must be completed before"。注意它**没有**把磁盘上的 JSON 原样贴出来——它做了一层语义渲染。这个能力在 example2 里会进一步看到。

---

## 这个例子的关键收获

1. **task_create 的简化设计逼出了"两阶段写法"。** create 不接受 blockedBy → LLM 必须先创建再用 task_update 加依赖。这看起来是一个"缺陷"，但它把"任务存在"和"任务关系"显式分开，反而让步骤更清晰、更容易调试。这是一种**有意的接口贫瘠**——强迫客户端走两遍，避免一次写入太多隐式假设。

2. **并行 tool_use 是 LLM 的"批处理本能"。** 第 1 轮一次发 3 个 task_create、第 2 轮一次发 2 个 task_update——LLM 不傻，它知道独立的操作应该一起发。harness 的 agent loop 一次接收所有 tool_use、逐个执行、一起塞回结果，这是 [s01](../../docs/zh/s01-lecture-notes.md) 那个"循环结构"的基础能力，到 s07 才被 task 工具用满。

3. **verbose 输出区分了三种打印源。** 每一轮你会看到三类信息：
   - **黄色 `执行: task_create(...)`** —— harness 在工具调度处的打印（`s07_task_system.py:451`）
   - **绿色 `创建 task_1.json: "..."`** —— TaskManager 类内部副作用打印（`s07_task_system.py:204`）
   - **暗灰 `.tasks/ 目录状态`** —— `print_tasks_dir()` 在每轮末尾扫描磁盘（`s07_task_system.py:462-464`）
   
   **三类打印对应三个抽象层：harness（调度）→ TaskManager（业务）→ 文件系统（存储）。** LLM 只看到工具返回的 JSON，看不到任何这些 verbose 输出。

4. **磁盘上的 JSON 是"事实"，LLM 看到的是"快照"。** LLM 通过 tool_result 看到的每个 task 是创建/更新那一刻的 snapshot，但磁盘上的 JSON 是当前状态。如果另一个进程在 LLM 操作期间改了文件，LLM 是看不到的——s07 是单进程的，所以这不是问题；但 s09 多 Agent 共享 `.tasks/` 时这就是必须直面的问题。

5. **LLM 主动总结输出，而不是吐出原始数据。** 第 3 轮没有 task_list 调用——LLM 从历史 tool_result 里"内存里"知道状态，渲染成 markdown 表格。这表明 task_list 不是"强制每次都看一眼"的工具，LLM 会按需调用。和 s03 的 todo 强提醒（nag 机制）形成对比：s07 完全靠 LLM 自己判断什么时候该看磁盘。

---

> **下一例：** [example2.md](example2.md) —— 让 LLM 显式调 `task_list`，看它如何把扁平输出渲染成依赖图。
