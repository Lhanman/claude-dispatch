# dispatch · 分级调度

一个 Claude Code 插件：先判断任务有多复杂，再决定走多重的流程。小事直接做，大事才请出提问、规格文档和子 agent。

与技术栈无关。项目特有的内容（构建和验证命令）由 `/dispatch:setup` 写进各项目自己的 CLAUDE.md，不放在插件里。

## 五个级别

| 级别 | 什么样的任务 | 流程 |
|---|---|---|
| L0 直做 | 一句话能说清的改动 | 直接改，跑最小验证 |
| L1 快修 | 位置明确的 bug 或小功能，不超过 3 个文件 | 三行意图 → 修 bug 先写复现测试 → 改 → 验证 |
| L2 标准 | 跨模块、需求有歧义、新依赖，或碰到公共接口、数据模型、并发、删除 | scout（按需）→ 最多一轮提问 → Plan 模式 → 测试先行 → reviewer（碰到上述高风险项时） |
| L3 特性 | 一个会话做不完；改公共接口、持久化格式；新增完整能力 | grill-me → OpenSpec 提案 → 你审阅 → 分任务组执行 → Opus 终审 → 归档 |
| L4 史诗 | 新子系统或大改造 | 先定架构决策 → 拆成多个 L3 |

- 级别按**风险最高的那个信号**定，不按平均值。
- L1 起，回复第一行会写判定和依据，例如 `〔L2 · 新增依赖 + 跨两个模块〕`。L0 和非开发类请求（问答、调研、写文档、脑暴）不写判定行。
- 要脑暴时说「脑暴一下……」或执行 `/dispatch:brainstorm`：先框定问题，发散 8–12 个不同角度的想法，归成 3–4 个方向对比价值、成本和风险，再收敛到 1–2 个推荐方向；要落地就转入对应级别的流程，要留存就写成笔记或 HTML 文档。
- L0–L2 判定后直接执行；L3 以上先征得你同意。
- 执行中发现任务变大或变小，会升级或降级，并说明原因。完整规则见 [`router/ROUTER.md`](router/ROUTER.md)。

**手动指定级别**：在消息里任意位置写 `#L0`–`#L4`，例如 `#L1 修一下分页越界`。你指定的级别是下限：不会降到它以下；执行中出现升级信号时，会先停下说明原因和建议级别，你回复 `#L3` 这样的标记确认后才升级，判定行写成 `〔L1→L3 · 用户确认〕`。

每次手动指定（包括升级确认）都会在 `~/.claude/dispatch/overrides.log` 记一行：时间、级别、目录、本会话上一次指定的级别。它反映自动判定哪里不准，可以拿来修订 `ROUTER.md`。

## 模型与子 agent

设计目标是省 token：只有在能节省主会话上下文、或需要独立判断时，才派子 agent。

| 角色 | 模型 | 什么时候用 |
|---|---|---|
| 主会话 | 由你的设置决定 | 所有任务 |
| `dispatch:scout` | Haiku 4.5，只读，不加载 CLAUDE.md | 要读 5 个以上文件，或进入不熟悉的区域 |
| `dispatch:reviewer` | Sonnet 5；L3 终审时指定为 Opus 5 | L2 碰到高风险项时；L3 交付前一次。只看改动差异，只报正确性问题和遗漏的需求 |
| `dispatch:builder` | Sonnet 5 | 规格明确的机械性任务组，或 L4 的并行分支 |
| 验证 | 不用模型 | `dispatch-verify` 脚本 |

`dispatch-verify <命令>` 执行验证命令，把完整日志写入临时文件，只回显退出码、报错行和末尾几行。构建和测试的长输出不进入上下文。

各模型方案的相对消耗（用 API 价格作权重估算，只用于比较高低）：

| 主会话 | 子 agent | 相对消耗 |
|---|---|---|
| Fable 5.1 xhigh | 全部继承主模型 | 100% |
| Opus 5 xhigh | 本插件的编制 | 约 28% |
| Opus 5 medium | 本插件的编制，builder 常用 | 约 23% |
| Sonnet 5 | 本插件的编制 | 约 12% |

### 建议的全局设置（可选，插件不会替你改）

