#!/usr/bin/env bash
# SessionStart：注入路由规则；配置了知识库、个人笔记库、文档站时，再追加对应的规则。
# 没配置（或没有 python3）时只输出 ROUTER.md，不多占上下文。

root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cat "$root/router/ROUTER.md"

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
