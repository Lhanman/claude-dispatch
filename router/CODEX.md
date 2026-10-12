# dispatch · Codex 适配
上面的规则按 Claude Code 的叫法写，在 Codex 里这样对应（工具名以你实际拿到的工具列表为准）：
- **命令行工具不在 PATH 里**：`dispatch-verify`、`dispatch-usage`、`dispatch-kb`、`dispatch-pages` 在 `{{BIN_DIR}}`，用绝对路径调用。
- **子 agent**：用 `spawn_agent`。`dispatch:scout`、`dispatch:reviewer`、`dispatch:builder` 对应角色 `dispatch_scout`、`dispatch_reviewer`、`dispatch_builder`，由 `{{BIN_DIR}}/dispatch-codex-setup` 生成；角色不存在就不指定角色，把对应 agent 文件里的职责写进委托。每次 spawn 都显式写 `model` 和 `reasoning_effort`，并用 `fork_turns: "none"` 给干净的上下文。
- **模式与命令**：Plan 模式 = `/plan`；`/clear` = `/new`；`/compact` 同名。
- **OpenSpec**：`/opsx:propose` 这类命令在 Codex 里是 `$openspec-propose`，以 `openspec init` 打印的为准。
- **项目指令文件**是 AGENTS.md，验证矩阵写在那里。