- 主会话模型和 thinking 强度是最大的消耗来源，用 `/model` 和 `/effort` 调整。Pro 订阅的官方默认模型是 Sonnet 5。
- 主会话用 Sonnet 时，L3 规划前可以切到 `/model opusplan`：规划用 Opus，执行用 Sonnet。
- 在 `~/.claude/settings.json` 的 `env` 里加 `"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"`。Claude Code 内置的 Explore、Plan 等 agent 默认继承主模型，加了这一条，即使主会话用 Opus 或 Fable，它们也不会跟着变贵。本插件的 agent 在各自文件里写明了模型，优先级更高，不受影响。
- 不要同时启用另一套"每个任务都强制走流程"的插件（例如 superpowers）。两套路由规则同时运行会互相冲突，也会重复占用上下文。

## 安装

**本机开发用（改动立即生效）**：把仓库软链到 skills 目录，然后在会话里执行 `/reload-plugins`。

```bash
ln -s ~/workbench/claude-dispatch ~/.claude/skills/dispatch
```

**其他机器**：把仓库推到 git 托管后，通过插件市场安装。

```bash
claude plugin marketplace add <仓库地址或本地路径>
claude plugin install dispatch@claude-dispatch
```

两种方式只能选一种，否则同一个插件会加载两次。

## 在一个项目里启用

在项目目录下执行 `/dispatch:setup`。它会：

1. 探测项目的构建方式，拟出 L0–L3 各级的验证命令，给你确认；
2. 把「dispatch 验证矩阵」写进项目的 CLAUDE.md；
3. 检查项目是不是 git 仓库（reviewer 要看改动差异，L4 并行要用 worktree）；
4. 检查 OpenSpec 是否就绪（L3 以上用到）。没有的话，L3 会退回到把方案写进 `docs/plans/`。

不执行 setup 也能用：路由规则会从构建文件推断验证命令。

## 个人知识库（可选）

可以把一个按目录组织的 Markdown 笔记库（例如 Obsidian 库）接进工作流：动手前先查已有的方案和踩坑记录，做完后把值得保留的内容沉淀回去。插件直接读写文件，不需要 Obsidian 在运行，也不经过 MCP。

**配置**：写在本机的 `~/.claude/dispatch/config` 里，不放在插件中。`/dispatch:setup` 会问你要不要配置。

```ini
kb_dir=~/notes            # 知识库目录
kb_exclude=copilot,assets # 不参与检索的顶层目录（可选）
```

每个项目在各自的 CLAUDE.md 里写明自己对应的子目录，由 setup 写入：`## dispatch 知识库` 下面一行 `目录：<子目录>/`。

**查**：L2 以上开工前执行。为了少占上下文，分三步逐层打开：

```bash
dispatch-kb search 导出 内存 -d 订单系统   # 每篇笔记一行：路径 │ 类型 │ 日期 │ 摘要
dispatch-kb outline 订单系统/订单导出改为分批流式写出.md  # 摘要 + 带行号的标题大纲
# 然后只读需要的那一节
```

检索的规则：

- 同一个概念的几种说法用 `|` 连成一个词，例如 `报错|故障|异常`，任一说法命中都算；
- 只列命中词数最多、分数不低于第一名 1/4 的结果；长笔记按篇幅打折，不因篇幅长而靠前；
- 同一篇的多个版本（简版、修订版、v2、终版……）只显示最新的一篇并注明「另有 N 个版本」，加 `--all` 查看全部。

另有 `dispatch-kb dirs`（顶层目录和笔记数）和 `dispatch-kb list [子目录]`。

**写**：L3 归档后，或 L2 得出值得保留的方案、决策、根因时，会提议执行 `/dispatch:note`。写入前一定先给你看路径和要点，你确认后才写。笔记格式固定，方便检索：

- frontmatter 包含 `title`、`type`（方案 / 决策 / 踩坑 / 指南）、`project`、一句话 `summary`、`tags`、`created`、`updated` 和 `source: dispatch`；
- 正文第一节是「结论」，其余小节按类型固定；
- 每篇不超过 150 行，超出就拆；代码只写 `路径:行号`，不贴大段代码。

