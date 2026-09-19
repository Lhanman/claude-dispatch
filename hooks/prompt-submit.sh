#!/usr/bin/env bash
# UserPromptSubmit：识别用户消息里的 #L0–#L4 覆盖标记。
# 没有标记时不输出任何内容，不占上下文；不调用模型。
# 用户指定的级别是下限：执行中出现升级信号时，由模型停下来请用户回复 #Lx 确认，
# 这条确认消息会再次经过这里，于是升级也会记进日志。
input="$(cat)"

prompt="$input"
session=""
if command -v python3 >/dev/null 2>&1; then
  parsed="$(printf '%s' "$input" | python3 -c 'import json,sys
try:
    d = json.load(sys.stdin)
    print(d.get("session_id", ""))
    print(d.get("prompt", ""))
except Exception:
    pass' 2>/dev/null)"
  if [ -n "$parsed" ]; then
    session="$(printf '%s\n' "$parsed" | head -n 1)"
    prompt="$(printf '%s\n' "$parsed" | tail -n +2)"
  fi
fi

level="$(printf '%s' "$prompt" | grep -oE '(^|[^[:alnum:]#])#L[0-4]($|[^[:alnum:]])' | grep -oE 'L[0-4]' | tail -n 1)"
[ -z "$level" ] && exit 0

# 本会话上一次指定的级别（放在临时目录，系统会自动清理）
prev=""
if [ -n "$session" ]; then
  state_dir="${TMPDIR:-/tmp}"; state_dir="${state_dir%/}/dispatch-level"
  mkdir -p "$state_dir" 2>/dev/null
  state="$state_dir/$(printf '%s' "$session" | tr -cd '[:alnum:]-_')"
  [ -f "$state" ] && prev="$(cat "$state" 2>/dev/null)"
  printf '%s' "$level" > "$state" 2>/dev/null
fi

# 记录人工覆盖：这是"自动判定不准"的信号，供以后修订 ROUTER.md 时回看。
# 列：时间、级别、目录、本会话上一次指定的级别（没有则为空）
log_dir="${HOME}/.claude/dispatch"
mkdir -p "$log_dir" 2>/dev/null && printf '%s\t%s\t%s\t%s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$level" "$PWD" "$prev" >> "$log_dir/overrides.log" 2>/dev/null

if [ -n "$prev" ] && [ "$prev" != "$level" ]; then
  echo "dispatch：用户指定级别 ${level}（本会话上一次指定的是 ${prev}）。如果是同一个任务，这是用户对级别调整的确认：按 ${level} 的流程继续，已有的意图和问答结论带入，判定行写〔${prev}→${level} · 用户确认〕；如果是新任务，判定行写〔${level} · 用户指定〕。${level} 是下限，不要降到它以下；再出现升级信号时，停下说明信号和建议级别，请用户回复 #L 加级别确认后再升。"
else
  echo "dispatch：用户指定本次任务级别为 ${level}，判定行写〔${level} · 用户指定〕。${level} 是下限，不要降到它以下；执行中出现升级信号时，停下说明信号和建议级别，请用户回复 #L 加级别确认后再升。"
fi
exit 0
