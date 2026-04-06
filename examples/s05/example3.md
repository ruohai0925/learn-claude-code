# s05 实际运行追踪：LLM 从描述中选对 skill（语义匹配）

> prompt: `I need to do a code review -- load the relevant skill first`
>
> 结果：2 轮，1 次 `load_skill("code-review")` 调用。LLM 从"code review"这个关键词匹配到了 `code-review` skill，正确选择了它。
>
> **重点观察：** 用户没有说 `load_skill("code-review")`，只说了 `"I need to do a code review"`。LLM 需要从 system prompt 里的 4 个 skill 描述中，判断哪个最匹配。这是 Layer 1 描述质量的检验——描述写得好，LLM 才能选对。

---

## 上下文：messages 已经有 7 条

接续 example1 + example2 的会话，messages 里已经积累了：

```
messages = [
  [0] user: "What skills are available?"
  [1] assistant/text: "Based on my system configuration, here are the **4 skills**..."
  [2] user: "Load the agent-builder skill and follow its instructions"
  [3] assistant/tool_use: load_skill({"name": "agent-builder"})
  [4] user/tool_result: "<skill name="agent-builder">..."     ← 4176 字符的 body，还在！
  [5] assistant/text: "The **agent-builder** skill is now loaded!..."
  [6] user: "I need to do a code review -- load the relevant skill first"    ← 新输入
]
```

注意 [4]——agent-builder 的 body 还在 messages 里。虽然这次要做 code review，和 agent-builder 无关，但那 4176 字符仍然会被发送给 API。**这就是 skill body 持久化的代价。**

---

## 第 1 轮：LLM 语义匹配选对 skill

**终端输出：**

```
────────────────── 轮次 1: 回复 ──────────────────
response.stop_reason = "tool_use"
response.content = [
  ToolUseBlock: name="load_skill", id="toolu_01F6Wjxbnn9wBUai1D53L6Wd"
    input={"name": "code-review"}
]

────────────────── 轮次 1: 执行工具 ──────────────────
加载 skill: "code-review"
返回内容 (4101 字符):
<skill name="code-review">
# Code Review Skill

You now have expertise in conducting comprehensive code reviews. Follow this structured approach:

## Review Checklist

### 1. Security (Critical)
...
```

**解读：** 用户说 `"I need to do a code review"`，LLM 选择了 `load_skill("code-review")`。匹配过程：

1. LLM 看到 system prompt 里的 4 个 skill 描述
2. `"code review"` 这个词直接出现在 `code-review` skill 的描述里：`"Perform thorough code reviews with security..."`
3. LLM 正确匹配

这个匹配看起来简单，但它依赖于 **Layer 1 描述的质量**。如果 `code-review` 的描述写成 `"Audit source files"`（没提 "review" 这个词），LLM 可能就匹配不上了。

**skill 描述里的 `"Use when user asks to review code, check for bugs, or audit a codebase"` 这一句特别关键——它直接告诉 LLM "什么时候该用我"。** 这是一种**触发条件的设计模式**：在描述里写明使用场景，帮 LLM 做出正确的选择。

---

## 第 2 轮：LLM 按照 skill 提供结构化回复

**终端输出：**

```
────────────────── 轮次 2: 回复 ──────────────────
response.stop_reason = "end_turn"
response.content = [
  TextBlock: "The **code-review** skill is loaded! I'm now equipped to perform thorough code reviews.

  ## Ready to Review Your Code

  I'll check across **5 dimensions**:

  | Area | What I Look For |
  |------|----------------|
  | Security | Injection flaws, hardcoded secrets... |
  | Correctness | Logic errors, race conditions... |
  | Performance | N+1 queries, blocking I/O... |
  | Maintainability | Naming, complexity, duplication... |
  | Testing | Coverage, edge cases... |

  ...
  What code should I review?"
]
```

**解读：** LLM 根据 code-review skill body 里的 "Review Checklist" 生成了 5 个维度的表格。这不是 LLM 凭空编的——而是从 skill body 里提炼的。看 skill body 原文：

```
### 1. Security (Critical)
### 2. Correctness
### 3. Performance
### 4. Maintainability
### 5. Testing
```

