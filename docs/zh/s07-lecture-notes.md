# s07: Task System —— 持久化的任务图

> **前置知识：** 请先完成 [s01](s01-lecture-notes.md) - [s06](s06-lecture-notes.md)。本讲义不重复已讲过的概念，只聚焦 s07 的新内容。

---

## 这一课要回答的问题

> [s03](s03-lecture-notes.md) 的 TodoManager 是内存里的扁平 checklist——没有顺序、没有依赖、[s06](s06-lecture-notes.md) 的 context compact 一触发就全没了。如果一个任务依赖另一个任务（B 必须等 A 完成），或者 C 和 D 可以并行，怎么表达？怎么让任务在压缩、重启、甚至跨会话后还能继续？

**答案：把任务从内存搬到磁盘，从扁平列表升级为依赖图。每个任务一个 JSON 文件，blockedBy 字段表达依赖关系。**

---

## 核心类比：项目管理工具

想想 Linear、Jira、Asana 的工作方式。如果你用过 Jira（很多公司都用），那 s07 的设计会让你觉得似曾相识——它本质上就是一个**给 Agent 用的极简 Jira**。下面我用一个典型的 Jira 工作流走一遍，再把它和 s07 一一对照。

### 一个典型的 Jira 工作流是这样的

假设你在一个叫 `PROJ` 的项目里，接到一件事："重构用户认证模块"。流程通常是这样：

**1. 创建 ticket。** 你点 "Create issue"，填写：

- **Summary**: `Refactor auth middleware`
- **Description**: `Replace session token storage to meet new compliance requirements`
- **Issue type**: Task
- **Assignee**: 你自己
- **Status**: `To Do`（默认）

Jira 给它分配一个全局唯一的 key：`PROJ-142`。这个 key 不只是数字——它是这条 ticket 的**身份**，可以贴到 Slack 消息、Git commit message、PR 标题里，任何人看到 `PROJ-142` 都能在 Jira 上找到它。

**2. 拆子任务并标依赖。** 你发现这件事一口气做不完，要拆成几步：

- `PROJ-143`: "Audit current token storage"
- `PROJ-144`: "Design new storage schema"（依赖 143——得先审计才知道要设计什么）
- `PROJ-145`: "Implement new storage"（依赖 144）
- `PROJ-146`: "Migrate existing sessions"（依赖 145）
- `PROJ-147`: "Write integration tests"（也依赖 145，可以和 146 并行）

在 Jira 里怎么标依赖？你打开 `PROJ-144`，点 "Add link" → 选 link 类型 "**is blocked by**" → 输入 `PROJ-143`。Jira 会在两条 ticket 之间建立**双向引用**——`PROJ-144` 上显示 "is blocked by PROJ-143"，`PROJ-143` 上自动显示 "blocks PROJ-144"。这就是 Jira 表达任务依赖的方式：不是层级（parent/child），而是**横向链接**。

**3. 推进状态。** 同事开始干 `PROJ-143`，把它从 `To Do` 拖到 `In Progress`。做完后拖到 `Done`。这时——**关键点来了**——`PROJ-144` 的 "is blocked by" 那一栏**并不会自动消失**。Jira 不会替你解除依赖关系。它只做两件事：

- 给 `PROJ-144` 的 watcher 发邮件提醒"你的依赖完成了"
- 在 sprint board 上把 `PROJ-144` 旁边的小图标变个颜色，暗示它"现在可能可以开始了"

但 "is blocked by PROJ-143" 这条 link 还在——它是一条**历史关系**，不是动态状态。真正"现在可以开干了"的判断，要靠人去看 board、看通知，然后手动把 `PROJ-144` 拖到 `In Progress`。

**4. 看板视图（Sprint board）。** 团队每天站会看 board——左边一列 `To Do`、中间 `In Progress`、右边 `Done`。每个 ticket 是一张卡片，被依赖阻塞的卡片旁边有小图标标记。一眼就能看出"现在哪些卡片是可以领的"——`To Do` 状态 + 没有未完成的 blocker。

