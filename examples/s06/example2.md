# s06 实际运行追踪：继续读文件直到压缩再次触发（压缩后的"失忆"效应）

> prompt: `Keep reading files until compression triggers automatically`
>
> 结果：接续 example1（auto_compact 后 messages 只有 1 条 summary）。LLM 继续读文件，但因为压缩丢失了精确的文件列表，它开始**猜错文件名**（s03_todo.py、s05_skills.py、s06_compress.py 都不存在）。6 轮后 auto_compact 再次触发。
>
> **重点观察：** 压缩的代价在这里活生生体现——LLM 丢失了第一轮 `bash find` 的文件列表，只能从 summary 里的模糊信息猜文件名，频繁出错。这就是讲义里说的"有损压缩"的实际后果。

---

## 起始状态：example1 压缩后

```
token 估算: ~533 / 12000
messages = [
  [0] user: "[Conversation compressed. Transcript: ...]..."   ← example1 的 summary
  [1] assistant/text: "I'm ready to help! What would you like to work on?"
  [2] user: "Keep reading files until compression triggers automatically"
]
```

只有 3 条 messages，~533 token。LLM 从 summary 里知道"之前读过 14 个 agent 文件"，但**不知道具体的文件名列表**（那个 `bash find` 的输出已经被压缩掉了）。

---

## 第 1 轮：重新列出文件

LLM 先 `bash find` 列文件 + 尝试 `read_file` 读目录（失败，和 s04 例 1 同样的错误）。

---

## 第 2 轮：读 s01 和 s02（正常）

```
────────────────── 轮次 2: 回复 ──────────────────
  ToolUseBlock: name="read_file"  →  s01_agent_loop.py
  ToolUseBlock: name="read_file"  →  s02_tool_use.py
```

**正常。** LLM 从第 1 轮的 `bash find` 输出里看到了文件列表，选了前两个读。

---

## 第 3 轮：micro_compact 首次触发 + LLM 猜错文件名

```
────────────────── Layer 1: micro_compact ──────────────────
tool_result 总数: 4, 保留最近 3 个
替换了 1 个旧 tool_result → "[Previous: used ...]"

────────────────── 轮次 3: 回复 ──────────────────
  ToolUseBlock: name="read_file"  →  agents/s03_todo.py       ← 不存在！
  ToolUseBlock: name="read_file"  →  agents/s04_subagent.py   ← 正确
```

**`s03_todo.py` 不存在！** 正确的文件名是 `s03_todo_write.py`。

**LLM 不是"乱猜"——它在系统性地"简化"文件名。** 看后面几轮的错误也是同一个模式：

| LLM 猜的 | 正确的 | 简化了什么 |
|---|---|---|
| s03_**todo**.py | s03_**todo_write**.py | 丢了 `_write` |
| s05_**skills**.py | s05_**skill_loading**.py | 丢了 `_loading`，加了复数 |
| s06_**compress**.py | s06_**context_compact**.py | 换了同义词，丢了 `context_` |

而它猜**对**的 `s04_subagent.py` 恰好是名字最简短的——没有多余的后缀需要记住。

**为什么会这样？** 先看 LLM 此刻能看到什么。

查看 transcript 里保存的 messages，micro_compact 执行后的状态：

```
[0] user: "[Conversation compressed...]\n\n## Conversation Summary\n### What Was Accomplished\n
    A progressive series of Python agent harness implementations was reviewed..."
    → summary 里只提到了 s11、s12、s_full 三个文件名，完全没有 s01-s10 的文件名！
[1] assistant: "I'm ready to help!"
[2] user: "Keep reading files until compression triggers automatically"
[3] assistant: bash find + read_file(directory)
[4] user/tool_result: "[Previous: used bash]"    ← bash find 的文件列表被替换了！
    user/tool_result: "Error: Is a directory"
[5] assistant: read_file(s01) + read_file(s02)
[6] user/tool_result: (s01 完整内容)    ← read_file 被保留
    user/tool_result: (s02 完整内容)    ← read_file 被保留
```

