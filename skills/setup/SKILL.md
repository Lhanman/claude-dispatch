---
name: setup
description: 为当前项目接入 dispatch 分级调度：探测构建方式，把各级别的验证命令写进项目 CLAUDE.md，并检查 git 与 OpenSpec 是否就绪。
disable-model-invocation: true
---

为**当前项目**接入 dispatch。dispatch 本身与技术栈无关，项目特有的事实只写进这个项目自己的 CLAUDE.md，不要改动插件里的任何文件。

## 1. 探测构建方式

查看项目根目录和主要子目录里的构建文件，例如 `package.json`（看 scripts）、`Makefile`、`justfile`、`Cargo.toml`、`go.mod`、`pyproject.toml`、`pom.xml`、`build.gradle(.kts)`、`*.sln`、`CMakeLists.txt`，以及 CI 配置（`.github/workflows/` 等）。CI 里实际在跑的命令最可信。

只读取，这一步不执行任何构建。多模块或多平台项目，弄清"只验证受影响的那一部分"该用什么命令。

## 2. 拟定验证矩阵

按"级别越高，验证越全"拟一张表，每一级都必须是能直接执行的命令：

| 级别 | 目的 | 命令 |
|---|---|---|
| L0 | 最快的检查：只编译或只做类型检查改动所在的部分 | … |
| L1 | 受影响部分的单元测试 + 编译 | … |
| L2 | 全部测试 + 静态检查 | … |
| L3 以上 | 完整构建，包含打包、链接等发布前步骤 | … |

项目确实没有某一级对应的命令时，写"同上一级"，不要编造命令。拿不准的命令先用 `dispatch-verify <命令>` 试跑一次确认。

把表给用户看，等用户确认或修改后再写入。

## 3. 写入项目 CLAUDE.md

在项目根目录的 CLAUDE.md 里新增或更新下面这一节。文件不存在就创建；已经有这一节就替换它，不要重复追加；不要改动文件里的其他内容。

```markdown
## dispatch 验证矩阵

验证命令一律通过 `dispatch-verify <命令>` 执行。

| 级别 | 命令 |
|---|---|
| L0 | … |
| L1 | … |
| L2 | … |
| L3 以上 | … |
```

## 4. 检查 git

执行 `git rev-parse --is-inside-work-tree`。不是 git 仓库时告诉用户：reviewer 拿不到改动差异，只能按文件列表审查；L4 的并行分支用不了 worktree。建议初始化 git，但**不要替用户执行** `git init`，除非用户明确同意。

## 5. 检查 OpenSpec（L3 以上用得到）

- 项目里已有 `openspec/` 目录：就绪，跳过。
- 没有，但 `openspec` 命令可用：问用户要不要执行 `openspec init --tools claude`。
- 命令不存在：告诉用户 L3 会退回到把方案写进 `docs/plans/`；需要时可用 `npm i -g @fission-ai/openspec` 安装。

## 6. 知识库（可选）

执行 `dispatch-kb path`。

- **已配置**：用 `dispatch-kb dirs` 看知识库的顶层目录，拟定这个项目对应的子目录。已有对应目录就复用，没有就用项目名。给用户确认后，写进项目 CLAUDE.md（已有这一节就替换）：

  ```markdown
  ## dispatch 知识库

  目录：<子目录>/
  ```

- **未配置**：问用户有没有个人知识库目录，例如 Obsidian 库或其他 Markdown 笔记目录。有的话，写入 `~/.claude/dispatch/config`：一行 `kb_dir=<目录>`；不想参与检索的顶层目录写成 `kb_exclude=<目录1>,<目录2>`。然后按上一条处理。没有就跳过。

## 7. 汇报

用几行话说明：写入了什么、git 和 OpenSpec 的状态、知识库对应的目录、还有哪些需要用户自己处理。