**5. 跨会话、跨设备、跨人。** Jira ticket 存在公司的 Jira 服务器上。你今天在公司电脑上创建 `PROJ-143`，明天在家用浏览器打开 Jira，它还在那儿。你休假时同事看到你那条 ticket，可以接手把它推进。**Ticket 的状态独立于任何一个人的工具或会话**——这是项目管理工具最根本的价值。

### 把 Jira 工作流映射到 s07

s07 的 TaskManager 就是把上面这套机制**抽象到只剩最核心的部分**，搬给 LLM 用：

| Jira | s07 |
|---|---|
| Jira 服务器（存所有 ticket 的中心地） | `.tasks/` 目录（存所有 task 的中心地） |
| 一条 ticket（`PROJ-143`） | 一个 `task_N.json` 文件 |
| Ticket 的全局唯一 key（`PROJ-143`） | 自增整数 `id`（`task_3`） |
| Summary 字段 | `subject` 字段 |
| Description 字段 | `description` 字段 |
| Status: `To Do` / `In Progress` / `Done` | `status`: `pending` / `in_progress` / `completed` |
| Issue link "**is blocked by**" | `blockedBy: [id, ...]` |
| Assignee 字段 | `owner` 字段（s07 没用，s09+ 才用） |
| Sprint board "可以领的卡片" 视图 | `task_list` 工具的输出 |
| 服务器存 ticket，浏览器只是临时视图 | 磁盘存 task，messages 只是临时视图 |
| 多人共享同一个 ticket 池 | 多个 Agent 共享同一个 `.tasks/` 目录（s09+） |

### s07 比 Jira 更智能的一点：自动解除依赖

记得上面 Jira 流程里那个细节吗？同事把 `PROJ-143` 标成 `Done`，但 `PROJ-144` 上的 "is blocked by PROJ-143" **不会自动消失**——Jira 只发邮件、变图标颜色，真正的"现在可以开始了"靠人手动判断。

这是因为 Jira 的设计假设是"人会看 board、会看邮件"。但 **LLM 不会自然地'瞄一眼 board'**——它只能在调用工具时看到结果。如果 s07 也照搬 Jira 的做法，LLM 每次完成一个任务后就要：

1. 调 `task_list` 看所有任务
2. 自己遍历，找出哪些任务的 `blockedBy` 包含刚完成的那个 ID
3. 一个个调 `task_update` 把它们的 `blockedBy` 改掉

这是一堆**冗余的工具调用**，而且 LLM 很容易漏。所以 s07 把这一步**做进了 TaskManager 自己**——`_clear_dependency()` 在你调 `task_update(status="completed")` 时**自动**触发，扫描所有任务文件、自动从 `blockedBy` 里移除完成的 ID。

**LLM 只表达"完成"的意图，依赖图的传播由 TaskManager 处理。** 这是把复杂逻辑藏在工具里、让 LLM 的接口保持简单的典型设计。

如果你愿意，可以这么想：**s07 = Jira + 一个"完成时自动 unblock 所有下游 ticket"的机器人。** 在 Jira 里这种机器人叫 **automation rule**（自动化规则），需要管理员单独配置；s07 直接把它焊进了 TaskManager 的核心行为里。

---

## s06 → s07：到底变了什么？

| 组件 | s06 | s07 | 变了吗？ |
|---|---|---|---|
| `while True` 循环结构 | 有 | 一样 | 不变 |
| 工具 | 5 个（base + compact） | 8 个（base + **task_create/update/list/get**） | **变了** |
| TaskManager | 无 | **新增**（持久化任务图） | **新增** |
| 状态存储 | 内存 messages（s06 的压缩可清空） | **磁盘** `.tasks/*.json` | **变了** |
| 任务关系 | 无 | **`blockedBy` 依赖图** | **新增** |
| 三层压缩 | 有 | 去掉了（s07 聚焦于任务，不含压缩） | 去掉 |