**关键发现：summary 里根本没有 s03-s06 的精确文件名。** example1 的 auto_compact 总结时，LLM 只详细提到了 s11、s12、s_full（可能因为它们是"最近 3 个"被保留的 read_file 结果，summary 倾向于记录最后读的内容）。s01-s06 的文件名只存在于第 1 轮的 `bash find` 输出里——但那个输出已经被 micro_compact 替换成了 `"[Previous: used bash]"`。

所以 LLM 此刻**完全没有 s03 的精确文件名来源**。它只能靠：
1. **训练数据里的命名模式**——`s03_todo.py` 比 `s03_todo_write.py` 更"像"一个典型的 Python 文件名
2. **summary 里的功能描述**——知道 s03 是关于 "TodoWrite" 的，但从 "todo_write" 到文件名需要"生成"

**本质上这是"生成"和"检索"的区别。** 有精确数据时 LLM 做检索（从 context 里逐字复制，第 2 轮读 s01、s02 就是这样——当时 bash find 输出还没被替换）。没有精确数据时 LLM 做生成（从训练分布里采样，`s03_todo` 是比 `s03_todo_write` 更高概率的 token 序列）。

**原因链（回到 s06 的机制）：**
1. example1 的 auto_compact 生成了一个**不完整的 summary**——只详细提到 s11/s12/s_full，没有 s03 的文件名
2. example2 第 1 轮重新跑了 `bash find`（包含完整文件名），第 2 轮还能正确读 s01/s02
3. 第 3 轮前 micro_compact 把 bash find 结果替换成了 `"[Previous: used bash]"`——文件名来源彻底断了
4. LLM 从"检索模式"退化到"生成模式"，开始产出"看起来合理但不精确"的文件名

**这是 micro_compact 的一个意外后果：** 它替换了 bash find 的结果（因为 bash 不在 PRESERVE_RESULT_TOOLS 里），但 LLM 后来需要这个结果来确定文件名。**"保留 read_file、替换 bash" 的策略假设 bash 输出不重要——但包含文件列表的 bash 输出其实很重要。**

---

## 第 4 轮：继续猜错

```
────────────────── 轮次 4: 回复 ──────────────────
  ToolUseBlock: name="read_file"  →  agents/s05_skills.py     ← 不存在！
  ToolUseBlock: name="read_file"  →  agents/s06_compress.py   ← 不存在！

输出: Error: [Errno 2] No such file or directory
输出: Error: [Errno 2] No such file or directory
```

**两个都猜错了。** 正确的名字是 `s05_skill_loading.py` 和 `s06_context_compact.py`。LLM 在根据 summary 里的描述"推断"简短文件名——但推断不出实际的命名风格。

**micro_compact 此时的状态：**

```
tool_result 总数: 6, 保留最近 3 个
替换了 0 个旧 tool_result → "[Previous: used ...]"
保留了 1 个 read_file 结果（PRESERVE_RESULT_TOOLS）
压缩后 token 估算: ~10037
```

注意"替换了 0 个"——因为前 3 个旧 tool_result 里有 read_file 结果（被保护），micro_compact 没有可替换的东西。

---

## 第 5 轮：LLM 重新列文件——但搜索范围扩大了

```
────────────────── 轮次 5: 回复 ──────────────────
  ToolUseBlock: name="bash"
    input={"command": "find /home/yzeng/Codes/learn-claude-code -type f -name \"*.py\" | sort"}
  ToolUseBlock: name="bash"
    input={"command": "find /home/yzeng/Codes/learn-claude-code -type f | sort"}

────────────────── 轮次 5: 执行工具 ──────────────────
执行: bash(find ... -name "*.py" | sort)
输出 (50000 字符): ...
执行: bash(find ... -type f | sort)
输出 (50000 字符): ...
```

**LLM 从连续的 "No such file" 错误中学习，决定重新用 `bash find` 列出文件。** 这和 s04 例 1 里的"错误即教学"是同一个模式。

**但为什么输出有 50000 字符？** 列 14 个文件的路径最多也就 ~1000 字符。原因是 LLM 偷偷扩大了搜索范围：

