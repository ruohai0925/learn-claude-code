# s07 实际运行追踪：完成任务并亲眼看到自动解锁

> prompt: `Complete task 1 and then list tasks to see task 2 unblocked`
>
> 结果：3 轮。第 1 轮 LLM 调 `task_update(task_id=1, status="completed")`——这一次调用触发了 `_clear_dependency` 的自动传播；第 2 轮 LLM 调 `task_list` 验证；第 3 轮总结输出 `end_turn`。
>
> **重点观察：** 这是 **s07 最核心的一个例子**——你会同时看到三件事：① verbose 输出里的黄色 `→ task_1 完成，解锁了: [2]`；② LLM 收到的 tool_result 里**没有**这一行；③ 第 2 轮 task_list 显示 task_2 的 `(blocked by: ...)` 后缀已经消失。这三件事共同证明 `_clear_dependency` 是 TaskManager **替 LLM 干掉的活儿**——LLM 只说了一句"complete"，剩下的图传播全部由 TaskManager 自动完成。

---

## 第 1 轮：标记 task_1 为完成（关键轮）

**终端输出：**

```
s07 >> Complete task 1 and then list tasks to see task 2 unblocked

────────────────── 用户输入 ──────────────────
query = "Complete task 1 and then list tasks to see task 2 unblocked"

────────────────── 轮次 1: 回复 ──────────────────
response.stop_reason = "tool_use"
response.content = [
  TextBlock: "Completing task 1 first!"
  ToolUseBlock: name="task_update", id="toolu_01SV..."
    input={"task_id": 1, "status": "completed"}
]
```

**解读：** LLM 用一次 `task_update` 调用就把 task_1 标完成。注意它**没有同时**做 task_list——它把 prompt 拆成了两步："complete first, then list"。这是 LLM 在尊重 prompt 的"and then"语义。

**先停一下——这个"完成"不是真的完成。**

你注意看 prompt：`Complete task 1 and then list tasks to see task 2 unblocked`。我们**没有**告诉 LLM "去把项目搭起来"或者"运行 setup 脚本然后把任务标记完成"。我们直接说的是 "**Complete task 1**"——本质上是命令 LLM 把磁盘上 `task_1.json` 的 `status` 字段从 `pending` 改成 `completed`，**仅此而已**。task_1 的 subject 是 "Setup project"，但**没有**任何"项目"被搭建——`.tasks/` 目录之外什么都没发生，`bash` 工具一次都没被调。

**所以这里的 task_1 其实是一个"人造的占位任务"——它的存在只是为了演示状态机的迁移**：pending → completed 这个动作触发 `_clear_dependency`，后者去清掉 task_2 的 blockedBy。我们关心的是这条**机制链**，不是 task_1 真的代表了什么工作。

**这是一个故意为之的教学简化。** 在真实使用中，"完成 task_1" 应该是这样的流程：

```
LLM: 我先来 Setup project。
LLM: bash({"command": "mkdir -p src && touch src/main.py && git init"})
工具: (no output)
LLM: 项目脚手架建好了，现在标记任务完成。
LLM: task_update({"task_id": 1, "status": "completed"})
工具: {"id": 1, ..., "status": "completed", ...}
```

有**真实工作**（bash 命令）发生，然后才有 "标记完成" 的动作。task_update 是工作的**收尾**，不是工作本身。

但在 example3 里，我们**跳过了真实工作**——直接命令 LLM 标记完成。为什么？因为我们要演示的是 `_clear_dependency` 的传播机制，**不是** LLM 怎么搭一个项目。如果让它真去 `mkdir + git init + touch`，verbose 输出里会塞满和"依赖图传播"无关的 bash 噪声，反而看不清重点。教学例子的常见取舍：**舍掉真实性，换取信号清晰度**。