**最重要的变化：状态从内存搬到了磁盘。** s06 的 transcript 是事后审计日志，但任务**当前的状态**还在 messages 里，压缩后就丢了。s07 的 `.tasks/` 目录是工作状态本身——压缩、重启、跨会话都不影响。

---

## 概念 1：一个任务一个 JSON 文件

```json
// .tasks/task_2.json
{
  "id": 2,
  "subject": "Write code",
  "description": "",
  "status": "pending",
  "blockedBy": [1],
  "owner": ""
}
```

字段含义：

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | int | 自增整数，文件名也用它（`task_2.json`） |
| `subject` | str | 短标题（"Write code"） |
| `description` | str | 详细描述（可选） |
| `status` | str | `pending` / `in_progress` / `completed` |
| `blockedBy` | list[int] | 被哪些任务阻塞（依赖列表） |
| `owner` | str | 谁负责（s09+ 多 Agent 用） |

**为什么一个文件一个任务，而不是一个大 JSON 装所有任务？**

- **并发友好** — 多个 Agent 同时读写时不会互相覆盖（s09+ 的多 Agent 协作前提）
- **故障恢复** — 一个任务的 JSON 损坏不影响其他任务
- **直观** — `ls .tasks/` 就能看到所有任务

代价是 list_all() 要扫描整个目录（O(N)），但任务数通常不大。

---

## 概念 2：blockedBy —— 依赖图的核心

```
task_1.json: blockedBy=[]      ← 无依赖，可立即开始
task_2.json: blockedBy=[1]     ← 等 task_1 完成
task_3.json: blockedBy=[1]     ← 也等 task_1（和 task_2 并行）
task_4.json: blockedBy=[2,3]   ← 等 task_2 和 task_3 都完成
```

画出来是一个 **DAG**（有向无环图）：

```
                +----------+
           +--> | task_2   | --+
           |    | pending  |   |
+----------+    +----------+   +--> +----------+
| task_1   |                        | task_4   |
| pending  |                        | pending  |
+----------+    +----------+   +--> +----------+
           |    | task_3   | --+
           +--> | pending  |
                +----------+
```

这个图能回答三个关键问题：

1. **What's ready?** — `status=pending` 且 `blockedBy=[]` 的任务（这里是 task_1）
2. **What's blocked?** — `blockedBy` 非空的任务（task_2/3/4）
3. **What can run in parallel?** — 同一层的任务（task_2 和 task_3 可以并行）

**注意：当前 s07 不实现"并行执行"——它只表达依赖关系。** 真正的并行需要 s08（背景线程）或 s12（worktree 隔离）。s07 的并行性是"逻辑上的并行"——LLM 知道哪些任务可以同时进行，但实际执行还是顺序的。

换句话说，**s07 是地图，s08 和 s12 是车队**。s07 的 DAG 告诉你"哪几条路可以同时走"，但车还是只有一辆——LLM 一次只能调一个工具、一个工具地往下做。即使 task_2 和 task_3 在图上是并列的（都没有 blocker），LLM 实际还是先做完 task_2 再做 task_3。后面两课才往这张地图上加"车"：

- **s08（背景线程）** 给单个 Agent 加了"开多个 shell 子进程"的能力——`background_run` 把命令丢进后台线程，立刻返回 task_id，Agent 不用等命令结束就能接着调其他工具，结果通过一个 notification queue 在下一轮 LLM 调用前注入回上下文。这一层解决的是**"长时间命令的并行"**：跑测试、跑构建、拉数据这类**纯命令型**任务可以同时开几个。但它不解决文件冲突——如果两个后台命令都改同一个文件，照样会乱套。
- **s12（worktree 隔离）** 进一步给"会改文件的任务"加并行能力——每个 task 分配一个独立的 git worktree（独立目录 + 独立分支），任务在自己的目录里跑，互不打架。s12 源码注释里有一句话很精辟：**"Tasks are the control plane and worktrees are the execution plane."**（任务是控制面，worktree 是执行面。）这里的控制面就是 s07 这一课建起来的 DAG，执行面是 s12 加上来的目录隔离——两层各管一摊，s07 的 task_id 是把两层粘在一起的钉子（s12 的 worktree 索引里直接存 `task_id`，反向也在 task JSON 里存 `worktree` 字段）。

