# s01 实际运行追踪（例 3）：不调工具的情况

> prompt: `What is 2+2?`
>
> 结果：1 轮 LLM 调��，0 次工具执行，2 条新 messages
>
> **重点观察：** LLM ��己判断不需要工具，直接回答，循环只跑 1 轮。

---

## 用户输入

**终端输出：**

```
s01 >> What is 2+2?

──────────────────── 用户输入 ────────────────────
query = "What is 2+2?"
```

---

## 轮次 1：发送给 LLM

**终端输出：**

```
──────────────────── 轮次 1: 发送给 LLM ────────────────────
messages = [
  [0]  user:      "What python files are in this directory?"
  [1]  assistant: bash({"command": "find ... -name \"*.py\" -type f"})
  [2]  user:      tool_result (find 输出)
  [3]  assistant: "Here are the Python files..."
  [4]  user:      "Create hello.py that prints hello, then run it"
  [5]  assistant: bash("echo ... > hello.py")
  [6]  user:      tool_result ("(no output)")
  [7]  assistant: bash("python hello.py")
  [8]  user:      tool_result ("hello")
  [9]  assistant: "Done! Created hello.py..."
  [10] user:      "What is 2+2?"               ← 新输入
]
```

**关键观察：** messages 已经有 11 条了！[0]-[9] 是例 1 和例 2 的完整历史。LLM ���看到之前的所有对话——这就是"记忆"的本质：**历史消息一直留在列表里**。

---

## 轮次 1：LLM 回复 → 直接给出答案

**终端输出：**

```
──────────────────── 轮次 1: LLM 回复 ────────────────────
response.stop_reason = "end_turn"
response.content = [
  TextBlock: "4"
]

──────────────────── 轮次 1: 循环结束 ────────────────────
stop_reason = "end_turn" → 不是 "tool_use"，return!
```

**解读：**

- `stop_reason = "end_turn"` → **第 1 轮就直接结束了！**
- `TextBlock: "4"` → LLM 不需要工具就能回答 2+2
- 没有 `ToolUseBlock`，没有执行任何命令

**LLM 背后有计算器吗？** 没有。LLM 没有调用任何工具，也没有真正"计算"。它就是一个"续写文本"的模型——训练数据里见过无数次 "2+2=4"，所以它"知道"下一个词应该是 "4"，和它知道"天空是蓝色的"一样的原理。它不是在算，而是在**回忆**。

这也是为什么简单数学 LLM 都对，但复杂数学（比如 `7429 × 8361`）LLM 经常算错——它没有真正的计算能力，只是在模式匹配。如果需要精确计算，LLM 应该调用 bash 跑 `python -c "print(7429 * 8361)"` 让计算机算，而不是自己"猜"。

**对应代码：** `agent_loop` 第 188-193 行

```python
messages.append({"role": "assistant", "content": response.content})

if response.stop_reason != "tool_use":    # "end_turn" != "tool_use" → True!
    return                                # 第 1 轮就 return 了！
```

循环里"执行工具"那段代码**根本没跑到**——因为在 `if` 那里就 `return` 了。

---

## 最终回答

**终端输出：**

```
──────────────────── 最终回答 ────────────────────
4
```

---

## 总结：三个例子的对比

| | 例 1 | 例 2 | 例 3 |
|---|---|---|---|
| prompt | 查看 py 文件 | 创建并运行���件 | 2+2 等于几 |
| LLM 调用轮次 | 2 | 3 | **1** |
| 工具执行次数 | 1 | 2 | **0** |
| 新增 messages | 4 | 6 | **2** |
| stop_reason 序列 | tool_use → end_turn | tool_use → tool_use → end_turn | **end_turn** |

**核心洞察：**

1. **LLM 自己决定要不要用工具。** 你的代码里没有任何"这个问题要用工具"的判断逻辑。`while True` 循环对所有情况都一样——区别全在 LLM 返回的 `stop_reason`。

2. **循环的两种路径：**

```
路径 A（例 1、例 2）：                    路径 B（例 3）：

response = LLM(messages)                 response = LLM(messages)
stop_reason == "tool_use"                stop_reason == "end_turn"
  → 执行工具                               → 直接 return
  → 结果塞回 messages                      （工具执行代码根本没跑到）
  → 继续循环
```

3. **history 是累积的。** 例 3 的 messages 里有 11 条消息（例 1 的 4 条 + 例 2 的 6 条 + 新输入 1 条）。每次新对话都追加在后面，不会清空。这就是 Agent 的"记忆"——不是什么特殊机制，就是 messages 列表不清空。