记住这一点：**s07 的 task 系统不会"自己执行"任何任务——它只是一块状态板**。任务的实际执行始终是 LLM 调其他工具（bash/read/write/edit）的结果，task_update 只是"在状态板上挪一下棋子"。example3 把"挪棋子"和"真实工作"硬生生切开来单独演示——这能让你看清状态板本身的行为，但也让 task_1 看上去像一个"空心任务"。**真实场景里，每次状态变化背后都该有真实的工具调用做铺垫**——只是在教学例子里我们把它省了。

**工具执行（最关键的一段）：**

```
────────────────── 轮次 1: 执行工具 ──────────────────
  → task_1 完成，解锁了: [2]                ← 黄色，TaskManager 副作用打印
  task_1: pending → completed                ← 绿色，update 副作用打印
执行: task_update({"task_id": 1, "status": "completed"})
输出 (123 字符): {
  "id": 1,
  "subject": "Setup project",
  "description": "",
  "status": "completed",
  "blockedBy": [],
  "owner": ""
}

.tasks/ 目录状态：
  task_1.json: [x] #1 "Setup project"
  task_2.json: [ ] #2 "Write code"           ← blockedBy 不见了！原本是 [1]
  task_3.json: [ ] #3 "Write tests" blockedBy=[2]
```

**这里有四件事同时发生，每一件都值得单独讲：**

### 1. 黄色 `→ task_1 完成，解锁了: [2]` —— `_clear_dependency` 在工作

这一行是 `TaskManager._clear_dependency()` 内部的副作用打印（`agents/s07_task_system.py:274-275`）。它的含义是："**因为 task_1 完成了，task_2 的 blockedBy 现在彻底变空，可以开始干了**。"

回顾 [s07 讲义](../../docs/zh/s07-lecture-notes.md) "概念 4：自动依赖解除" 里讲过的关键设计点：`unblocked` 列表**不是**记录"被影响的任务"，而是记录"blockedBy 现在彻底变空的任务"。在这个例子里：

- task_2 原本 `blockedBy=[1]` → 抹掉 1 后变成 `[]` → **算 unblocked**（出现在 `[2]` 列表里）
- task_3 原本 `blockedBy=[2]` → task_1 跟它无关，blockedBy 没变 → **不算 unblocked**

所以输出的 `解锁了: [2]` 只有 task_2 一个——精确到位。

### 2. 绿色 `task_1: pending → completed` —— update 的状态变更打印

这是 `TaskManager.update()` 自己的副作用打印（`s07_task_system.py:243-244`），用 `→` 形象地展示状态机的迁移。注意打印顺序：黄色的 `_clear_dependency` 打印在前、绿色的 status 打印在后——这是因为 `update()` 里的代码顺序是：

```python
if status == "completed":
    self._clear_dependency(task_id)   # ← 先调，黄色打印先出
...
if status and status != old_status:
    print(f"  task_{task_id}: {old_status} → {status}")  # ← 后调，绿色打印后出
```

实际上 status 字段在 `_clear_dependency` 之前就赋值了（`task["status"] = status`），所以 `_clear_dependency` 看到的 task_1 已经是 completed 状态——但这不影响别的任务文件，因为 `_clear_dependency` 只读其他 task 文件的 blockedBy。

### 3. 工具的 tool_result 输出**只包含 task_1 自己**

仔细看那个 123 字符的 JSON 输出——它**只**有 task_1 的字段：id=1, status="completed", blockedBy=[]。**没有** "task_2 unblocked" 这种通知。

**这是 s07 一个非常重要的设计选择**：`_clear_dependency` 的副作用（修改了别的任务文件）**不进入 tool_result，不返回给 LLM**。LLM 只知道"我要求 task_1 完成、它确实完成了"。它**完全不知道** task_2 的 blockedBy 已经被清空了。

**那 LLM 怎么知道 task_2 现在解锁了？** —— 它**必须**调一次 `task_list`。这就是为什么 prompt 是 "complete task 1 **and then list**"，也是为什么 LLM 在第 2 轮真的去调了 task_list。