所以 s07 的 `blockedBy` 不是在这一课就榨干价值的——它是为 s08/s12 **提前铺好的协调语言**。本课你看到的"逻辑上的并行"（图上写着"可以同时做"），到 s12 才会变成"两个目录里真的同时在跑的两个任务"。这也是为什么 s07 必须放在 s08/s12 前面：没有这张图，s08 的后台线程不知道"哪些命令安全地放一起跑"，s12 的 worktree 也不知道"该给哪几条任务各开一个 lane"。

---

## 概念 3：TaskManager 的接口结构 —— 4 个公开方法 + 一堆私有 helpers

退一步看 `TaskManager` 这个类整体的样子（`agents/s07_task_system.py:157-308`）。把所有方法按出现顺序列出来：

```python
class TaskManager:
    def __init__(self, tasks_dir):                # 私有：构造，扫描已有文件
    def _max_id(self):                             # 私有：找最大 ID
    def _load(self, task_id):                      # 私有：从磁盘读 JSON
    def _save(self, task):                         # 私有：把 JSON 写回磁盘
    def create(self, subject, description=""):    # 公开 ★
    def get(self, task_id):                        # 公开 ★
    def update(self, task_id, status, ...):        # 公开 ★
    def _clear_dependency(self, completed_id):    # 私有：依赖图传播
    def list_all(self):                            # 公开 ★
```

**带 ★ 的 4 个公开方法 = 4 个 LLM 工具。** 不多不少，正好对应。验证一下 dispatch table（`agents/s07_task_system.py:370-379`）：

```python
TOOL_HANDLERS = {
    ...
    "task_create": lambda **kw: TASKS.create(kw["subject"], kw.get("description", "")),
    "task_update": lambda **kw: TASKS.update(kw["task_id"], kw.get("status"), kw.get("addBlockedBy"), kw.get("removeBlockedBy")),
    "task_list":   lambda **kw: TASKS.list_all(),
    "task_get":    lambda **kw: TASKS.get(kw["task_id"]),
}
```

每一行就是把 LLM 工具名翻译成 TaskManager 的公开方法调用——**dispatch table 是 LLM 视角和 TaskManager 视角之间的一座小桥**，桥的一头是工具名（`task_create`），另一头是方法名（`TASKS.create`）。

剩下的 5 个方法呢？`__init__` / `_max_id` / `_load` / `_save` / `_clear_dependency`——下划线开头是 Python 的"私有"约定——**全部是为这 4 个公开方法服务的**：

| 私有方法 | 服务于谁 | 干什么 |
|---|---|---|
| `__init__` + `_max_id` | 全部 4 个公开方法 | 启动时扫描磁盘，决定 `_next_id` 从几开始 |
| `_load` | `get`, `update` | 从磁盘把 JSON 反序列化成 dict |
| `_save` | `create`, `update`, `_clear_dependency` | 把 dict 序列化写回磁盘 |
| `_clear_dependency` | `update` | 完成任务时自动传播依赖图（下一节详解） |

换句话说，整个类可以用一个倒过来的金字塔来理解：

```
        LLM 看到的世界（4 个工具）
                  ↓
        ┌───────────────────────┐
        │ task_create  task_get │   ← dispatch table 翻译
        │ task_update task_list │
        └───────┬───────────────┘
                ↓
        ┌───────────────────────┐
        │ create / get          │   ← 4 个公开方法
        │ update / list_all     │     （TaskManager 的对外 API）
        └───────┬───────────────┘
                ↓
        ┌───────────────────────┐
        │ _load / _save         │   ← 私有 helpers
        │ _max_id               │     （磁盘 I/O、ID 生成）
        │ _clear_dependency     │     （依赖图传播）
        └───────────────────────┘
                  ↓
              .tasks/*.json
```