没有配置知识库时，这部分规则不会注入会话，不占上下文。

## 文档站（可选）

把生成的 HTML 文档（包括 Artifact 页面）发布到一个静态站点，例如 GitHub Pages，积累成一套可以浏览、搜索的文档库。站点目录页按 `catalog.json` 自动生成，支持搜索和按标签筛选。

**配置**：写在 `~/.claude/dispatch/config`。

```ini
pages_repo=~/sites/me.github.io   # 站点仓库的本地目录（需要配置好 git 远程地址）
pages_url=https://me.github.io    # 站点网址
pages_title=我的文档               # 目录页标题
pages_deny=公司名,内部项目名         # 发布前拦截的敏感词
pages_docs_dir=文档                # 文档根目录（可选，默认「文档」）
pages_misc=其他                    # 没有项目时放的目录（可选，默认「其他」）
```

**发布**：

```bash
dispatch-pages publish page.html --slug my-page --desc "一句话摘要" --tags 标签1,标签2 --project 项目
```

脚本会依次：做敏感检查 → 补全 HTML 外壳（Artifact 页面没有 `<head>`）→ 写入 `文档/<项目>/<标题>.html` → 更新 `catalog.json`、目录页和仓库 README → 提交并推送。

文件按项目分目录、用中文标题命名，在本地也能一眼找到；不属于任何项目的放在 `文档/其他/`。slug 是每篇文档不变的英文标识，同一个 slug 再次发布就是更新；标题或项目变了，文件会跟着改名或换目录。

**网址用英文**：线上网址一律是 `<站点>/p/<slug>/`，不会出现中文路径。脚本会在站点仓库里生成 `.github/workflows/pages.yml` 和 `.github/build-site.py`，推送后由 GitHub Actions 按 `catalog.json` 把中文路径的文档复制成 `p/<slug>/index.html` 再上线。第一次使用前，要在站点仓库的 Settings → Pages → Source 选择 **GitHub Actions**。

**敏感检查**：本机绝对路径、邮箱、疑似密钥、`pages_deny` 里的词，以及用到 Artifact 专属能力（`claude.use`）的页面，命中就不发布，退出码 3。确认无妨后用 `--allow 词,词` 放行。私有 Artifact 链接只提醒，不拦截。

**触发**：发布 Artifact 页面后，PostToolUse hook 会提示主会话执行上面的命令，并带上文件路径和 slug；已经发布过的页面会提示按更新处理。

其他命令：`dispatch-pages list`、`search <词>`、`check <文件>`、`remove <slug>`、`rebuild`。

> GitHub Pages 站点是公开的，即使仓库是私有的也一样。发布之前，靠敏感检查把关。

## 常驻开销

每个会话固定增加的上下文：`ROUTER.md` 全文（配置了知识库时再加 `KB.md` 约 250 token，配置了文档站再加 `PAGES.md` 约 100 token；合计约 2.3k），加上各 skill 和 agent 的一行描述。查看实测值：

```bash
claude plugin details dispatch
```

skill 的正文只在被调用时才加载。没有 `#L` 标记时，hook 不输出任何内容。两个 hook 都是本地脚本，不调用模型。

## 目录

```
.claude-plugin/   plugin.json、marketplace.json
router/           ROUTER.md 路由规则；KB.md、PAGES.md 知识库和文档站规则（配置了才注入）
hooks/            hooks.json；session-start.sh 注入规则；prompt-submit.sh 识别 #L0–#L4；Artifact 发布后提示同步到文档站
bin/              dispatch-verify、dispatch-kb、dispatch-pages，插件启用期间自动加入 PATH
agents/           scout、reviewer、builder
skills/           setup、note、brainstorm、grill-me、grilling、test-driven-development、systematic-debugging
```

## 依赖

- bash；python3（解析 hook 输入和 `dispatch-kb` 用到；没有 python3 时，hook 退回到文本匹配，知识库和文档站功能不启用）。
- [OpenSpec](https://github.com/Fission-AI/OpenSpec)（可选，L3 以上用到）：`npm i -g @fission-ai/openspec`，在项目里执行 `openspec init --tools claude`。

## 许可

MIT。包含的第三方 skill 见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
