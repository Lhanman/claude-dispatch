#!/usr/bin/env bash
# SessionStart：注入路由规则；在 Codex 里再追加适配说明；配置了知识库、个人笔记库、文档站时，再追加对应的规则。
# 没配置（或没有 python3）时只输出 ROUTER.md，不多占上下文。

root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cat "$root/router/ROUTER.md"

# 在 Codex 里运行时追加一段适配说明：Codex 给插件钩子同时设置 PLUGIN_ROOT 和 CLAUDE_PLUGIN_ROOT，
# Claude Code 只设后者。DISPATCH_HARNESS=codex|claude 可以手动指定（测试、排查用）。
# 用 bash 自带的替换而不是 python3，没有 python3 时这一段照样输出。
harness="${DISPATCH_HARNESS:-}"
if [ -z "$harness" ]; then
  if [ -n "${PLUGIN_ROOT:-}" ]; then harness=codex; else harness=claude; fi
fi
if [ "$harness" = codex ] && [ -r "$root/router/CODEX.md" ]; then
  echo
  codex_md="$(<"$root/router/CODEX.md")"
  printf '%s\n' "${codex_md//\{\{BIN_DIR\}\}/$root/bin}"
fi

# render <模板> <占位符> <值>：把模板里的 {{占位符}} 换成值后输出。
# 写 sys.stdout.buffer 而不是 sys.stdout：中文 Windows 上 stdout 默认按 GBK 编码，
# 直接 write 会在中文内容上抛 UnicodeEncodeError，规则就注入不进会话了。
render() {
  VALUE="$3" python3 -c 'import os,sys; sys.stdout.buffer.write(open(sys.argv[1],encoding="utf-8").read().replace("{{"+sys.argv[2]+"}}", os.environ["VALUE"]).encode("utf-8"))' "$1" "$2"
}

if kb="$("$root/bin/dispatch-kb" path 2>/dev/null)" && [ -n "$kb" ]; then
  echo; render "$root/router/KB.md" KB_DIR "$kb"
fi
if pd="$("$root/bin/dispatch-kb" personal-path 2>/dev/null)" && [ -n "$pd" ]; then
  echo; render "$root/router/PERSONAL.md" PERSONAL_DIR "$pd"
fi
if url="$("$root/bin/dispatch-pages" url 2>/dev/null)" && [ -n "$url" ]; then
  echo; render "$root/router/PAGES.md" PAGES_URL "$url"
fi
exit 0