**接口边界 = LLM 能做的事的边界。** 这是一种"能力围栏"：你只把想让 LLM 做的事暴露成公开方法，剩下的全部封在私有方法里。LLM 不能直接调 `_save`、`_load` 或 `_clear_dependency`——它**碰不到**底层的文件操作和图传播逻辑，只能通过 4 个工具的"正门"进来。

这个设计带来三个具体的好处：

1. **私有方法可以自由重构。** 哪天你想把 JSON 换成 SQLite、把 `glob` 换成数据库查询、把 `_clear_dependency` 的 O(N) 扫描改成反向索引——**只要 4 个公开方法的签名不变，LLM 完全感知不到**。LLM 看到的"任务系统的样子"是稳定的，存储层可以随便换。
2. **读代码时知道从哪儿入手。** 想搞懂 TaskManager？盯着 4 个公开方法看就够了，私有方法只是它们的实现细节。如果你只有 5 分钟读这个类，从 `create` / `get` / `update` / `list_all` 入手就能掌握 80% 的设计。
3. **LLM 的工具表是类的 API 的镜像。** 想给 LLM 加新能力？在类里加一个新公开方法，再在 dispatch table 加一行映射，再在 TOOLS 列表加一个 schema——三步。这是非侵入式扩展（参见 [s05](s05-lecture-notes.md)）的一个具体落地：你只在三个地方加东西，没有任何已有逻辑被改动。

**这是一个通用的工具系统设计模式：用 public/private 把"可调用的能力"和"实现细节"切开，然后在 dispatch table 那一层做翻译。** 后续 s08 的 `BackgroundManager`、s12 的 worktree 管理类都会沿用这个模式——你会反复看到一个 Manager 类只暴露 3-5 个公开方法、剩下全是 helpers，再加一张 dispatch table 把它们映射成工具。**记住这个形状，后面的课程里你会一眼认出来。**

---

## 概念 4：自动依赖解除（`_clear_dependency`）

完成一个任务时，**自动**从所有其他任务的 blockedBy 里移除它。先看 `update()` 里的触发点（`agents/s07_task_system.py:223-235`）：

```python
def update(self, task_id: int, status: str = None,
           add_blocked_by: list = None, remove_blocked_by: list = None) -> str:
    task = self._load(task_id)
    ...
    if status:
        if status not in ("pending", "in_progress", "completed"):
            raise ValueError(f"Invalid status: {status}")
        task["status"] = status
        # ── 关键：完成任务时自动解除其他任务对它的依赖 ──
        if status == "completed":
            self._clear_dependency(task_id)
```

整个 update 里关键就是这两行——只要 `status == "completed"`，TaskManager 立刻调 `_clear_dependency`，LLM 完全感知不到这一步发生了。

然后是 `_clear_dependency` 自己（`agents/s07_task_system.py:262-275`）：

```python
def _clear_dependency(self, completed_id: int):
    """Remove completed_id from all other tasks' blockedBy lists."""
    unblocked = []
    for f in self.dir.glob("task_*.json"):
        task = json.loads(f.read_text())
        if completed_id in task.get("blockedBy", []):
            task["blockedBy"].remove(completed_id)
            self._save(task)
            if not task["blockedBy"]:
                unblocked.append(task["id"])

    # Verbose: 显示哪些任务被解锁了
    if unblocked:
        print(f"  → task_{completed_id} 完成，解锁了: {unblocked}{RESET}")
```

逐行拆开看：

