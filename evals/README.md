# dispatch 行为 eval

`tests/` 只测脚本，这里测的是**路由规则有没有真的改变模型的行为**：用真实的 `claude -p` 会话，检查判定行、子 agent 调用和最终结果，并读出实际 token 用量。

会真的调用模型：花 token，结果有随机性。所以不在 `unittest discover` 里，要点名场景才跑。

```bash
python3 evals/run_eval.py --list
python3 evals/run_eval.py l0-typo l1-bugfix classify-l3        # 启用插件，检查行为
python3 evals/run_eval.py --all --compare --runs 3             # 每个场景用"启用 / 不启用"各跑 3 次，对比用量
```

## 场景

| 场景 | 检查什么 |
|---|---|
| `l0-typo` | 一句话能说清的改动：没有判定行，不派子 agent，文件确实改对了 |
| `l1-bugfix` | 位置明确的小 bug：不升到 L2 以上，不派子 agent，测试通过 |
| `classify-l3` | 软删除 + 改接口 + 数据迁移：判为 L2 或 L3，且在被要求"先别动手"时没有改任何文件 |

每个场景是 `evals/scenarios/<名字>/`：`scenario.json`（提示词和检查项）加可选的 `repo/`（起始文件）。检查项的类型见 `run_eval.py` 里的 `check()`。

## 能测什么、不能测什么

- **能测**：定级是否合理、小任务有没有被流程拖重、插件的固定开销（规则和 skill 描述）在小任务上占多大比例。
- **测不了**：L2 以上的完整流程。`claude -p` 是无人值守的，Plan 模式的批准、grilling 的提问都没有人回答，流程会停在半路。要测 L3 的整条链路，得自己手动跑两遍，用 `dispatch-usage` 对比两个会话。
- **单次结果只是个例**。模型有随机性，`--runs 3` 以上才能看出趋势；两组差距小于组内波动时，别下结论。

## 比较两个版本的固定开销

```bash
git worktree add /tmp/dispatch-old <旧版本的提交>
python3 evals/run_eval.py l0-typo --runs 5 --plugin-dir /tmp/dispatch-old
python3 evals/run_eval.py l0-typo --runs 5
```

`l0-typo` 的任务几乎没有内容，两次的"新增"差额基本就是两个版本常驻规则的差额。

## 安全

每个场景在临时目录的全新 git 仓库里运行，权限模式是 `acceptEdits` 加一份工具白名单（`run_eval.py` 的 `ALLOWED`），不用 `bypassPermissions`。白名单之外的命令会被拒绝，并计入输出里的"拒绝"列：**有拒绝的那一行用量不可信**，因为被拒的命令会让模型多绕几轮，先放宽白名单再比。每次运行有美元上限（`--budget`，默认 0.5）。