**这个设计的好处：**
- TaskManager 只有"事实通告"，没有"建议下一步"——LLM 自己判断什么时候 query
- 简单：tool_result 永远只反映"你刚刚做的那个 task 现在的样子"，不需要包含一堆相关任务
- 解耦：未来如果要把 task 系统改成事件流（s08+），通知机制可以独立做

**坏处也很明显：** LLM 必须主动 list 才能发现解锁了什么。如果它忘了 list，它就以为 task_2 还在等。但这一点可以靠 prompt（"and then list"）或 system prompt 引导。

### 4. 磁盘上的 task_2.json 已经被改了

verbose 末尾的 `.tasks/ 目录状态` 显示：

```
  task_2.json: [ ] #2 "Write code"           ← blockedBy 不见了！
```

注意 `blockedBy=` 那一截后缀**消失了**。这是 `print_tasks_dir()` 的逻辑（`s07_task_system.py:107`）：

```python
blocked = f" blockedBy={task['blockedBy']}" if task.get("blockedBy") else ""
```

`task["blockedBy"] = []`（空列表）→ falsy → 不打印后缀。所以 task_2 现在是"无依赖"的状态——可以开始干了。

**你可以在另一个终端验证：** `cat .tasks/task_2.json` 会显示 `"blockedBy": []`——文件真的被改写了。`_clear_dependency` 的写盘动作（`s07_task_system.py:269` 的 `self._save(task)`）已经发生。

---

## 第 2 轮：LLM 调 task_list 验证

**终端输出：**

```
────────────────── 轮次 2: 回复 ──────────────────
response.stop_reason = "tool_use"
response.content = [
  TextBlock: "Task 1 is done! Now let's list all tasks to see the updated state."
  ToolUseBlock: name="task_list", id="toolu_018C..."
    input={}
]

────────────────── 轮次 2: 执行工具 ──────────────────
执行: task_list({})
输出 (78 字符): [x] #1: Setup project
[ ] #2: Write code
[ ] #3: Write tests (blocked by: [2])

.tasks/ 目录状态：
  task_1.json: [x] #1 "Setup project"
  task_2.json: [ ] #2 "Write code"
  task_3.json: [ ] #3 "Write tests" blockedBy=[2]
```

**解读：** task_list 的输出验证了第 1 轮的所有结论：

```
[x] #1: Setup project                       ← marker 是 [x]，不是 [ ]
[ ] #2: Write code                          ← 没有 (blocked by: ...) 后缀！
[ ] #3: Write tests (blocked by: [2])       ← 还是有 [2]，因为 task_2 没完成
```

**对比 example2 的 task_list 输出：**

```
example2:                              example3 (现在):
[ ] #1: Setup project                  [x] #1: Setup project           ← 状态变了
[ ] #2: Write code (blocked by: [1])   [ ] #2: Write code              ← blockedBy 没了
[ ] #3: Write tests (blocked by: [2])  [ ] #3: Write tests (blocked by: [2])  ← 没变
```

**两处变化** —— 两处都是 `task_update(1, "completed")` 这**一个**调用引起的：

- task_1 的 status 变了 —— 这是 `update()` 直接干的
- task_2 的 blockedBy 变了 —— 这是 `_clear_dependency` 在 `update()` 内部**自动连锁**触发的

**LLM 只发了一个工具调用，但 .tasks/ 目录里有两个文件被改写。** 这就是 [s07 讲义](../../docs/zh/s07-lecture-notes.md) "概念 4" 里说的"LLM 只表达完成的意图，依赖图的传播由 TaskManager 处理"。

注意 task_list 的字符数从 96（example2）降到 78：因为 task_2 的 `(blocked by: [1])` 后缀消失了，少了 16 字符。**输出长度本身就是依赖关系的副信号**——长度变短意味着至少有一个任务被解锁了。

---

## 第 3 轮：LLM 输出最终状态表

