#!/usr/bin/env bash
# UserPromptSubmit：识别用户消息里的 #L0–#L4 覆盖标记。
# 没有标记时不输出任何内容，不占上下文；不调用模型。
input="$(cat)"

if command -v python3 >/dev/null 2>&1; then
  prompt="$(printf '%s' "$input" | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("prompt",""))
except Exception:
    pass' 2>/dev/null)"
else
  prompt="$input"
fi

level="$(printf '%s' "$prompt" | grep -oE '(^|[^[:alnum:]#])#L[0-4]($|[^[:alnum:]])' | grep -oE 'L[0-4]' | tail -n 1)"
[ -z "$level" ] && exit 0

# 记录人工覆盖：这是"自动判定不准"的信号，供以后修订 ROUTER.md 时回看
log_dir="${HOME}/.claude/dispatch"
mkdir -p "$log_dir" 2>/dev/null && printf '%s\t%s\t%s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$level" "$PWD" >> "$log_dir/overrides.log" 2>/dev/null

echo "dispatch：用户指定本次任务级别为 ${level}。按 ${level} 的流程执行，判定行写〔${level} · 用户指定〕。"
exit 0
