# 第三方内容

本插件包含下列来自其他项目的 skill，均为 MIT 许可。

| 目录 | 来源 | 版权 | 改动 |
|---|---|---|---|
| `skills/grilling/`、`skills/grill-me/` | [mattpocock/skills](https://github.com/mattpocock/skills) | Copyright (c) 2026 Matt Pocock | `grill-me` 改为调用本插件内的 `dispatch:grilling` |
| `skills/test-driven-development/`、`skills/systematic-debugging/` | [obra/superpowers](https://github.com/obra/superpowers)，已同步到 v7.0.0（bb92a77） | Copyright (c) 2025 Jesse Vincent | 收窄了触发描述，使其按 dispatch 的级别触发；把对 `superpowers:*` 的引用改为本插件内的对应项（上游的 `verification-before-completion` 本插件没有，改为通过 `dispatch-verify` 验证）。最初引入的是 v4.0.0 之前的快照（2025-12-09 至 12-11，上游 commit 5845b52、030a222），后来按三方合并同步到 v7.0.0：带入 `find-polluter.sh` 的 `./` 前缀修复、调试示例不再打印密钥、`testing-anti-patterns.md` 换成上游重写的 `writing-good-tests.md`，以及上游的压缩（删掉 Real-World Impact 等复述段落） |
| `skills/code-review/` | [obra/superpowers](https://github.com/obra/superpowers) 的 `requesting-code-review`、`receiving-code-review` | Copyright (c) 2025 Jesse Vincent | 两个 skill 合并为一个并改写为中文；审查员改为本插件的 `dispatch:reviewer`，回传格式由该 agent 自带，不再内置 prompt 模板；触发条件改为按 dispatch 的 L2–L4 级别；另加了「先验证再派审查」一节；取改动范围改用上游 v6.4.1 的 `git merge-base origin/main HEAD` 写法，避免 main 前进后把它的新文件显示成被删除 |

MIT 许可全文见本仓库的 `LICENSE`，上述项目各自的许可条款与之相同，版权归各自作者所有。