| | 第 1 轮的 find | 第 5 轮的 find |
|---|---|---|
| 搜索路径 | `find .../agents -name "*.py"` | `find .../learn-claude-code -name "*.py"` |
| 范围 | 只搜 `agents/` 目录 | 搜**整个项目** |
| 匹配文件数 | 14 个 | **1087 个** |

整个项目下有 1087 个 .py 文件——大部分来自 `examples/s05/mcp-server/venv/` 里的 Python 依赖包（pip install 下载的源码）。14 个 agent 文件淹没在了 1073 个 venv 文件里。

第二个命令更夸张——`find ... -type f | sort` 列出了**所有类型的文件**（.py、.html、.md、.git/objects、node_modules……），输出直接撞上了 50000 字符的截断上限。

**为什么 LLM 扩大了搜索范围？** 因为它猜错了几个文件名后，不确定文件是不是在 `agents/` 下——也许文件在其他目录？所以它放大搜索范围来"确保找到"。这是一个合理但代价高昂的策略——token 从 ~10000 直接飙到 ~35000，触发了 Layer 2。

---

## Layer 2 再次触发

```
────────────────── Layer 1: micro_compact ──────────────────
tool_result 总数: 10, 保留最近 3 个
替换了 0 个旧 tool_result → "[Previous: used ...]"
保留了 4 个 read_file 结果（PRESERVE_RESULT_TOOLS）
压缩后 token 估算: ~35639

────────────────── Layer 2: 触发! token 估算 ~35639 > 12000 ──────────────────
原始: 13 条 messages → 压缩后: 1 条
```

**micro_compact 再次被"架空"**——10 个 tool_result 里 4 个是 read_file（被保护），3 个是最近的（被保留），剩下的要么太短（错误信息 ~100 字符）要么已经被之前替换过了。Layer 2 不得不接管。

---

## 第 6 轮：第二次压缩后

```
────────────────── 轮次 6 ──────────────────
token 估算: ~456 / 12000
messages = [
  [0] user: "[Conversation compressed. Transcript: ...]..."
]

最终回答: "I have the context from the compressed conversation.
The repository structure is clear — it's a learn-claude-code project..."
```

**LLM 又回到了"准备好了"的状态。** 这是第二次被压缩——之前读过的 s01-s04 文件内容再次丢失。

---

## 累积压缩损失的可视化

```
example1 开始:  messages = [用户输入]                      ~22 token

example1 轮次2: messages += [14个read_file结果]           ~60571 token
                    ↓ auto_compact
                messages = [summary_1]                     ~477 token

example2 轮次2-4: messages += [读s01,s02,s04 + 猜错×3]    ~10249 token

example2 轮次5: messages += [2个大的bash find]             ~35639 token
                    ↓ auto_compact
                messages = [summary_2]                     ~456 token
```

**summary_2 是 summary_1 的"再压缩"。** summary_1 总结了 14 个文件的内容，summary_2 总结了 "之前有个 summary + 后来又读了几个文件 + 猜错了一些文件名"。信息在每次压缩时都衰减——这就是讲义里说的"累积压缩损失"。

---

## 这个例子的关键收获

1. **压缩的代价是"失忆"。** LLM 丢失了精确的文件列表，开始猜文件名，频繁出错。这不是 bug——是有损压缩的必然后果。

2. **"保留 read_file、替换 bash" 的策略有盲区。** 包含文件列表的 `bash find` 输出其实和 read_file 一样重要——但当前代码只保护 read_file。更智能的策略可能需要根据内容类型（而不仅仅是工具名）来决定是否保留。

3. **LLM 从错误中恢复的能力依然有效。** 猜错文件名 → 收到 "No such file" 错误 → 重新 `bash find` 列文件。压缩管道不会阻碍 LLM 的自我纠正能力。

4. **累积压缩损失是真实的。** 两次 auto_compact 后，LLM 对项目的理解越来越模糊——从"知道 14 个文件的具体内容"退化到"知道这是一个 agent 教程项目"。