LLM 把这 5 个标题提炼成了一张简洁的表格，同时保留了用户说 `"load the relevant skill first"` 的后半部分暗示——它知道用户接下来要 review 代码，所以主动问 `"What code should I review?"`。

**LLM 是怎么做到这种"清晰凝练的总结"的？**

这个问题值得深入想想，因为它触及了 LLM 的核心能力。LLM 输出这段总结不是靠一套固定的"摘要算法"，而是多种能力的交汇：

**1. 训练数据里的"格式模式"**

Claude 在训练中见过海量的 Markdown 表格、技术文档、code review checklist。当它看到一段结构化的 skill body（5 个 `###` 标题，每个下面跟着 checklist），它自然会用训练中见过的"总结模式"来处理——把平行结构压缩成表格是它最熟悉的输出格式之一。这不是"理解了内容后决定用表格"，更像是"看到这种输入结构，输出表格是最高概率的 token 序列"。

**2. System prompt 和 skill body 的双重引导**

两个信号同时在引导 LLM 的行为：

- system prompt 说 `"Use load_skill to access specialized knowledge before tackling unfamiliar topics"`——暗示 LLM 的角色是"先学习再行动"
- skill body 的第一句话是 `"You now have expertise in conducting comprehensive code reviews. Follow this structured approach:"`——这句 `"You now have expertise"` 实际上是在**重新定义 LLM 的角色**

这就是为什么 skill body 的开头通常写成 `"You now have expertise in..."`（而不是 `"Here is information about..."`）。前者让 LLM 以"专家"身份说话，后者只是给 LLM 看一段参考资料。**措辞的微妙差异直接影响了 LLM 的输出风格**——"专家"会给出简洁的结构化分析，"读了一段资料的人"可能只会复述。

**3. 用户 prompt 里的隐含指令**

用户说的是 `"I need to do a code review -- load the relevant skill first"`，不是 `"load the code-review skill"`。那个 `"first"` 暗示了"加载 skill 只是第一步，接下来还有事要做"。LLM 从这个词推断出：加载完后应该准备好下一步（review 代码），而不是只确认"skill 已加载"就结束。所以它主动问 `"What code should I review?"`——这不是 skill body 里写的，而是 LLM 从对话意图中推理出来的。

**4. 这一切都是概率，不是规则**

需要强调：LLM 没有一个内部模块叫"总结器"或"意图分析器"。上面说的每一点，本质上都是**下一个 token 的概率分布**。当 context 里同时有 `"You now have expertise"`（skill body）+ `"I need to do a code review"` （用户意图）+ `"follow this structured approach"` （skill 指令）时，输出一张 5 行表格并问 `"What code should I review?"` 是概率最高的 token 序列。换一种 skill body 的措辞、换一种用户 prompt 的语气，输出可能完全不同——example4 的 continue vs restart 就是最好的证明。

---

## messages 快照：两个 skill body 并存

此刻 messages 共 9 条，其中**两个 skill body 同时存在**：

| 索引 | 内容 | 大小 |
|---|---|---|
| [4] | agent-builder body | ~4176 字符 |
| [8] | **code-review body** | **~4101 字符** |

这两个 body 加起来 ~8277 字符，每次 API 调用都会发送。而用户实际上只需要 code-review——agent-builder 是之前加载的，现在已经用不到了。**但我们没有机制去"卸载"一个已加载的 skill。** messages 只会增长，不会缩减（除非用 s06 的 context compact 机制）。

---

## 这个例子的关键收获

1. **Layer 1 描述质量决定匹配准确度。** 描述里写明 `"Use when user asks to review code"` 是关键——它相当于给 LLM 一个 if-then 规则。没有这句话，LLM 可能需要更复杂的推理才能选对 skill。

2. **skill body 只增不减。** 到 example3 结束，messages 里已经有 2 个 skill body（~8277 字符），而且无法卸载。这预示了 example4 的问题——context 越来越重。

3. **LLM 的"摘要能力"再次体现。** 4101 字符的 code-review body 被提炼成了一张 5 行的表格。LLM 不是在复读 skill 内容，而是在**理解并重新组织**它。
