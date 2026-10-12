#!/usr/bin/env bash
# Codex 烟测：在真实的 Codex 会话里确认 dispatch 的钩子触发了、规则注入了、#L 标记生效了。
#
# 为什么要单独一个脚本：tests/ 里的 Codex 测试只能验证清单、钩子脚本和角色文件，
# 验证不了"Codex 真的跑了钩子、模型真的看到了规则"，那一步需要登录和模型调用。
#
# 用法：evals/codex-smoke.sh [--real-home] [--dry-run]
#   默认      用一个临时的 CODEX_HOME，并把你现有的 auth.json 复制进去，不动你的 Codex 配置。
#   --real-home 直接装到你自己的 ~/.codex（临时目录里没有登录信息时用它）；
#               用完执行 `codex plugin remove dispatch@claude-dispatch` 卸掉。
#   --dry-run   只做安装和检查，打印将要执行的 codex exec 命令，不调用模型（不需要登录）。
#
# 要求：codex 命令可用。真实运行会花几美分的额度。
# 退出码：0 全部通过，1 有检查没过，2 环境不满足。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
real_home=0; dry=0
for a in "$@"; do
  case "$a" in
    --real-home) real_home=1 ;;
    --dry-run) dry=1 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "未知参数：$a" >&2; exit 2 ;;
  esac
done

command -v codex >/dev/null 2>&1 || { echo "找不到 codex 命令。" >&2; exit 2; }
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

if [ "$real_home" -eq 1 ]; then
  export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
else
  src="${CODEX_HOME:-$HOME/.codex}"
  export CODEX_HOME="$work/codex-home"
  mkdir -p "$CODEX_HOME"
  if [ -f "$src/auth.json" ]; then
    cp "$src/auth.json" "$CODEX_HOME/auth.json"
  elif [ "$dry" -eq 0 ]; then
    echo "在 $src 里没有找到 auth.json（可能登录信息在系统钥匙串里）。改用 --real-home，或先用 --dry-run 检查安装。" >&2
    exit 2
  fi
fi

fail=0
check() { if [ "$1" -eq 0 ]; then echo "✔ $2"; else echo "✘ $2"; fail=1; fi; }

echo "== 安装"
codex plugin marketplace add "$ROOT" >/dev/null 2>&1; check $? "添加 marketplace"
codex plugin add dispatch@claude-dispatch >/dev/null 2>&1; check $? "安装 dispatch"
codex plugin list 2>/dev/null | grep -q "dispatch@claude-dispatch.*installed" ; check $? "状态是 installed"

proj="$work/proj"; mkdir -p "$proj"; (cd "$proj" && git init -q)
codex_exec() { (cd "$proj" && codex exec --json --skip-git-repo-check "$1" 2>&1); }

p1='不要调用任何工具。如果你在会话开头收到了以"# dispatch ·"开头的规则，把这些规则的标题行原样各复述一行；一条都没有就只回答 NONE。'
p2='#L2 不要调用任何工具。只回答：按规则，这一轮的判定行应该怎么写？'

echo "== 真实会话"
if [ "$dry" -eq 1 ]; then
  echo "（--dry-run）将执行："
  echo "  codex exec --json --skip-git-repo-check '$p1'"
  echo "  codex exec --json --skip-git-repo-check '$p2'"
else
  out1="$(codex_exec "$p1")"
  printf '%s' "$out1" | grep -qF "dispatch · 分级调度"; check $? "SessionStart 钩子注入了路由规则"
  printf '%s' "$out1" | grep -qF "Codex 适配";          check $? "Codex 适配说明也注入了"
  out2="$(codex_exec "$p2")"
  printf '%s' "$out2" | grep -qF "〔L2";                 check $? "UserPromptSubmit 钩子识别了 #L2"
  if [ "$fail" -ne 0 ]; then
    echo
    echo "没过时先看这几点："
    echo "  1. 插件的钩子可能需要先批准：交互式运行一次 codex，按提示批准 dispatch 的钩子，再重跑本脚本。"
    echo "  2. 钩子输出超过约 2,500 token 时 Codex 会改成写临时文件，只给模型预览；tests/test_skills.py 守着这条线。"
    echo "  3. 用 --real-home 重试，排除临时 CODEX_HOME 带来的差异。"
  fi
fi

exit $fail