- **`self.dir.glob("task_*.json")`** —— 暴力扫描整个 `.tasks/` 目录。这是 O(N) 的——任务越多越慢，但任务通常就几十条，无所谓。如果未来任务数 >1000，可以加一个反向索引（"谁依赖我"），但这是教学版，刻意保持简单。
- **`if completed_id in task.get("blockedBy", []):`** —— 只动那些**真的依赖刚完成任务**的文件。其他文件读一下就过，不写盘。
- **`task["blockedBy"].remove(completed_id)` + `self._save(task)`** —— 改内存里的 list，写回磁盘。注意这里**没有文件锁**——s07 是单进程的简化版，s09 多 Agent 时这一步就要小心了（两个 Agent 同时改同一个 task 文件会丢更新）。
- **`unblocked` 列表** —— 这是源码里一个值得注意的细节：它**不是**记录"我从谁的 blockedBy 里抹掉了 completed_id"，而是记录"抹掉之后 blockedBy **彻底变空**的任务"。区别在于：

  ```
  task_3.json: blockedBy=[1, 2]
  完成 task_1 → 抹掉 1 → blockedBy=[2]   ← 不算 unblocked（还在等 task_2）

  task_2.json: blockedBy=[1]
  完成 task_1 → 抹掉 1 → blockedBy=[]    ← 算 unblocked（真的可以开干了）
  ```

  也就是说 `unblocked` 是"现在**可以立刻领取**的任务"，不是"被影响的任务"。这个区分对 LLM 很重要——它看到 verbose 输出 `→ task_1 完成，解锁了: [2]` 的时候，知道的是"task_2 现在可以做了"，而不是"task_2 的状态被改了一下"。

- **最后那行 `print`** —— 仅供 verbose 输出用，给屏幕前的人看。`_clear_dependency` 不返回 unblocked 列表给 LLM——LLM 想知道"还有什么可以做"得自己再调一次 `task_list`。这是个克制的设计：TaskManager 替 LLM 管图的传播，但**不**主动喂给它"接下来应该做什么"，那是 LLM 自己的判断。

**LLM 不需要手动管理依赖更新。** 它只要说 `task_update(task_id=1, status="completed")`，TaskManager 就会扫描所有任务文件，自动解锁所有依赖 task_1 的任务。

例子：

```
完成前:
  task_2: blockedBy=[1]
  task_3: blockedBy=[1, 2]

调用 task_update(1, "completed")
  ↓ _clear_dependency(1)
  ↓ 扫描所有 task_*.json
  ↓ task_2 的 blockedBy 包含 1 → 移除 → blockedBy=[]
  ↓ task_3 的 blockedBy 包含 1 → 移除 → blockedBy=[2]

完成后:
  task_2: blockedBy=[]      ← 解锁了！
  task_3: blockedBy=[2]     ← 还在等 task_2
```

这是 s07 最优雅的设计：**LLM 表达"完成"的意图，TaskManager 处理图的传播**。LLM 不需要自己遍历任务列表更新依赖。

---

## 概念 5：持久化的真正含义

**s06 的 context compact 触发后，messages 被替换为 summary。如果你的任务只在 messages 里（比如 s03 的 todo），就丢了。** 但 s07 的任务在磁盘上，压缩不影响它们：

```
压缩前:
  messages = [...20 条消息，包含创建任务的对话...]
  .tasks/ = [task_1.json, task_2.json, task_3.json]    ← 磁盘上

压缩后:
  messages = [{"role": "user", "content": "[Compressed summary]..."}]
  .tasks/ = [task_1.json, task_2.json, task_3.json]    ← 磁盘上，没变！

下一轮 LLM 调用 task_list:
  → 仍然能看到所有任务！
```

**这是把状态从"对话上下文"中分离出来的关键设计。** s06 解决了"messages 太大"，但不能解决"压缩后丢失任务进度"。s07 通过把任务存在文件系统里，让任务进度独立于 messages 存在。

更进一步：**重启 Agent 后，TaskManager 会扫描 `.tasks/` 目录，从最大 ID 继续生成新任务**。所以你今天创建了 task_1/2/3，明天重启 Agent，再创建任务时 ID 会从 4 开始——任务系统的状态完整保留。

**亲眼见证一下这个现象：** 等会儿你按下面 "自己动手试试" 表格里的 4 个 prompt 顺序跑一遍，每个 prompt 都会**重启一次 Agent**（一次 Python 进程），但 ID **不会**从 1 重新开始：

