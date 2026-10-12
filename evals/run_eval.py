#!/usr/bin/env python3
"""dispatch 行为 eval：用真实的 `claude -p` 会话检查路由规则有没有生效，并读出实际 token 用量。

和 tests/ 的区别：tests/ 只测脚本，这里会真的调用模型，花 token、有随机性，所以默认不跑，必须点名场景。

  python3 evals/run_eval.py --list
  python3 evals/run_eval.py l0-typo l1-bugfix            启用插件跑，检查行为
  python3 evals/run_eval.py --all --compare              每个场景分别用"启用 / 不启用"各跑一次，对比用量
  python3 evals/run_eval.py l1-bugfix --compare --runs 3 每组跑 3 次取平均（单次结果只是个例）

选项：--model（默认 claude-sonnet-5-5）、--max-turns（默认 25）、--budget（每次的美元上限，默认 0.5）、
--plugin-dir（默认本仓库；比较两个版本时，用 `git worktree add` 检出旧版本再指向它）。
每次运行的原始事件流写在 evals/runs/<时间>/ 下，出问题时翻它。

安全：每个场景在临时目录的全新 git 仓库里跑；权限模式是 acceptEdits 加一份工具白名单，
不开 bypassPermissions，白名单之外的操作会被拒绝并记在 permission_denials 里。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIOS = os.path.join(ROOT, "evals", "scenarios")
ALLOWED = ["Read", "Edit", "Write", "Glob", "Grep", "Task", "Skill",
           "Bash(python3:*)", "Bash(python:*)", "Bash(git:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(test:*)",
           "Bash(tail:*)", "Bash(head:*)", "Bash(grep:*)", "Bash(wc:*)", "Bash(command:*)",
           "Bash(dispatch-verify:*)", "Bash(dispatch-usage:*)"]


def scenario_names():
    return sorted(d for d in os.listdir(SCENARIOS) if os.path.isfile(os.path.join(SCENARIOS, d, "scenario.json")))


def load(name):
    with open(os.path.join(SCENARIOS, name, "scenario.json"), encoding="utf-8") as fh:
        return json.load(fh)


def prepare(name):
    """把场景自带的 repo/ 拷到临时目录，初始化成 git 仓库并提交。"""
    work = tempfile.mkdtemp(prefix=f"dispatch-eval-{name}-")
    src = os.path.join(SCENARIOS, name, "repo")
    if os.path.isdir(src):
        shutil.copytree(src, work, dirs_exist_ok=True)
    else:
        open(os.path.join(work, ".gitkeep"), "w").close()
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.name=eval", "-c", "user.email=eval@example.test", "commit", "-q", "-m", "init"]):
        subprocess.run(cmd, cwd=work, check=True, capture_output=True)
    return work


def run_claude(prompt, cwd, plugin, model, max_turns, budget, plugin_dir):
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--no-session-persistence",
           "--permission-mode", "acceptEdits", "--allowedTools", ",".join(ALLOWED),
           "--setting-sources", "project", "--model", model, "--max-turns", str(max_turns),
           "--max-budget-usd", str(budget)]
    if plugin:
        cmd += ["--plugin-dir", plugin_dir]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=900)
    events = []
    for line in proc.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    return events, proc.stderr


def summarize(events):
    """从事件流里取出检查要用的事实。只看主会话（parent_tool_use_id 为空）的消息。"""
    s = {"first_line": None, "agents": [], "skills": [], "plugins": [], "result": {}}
    for e in events:
        kind = e.get("type")
        if kind == "system" and e.get("subtype") == "init":
            s["plugins"] = [p.get("name") for p in e.get("plugins", [])]
        elif kind == "assistant" and not e.get("parent_tool_use_id"):
            for b in (e.get("message") or {}).get("content", []):
                if b.get("type") == "text" and s["first_line"] is None and b.get("text", "").strip():
                    s["first_line"] = b["text"].strip().splitlines()[0]
                elif b.get("type") == "tool_use":
                    if b.get("name") in ("Task", "Agent"):
                        s["agents"].append((b.get("input") or {}).get("subagent_type") or "general-purpose")
                    elif b.get("name") == "Skill":
                        s["skills"].append((b.get("input") or {}).get("skill"))
        elif kind == "result":
            s["result"] = e
    return s


def read(cwd, path):
    try:
        with open(os.path.join(cwd, path), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def check(c, s, cwd):
    t = c["type"]
    if t == "first_line_matches":
        return bool(re.search(c["pattern"], s["first_line"] or ""))
    if t == "first_line_not_matches":
        return not re.search(c["pattern"], s["first_line"] or "")
    if t == "agent_calls_at_most":
        return len(s["agents"]) <= c["n"]
    if t == "agent_type_called":
        return c["agent"] in s["agents"]
    if t == "skill_called":
        return c["skill"] in s["skills"]
    if t == "file_contains":
        return c["text"] in read(cwd, c["path"])
    if t == "file_not_contains":
        return c["text"] not in read(cwd, c["path"])
    if t == "command_passes":
        return subprocess.run(c["cmd"], shell=True, cwd=cwd, capture_output=True).returncode == 0
    if t == "cost_at_most_usd":
        return (s["result"].get("total_cost_usd") or 0) <= c["usd"]
    raise ValueError(f"未知的检查类型：{t}")


def usage(s):
    r = s["result"]
    u = r.get("usage") or {}
    new = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("output_tokens", 0)
    return {"new": new, "cache_read": u.get("cache_read_input_tokens", 0), "output": u.get("output_tokens", 0),
            "turns": r.get("num_turns", 0), "usd": r.get("total_cost_usd") or 0.0,
            "denied": len(r.get("permission_denials") or [])}


def run_one(name, plugin, args, outdir):
    scn = load(name)
    cwd = prepare(name)
    t0 = time.time()
    events, err = run_claude(scn["prompt"], cwd, plugin, args.model, args.max_turns, args.budget, args.plugin_dir)
    s = summarize(events)
    arm = "plugin" if plugin else "baseline"
    with open(os.path.join(outdir, f"{name}-{arm}-{int(t0)}.jsonl"), "w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    if not s["result"]:
        return {"name": name, "arm": arm, "error": (err or "没有拿到 result 事件")[:200]}
    results = [(c, check(c, s, cwd)) for c in scn["checks"]]
    if plugin and "dispatch" not in s["plugins"]:
        results.insert(0, ({"type": "plugin_loaded"}, False))
    shutil.rmtree(cwd, ignore_errors=True)
    return {"name": name, "arm": arm, "first_line": s["first_line"], "agents": s["agents"],
            "denied": len(s["result"].get("permission_denials") or []), "checks": results, "usage": usage(s)}


def mean(rows, key):
    return sum(r["usage"][key] for r in rows) / len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenarios", nargs="*")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--compare", action="store_true", help="每个场景再跑一组不启用插件的基线")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--max-turns", type=int, default=25)
    ap.add_argument("--budget", type=float, default=0.5)
    ap.add_argument("--plugin-dir", default=ROOT, help="要加载的插件目录；比较两个版本时指向另一个 git worktree")
    args = ap.parse_args()

    names = scenario_names()
    if args.list:
        for n in names:
            print(f"{n:<16}{load(n)['description']}")
        return 0
    chosen = names if args.all else args.scenarios
    unknown = [n for n in chosen if n not in names]
    if not chosen or unknown:
        print("请指定场景（或 --all）。" + (f"未知场景：{unknown}" if unknown else "") + f"\n可选：{', '.join(names)}", file=sys.stderr)
        return 2
    if not shutil.which("claude"):
        print("找不到 claude 命令。", file=sys.stderr)
        return 2

    outdir = os.path.join(ROOT, "evals", "runs", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(outdir)
    arms = [True, False] if args.compare else [True]
    failed = False
    table = []
    for name in chosen:
        for plugin in arms:
            rows = [run_one(name, plugin, args, outdir) for _ in range(args.runs)]
            for r in rows:
                label = f"{name} [{r['arm']}]"
                if "error" in r:
                    print(f"✘ {label}  运行失败：{r['error']}")
                    failed = True
                    continue
                bad = [c for c, ok in r["checks"] if not ok]
                # 基线组没有插件，行为检查对它没有意义，只看用量
                if r["arm"] == "plugin":
                    failed |= bool(bad)
                    print(f"{'✔' if not bad else '✘'} {label}  首行：{(r['first_line'] or '')[:40]!r}  子 agent：{r['agents'] or '无'}"
                          + (f"  拒绝 {r['denied']} 次" if r["denied"] else ""))
                    for c in bad:
                        print(f"    未通过：{json.dumps(c, ensure_ascii=False)}")
            ok_rows = [r for r in rows if "error" not in r]
            if ok_rows:
                table.append((name, "plugin" if plugin else "baseline", ok_rows))

    if table:
        print(f"\n{'场景':<14}{'组':<10}{'轮数':>6}{'新增':>10}{'缓存读':>11}{'输出':>8}{'USD':>9}{'拒绝':>6}")
        for name, arm, rows in table:
            print(f"{name:<14}{arm:<10}{mean(rows, 'turns'):>6.1f}{mean(rows, 'new'):>10,.0f}{mean(rows, 'cache_read'):>11,.0f}"
                  f"{mean(rows, 'output'):>8,.0f}{mean(rows, 'usd'):>9.4f}{mean(rows, 'denied'):>6.1f}")
        if any(mean(rows, "denied") for _, _, rows in table):
            print("\n注意：有权限拒绝。被拒绝的命令会让模型多绕几轮，这一行的用量不可信，先放宽 ALLOWED 再比。")
        if args.compare:
            print("\n（新增 = 新输入 + 缓存写 + 输出；基线组用的是同一个模型、同一份提示词，只是不加载 dispatch。"
                  f"每组 {args.runs} 次，次数少时只能当个例看。）")
    print(f"事件流：{outdir}")
    return 1 if failed else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
