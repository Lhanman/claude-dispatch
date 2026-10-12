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
| `spec-check` | L3 规格自检：补「审查重点」，显式指定 sonnet 派 `general-purpose` 子 agent 通读，自检阶段不实现 |
| `l3-execute` | L3 执行阶段（三个任务组的小项目）：连续做完、写账本、勾选 tasks.md、遇到歧义自己裁决、最后用子 agent 终审 |

每个场景是 `evals/scenarios/<名字>/`：`scenario.json`（提示词和检查项）加可选的 `repo/`（起始文件）。检查项的类型见 `run_eval.py` 里的 `check()`。可选字段：`repo_from`（复用别的场景的起始文件）、`max_turns`、`budget`（L3 比小任务长，要单独放宽）、`baseline_prompt`（`--compare` 的基线组用这条提示词——基线里没有 dispatch，提示词不能提 `dispatch:xxx`）。

## 用量是怎么算的

有后台子 agent 时，一次运行会产生**多个** `result` 事件：主 agent 先在"等子 agent"处结束一次，被通知唤醒后再结束一次。`total_cost_usd` 和 `modelUsage` 是累计的，顶层 `usage`、`num_turns`、`permission_denials` 是按段的，而且顶层 `usage` 只算主模型。所以 token 取最后一个 `result` 的 `modelUsage`（含子 agent 用的模型），轮数和权限拒绝按段加总。这条逻辑有单测（`tests/test_evals.py`），因为我们自己踩过：首版只读最后一段，把一个 14 轮的运行记成了 2 轮。

## 能测什么、不能测什么

- **能测**：定级是否合理、小任务有没有被流程拖重、插件的固定开销（规则和 skill 描述）在小任务上占多大比例。
- **测不了**：L2 以上从头到尾的完整流程。`claude -p` 是无人值守的，Plan 模式的批准、grilling 的提问都没有人回答，流程会停在半路。所以 L3 是拆成两段测的：`spec-check`（规格出来之后）和 `l3-execute`（规格审完之后），前面的 grill-me 和 propose 两步没有覆盖。要测整条链路，得自己手动跑两遍，用 `dispatch-usage` 对比两个会话。
- **单次结果只是个例**。模型有随机性，`--runs 3` 以上才能看出趋势；两组差距小于组内波动时，别下结论。

## 比较两个版本的固定开销

```bash
git worktree add /tmp/dispatch-old <旧版本的提交>
python3 evals/run_eval.py l0-typo --runs 5 --plugin-dir /tmp/dispatch-old
python3 evals/run_eval.py l0-typo --runs 5
```

`l0-typo` 的任务几乎没有内容，两次的"新增"差额基本就是两个版本常驻规则的差额。

## Codex 烟测

`evals/codex-smoke.sh` 在真实的 Codex 会话里确认钩子触发、规则注入、`#L2` 标记生效。需要 `codex login`，会花几美分；`--dry-run` 只做安装和检查，不需要登录。这一步我们在没有登录的环境里写的，只跑过 `--dry-run`，真实会话部分需要你的机器验证。

## 安全

每个场景在临时目录的全新 git 仓库里运行，权限模式是 `acceptEdits` 加一份工具白名单（`run_eval.py` 的 `ALLOWED`），不用 `bypassPermissions`。白名单之外的命令会被拒绝，并计入输出里的"拒绝"列：**有拒绝的那一行用量不可信**，因为被拒的命令会让模型多绕几轮，先放宽白名单再比。每次运行有美元上限（`--budget`，默认 0.5）。