```
跑 example1 (prompt: "Create 3 tasks: Setup project, Write code, Write tests..."):
  → 进程启动，扫描 .tasks/，发现是空的，_next_id = 1
  → 创建 task_1, task_2, task_3
  → 进程结束。.tasks/ 留下 3 个 JSON 文件。

跑 example2 (prompt: "List all tasks and show the dependency graph"):
  → 进程启动，扫描 .tasks/，发现 3 个文件，_next_id = 4
  → verbose 输出会先打印 "──── 启动时已有任务 ────"，列出 example1 留下的 task_1/2/3
  → LLM 调 task_list，看到的是 example1 的产物，不是新创建的
  → 进程结束。

跑 example3 (prompt: "Complete task 1 and then list tasks..."):
  → _next_id = 4，但这个 prompt 不创建新任务，只 update task_1
  → "task 1" 指的还是 example1 创建的那个 task_1
  → 进程结束。

跑 example4 (prompt: "Create a task board for refactoring..."):
  → _next_id = 4，新建的任务从 task_4 开始一路往上
  → .tasks/ 里现在混着 example1 的旧任务和 example4 的新任务
```

这正是"持久化"在你眼皮底下的具体表现——**进程死了，状态还在**。`s07_task_system.py:482-485` 的启动横幅 "启动时已有任务" 就是为这一刻准备的，让你一眼看到上一次跑剩下的东西。

也正因为这样，**如果你想让某个例子从干净状态开始，得自己 `rm -rf .tasks/`**。教程没有自动清理，是故意的——清理掉就看不到持久化了。如果你跑 example4 时 verbose 输出里冒出来一堆 task_1/2/3 不属于这次 prompt 的任务，别奇怪，那是 example1 留下的"考古层"。

---

## 概念 6：和 s03 TodoManager 的对比

| 维度 | s03 TodoManager | s07 TaskManager |
|---|---|---|
| 存储 | 内存（Python list） | 磁盘（JSON 文件） |
| 关系 | 无（扁平列表） | DAG（blockedBy） |
| 状态 | done / not done | pending / in_progress / completed |
| 唯一性约束 | "Only one in_progress at a time"（硬约束） | 无约束（可以多个 in_progress） |
| 持久化 | 无（s06 压缩后消失） | 有（独立于 messages） |
| 多 Agent 协作 | 不可能（内存隔离） | 可能（共享 .tasks/ 目录） |
| nag 提醒 | 有（s03 的 5 轮提醒机制） | 无（LLM 自己决定何时 list） |

**为什么 s07 不再需要 nag？** s03 的 nag 是为了避免 LLM "忘了用 todo 工具"。但 s07 的任务是持久化的——LLM 没用任务系统也不会"丢失工作进度"，因为它可以随时调 `task_list` 看磁盘上的状态。任务系统不是"提醒机制"，是"协调机制"。

不过，s03 的 todo 在简单场景下依然有价值——快速、不需要持久化、有强提醒。s07 的任务系统更适合复杂的、跨会话的工作。**两者并不互斥。**

---

## 概念 7：为什么这是后续课程的基础？

s07 看起来只是"持久化的 todo"，但它是后面所有协作机制的**地基**：

| 后续课程 | 怎么用 s07 |
|---|---|
| **s08 background tasks** | 后台执行的命令绑定到 task，进度反映在 task status 上 |
| **s09 agent teams** | 多个 Agent 共享同一个 `.tasks/` 目录，通过任务分配协作 |
| **s11 autonomous agents** | Agent 自动扫描 `.tasks/`，领取无主的（owner 为空的）任务 |
| **s12 worktree isolation** | 每个 task 在独立的 git worktree 里执行，避免冲突 |

`owner` 字段在 s07 里没用——它是为 s09+ 准备的。同样，`blockedBy` 在 s07 里只是记录依赖，但 s11 的 autonomous agent 会用它来决定"哪些任务现在可以领取"。