**终端输出（最终回答）：**

```
Here's the updated state:

| ID | Task | Status | Blocked By |
|----|------|--------|------------|
| 1 | Setup project | ✅ Completed | — |
| 2 | Write code | ⬜ Pending | ~~#1~~ *(unblocked!)* |
| 3 | Write tests | ⬜ Pending | #2 |

**#2 Write code** is now unblocked and ready to start! Task 3 is still waiting on Task 2 to be completed.
```

**解读：** LLM 用 `~~#1~~` 删除线 + `*(unblocked!)*` 双重视觉强调"task_2 原本依赖 task_1，现在不依赖了"。这是 LLM **主动**做的渲染选择——TaskManager 没记录"曾经依赖谁"这种历史，LLM 是从前一轮的 messages 里推理出来的：

- 第 6 条 messages 里有 `task_2: blockedBy=[1]`
- 第 14 条 messages 里有 `task_2: blockedBy=[]`
- LLM 把这两者对比 → 推理出 "task_2 was unblocked by task_1's completion" → 用删除线表达

**这是历史信息的优势：当 LLM 看到完整的对话历史，它能做出"差异感知"的渲染**。如果 messages 被压缩了（s06 风格），LLM 可能只能看到当前状态，做不到这种"曾经依赖谁"的对比。

---

## 这个例子的关键收获

1. **`_clear_dependency` 是 TaskManager 替 LLM 干掉的活。** LLM 只说了一句 "complete task_1"，TaskManager 自动扫描所有任务文件、自动从 blockedBy 里清理掉 1、自动判断哪些任务彻底解锁。LLM **完全不需要**遍历 task_list 找"哪些任务依赖我"。这就是讲义里说的"把复杂逻辑藏在工具里、让 LLM 接口保持简单"。

2. **三种打印源 + 三个观察角度。** 同一时刻你能看到：
   - **黄色 `→ task_1 完成，解锁了: [2]`** —— TaskManager 内部自我汇报（屏幕前的人看的）
   - **绿色 `task_1: pending → completed`** —— update 状态机迁移日志（屏幕前的人看的）
   - **123 字符的 JSON 输出** —— LLM 真正看到的 tool_result（只有 task_1 自己）
   - **`.tasks/ 目录状态`** —— `print_tasks_dir()` 扫描磁盘的快照（屏幕前的人看的）
   
   **LLM 看到的信息量远小于屏幕前的人。** verbose 是给人调试用的，不是 LLM 看的。

3. **"完成"不会被自动通知给 LLM——LLM 必须主动 list。** TaskManager 改写了别的任务文件，但不把这个改动塞进 tool_result。LLM 想知道"task_2 现在解锁了吗"，必须显式调 task_list 或 task_get。这是一种**克制的解耦**：tool_result 只反映"你做的那一件事的结果"，不混入"其他被影响的任务"。代价是 LLM 可能会忘了去 list——但这能用 prompt 或 system prompt 引导。

4. **task_list 的输出长度本身是个副信号。** 从 96 字符（example2）→ 78 字符（example3）—— 一行 `(blocked by: [1])` 后缀消失就少了 16 字符。如果未来你想做 "task 系统状态追踪"，可以监控 task_list 输出的字符数变化，作为依赖图变化的廉价指标。

5. **历史 messages 让 LLM 能做"差异渲染"。** task_2 的 `~~#1~~` 删除线是 LLM 对比"曾经的状态"和"现在的状态"得出的。如果你把 example2 和 example3 在不同进程里跑（history 重置），LLM 就只会看到"task_2: blockedBy=[]"，没办法说"unblocked"——因为它不知道"曾经被 blocked"。**所以 history 的累积不仅是"省 token"，也是"语义对比能力"的来源**。

---

> **下一例：** [example4.md](example4.md) —— 让 LLM 创建一个**菱形** DAG（parse → transform/emit → test），看它如何表达"并行"。