**s07 的真正价值不是 task_create/update/list/get 这 4 个工具，而是奠定了"任务作为共享状态"的协作模型。**

---

## verbose 输出里看什么

### 启动时

```
=== s07 verbose 模式 ===
TASKS_DIR = /home/.../learn-claude-code/.tasks
下一个 task ID: 4（启动时扫描了已有文件）

──────────── 启动时已有任务 ────────────
.tasks/ 目录状态：
  task_1.json: [x] #1 "Setup project"
  task_2.json: [>] #2 "Write code" blockedBy=[]
  task_3.json: [ ] #3 "Write tests" blockedBy=[2]
```

关键看：
- `下一个 task ID` —— 体现了"重启后接着之前的 ID 继续"
- 启动时打印已有任务 —— 让你看到"持久化"是真的，文件还在

### 每轮工具执行后

```
执行: task_create({"subject": "Setup project"})
输出: {"id": 1, "subject": "Setup project", "status": "pending", ...}
  创建 task_1.json: "Setup project"

.tasks/ 目录状态：
  task_1.json: [ ] #1 "Setup project"
```

关键看：每次任务工具调用后，磁盘状态的变化——`.tasks/ 目录状态` 一目了然。

### 完成任务时的依赖解锁

```
执行: task_update({"task_id": 1, "status": "completed"})
  task_1: pending → completed
  → task_1 完成，解锁了: [2]
```

`→ task_1 完成，解锁了: [2]` —— 这一行展示了 `_clear_dependency` 的效果：完成 task_1 自动解锁了依赖它的 task_2。

---

## 自己动手试试

```sh
python agents/s07_task_system.py
```

| 试这个 prompt | 观察什么 | 详细追踪 |
|---|---|---|
| `Create 3 tasks: "Setup project", "Write code", "Write tests". Make them depend on each other in order.` | LLM 是用 1 次 task_create 一次创建多个，还是分多次？怎么用 task_update 设置依赖？ | [example1.md](../../examples/s07/example1.md) |
| `List all tasks and show the dependency graph` | task_list 的输出格式是什么？LLM 如何把扁平列表渲染成 graph？ | [example2.md](../../examples/s07/example2.md) |
| `Complete task 1 and then list tasks to see task 2 unblocked` | `_clear_dependency` 的实际效果——task 2 的 blockedBy 自动从 [1] 变成 []？ | [example3.md](../../examples/s07/example3.md) |
| `Create a task board for refactoring: parse → transform → emit → test, where transform and emit can run in parallel after parse` | LLM 如何表达"并行"（菱形依赖图）？ | [example4.md](../../examples/s07/example4.md) |

---

## 这一课的关键收获

1. **状态从内存搬到磁盘是关键升级。** 这一步看似简单（一个 JSON 文件 vs Python list），但解锁了 context compact 抗性、跨会话延续、多 Agent 协作三大能力。

2. **`blockedBy` 把扁平列表变成了 DAG。** 从"做完一个勾掉一个"升级到"理解任务之间的因果关系"。这是让 Agent 处理"复杂工作"的前提。

3. **`_clear_dependency` 让 LLM 不用手动管理图的传播。** LLM 只表达"完成"的意图，TaskManager 自动处理"哪些任务被解锁"。这是把复杂逻辑藏在工具里、让 LLM 接口保持简单的好例子。

4. **s07 不实现并行执行，只表达并行可能性。** 真正的并行执行在 s08（线程）和 s12（worktree）。s07 的 DAG 是"协调的语言"——告诉 Agent "什么可以并行"，但执行还是顺序的。

5. **`owner` 字段是为未来准备的。** s07 里没用，但 s09 多 Agent 时它表示"这个任务归谁做"。s07 的设计已经为后续课程铺好了路。

6. **持久化的代价是状态管理的复杂性。** 任务文件可能损坏、可能不一致、可能跨进程被并发修改。当前 s07 没有处理这些问题——这是教学简化，生产环境需要文件锁、原子写入、JSON schema 校验等。
