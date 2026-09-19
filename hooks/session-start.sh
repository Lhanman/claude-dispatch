#!/usr/bin/env bash
# SessionStart：注入路由规则；配置了知识库、文档站时，再追加对应的规则。
# 没配置（或没有 python3）时只输出 ROUTER.md，不多占上下文。

root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cat "$root/router/ROUTER.md"

# render <模板> <占位符> <值>：把模板里的 {{占位符}} 换成值后输出
render() {
  VALUE="$3" python3 -c 'import os,sys; sys.stdout.write(open(sys.argv[1],encoding="utf-8").read().replace("{{"+sys.argv[2]+"}}", os.environ["VALUE"]))' "$1" "$2"
}

if kb="$("$root/bin/dispatch-kb" path 2>/dev/null)" && [ -n "$kb" ]; then
  echo; render "$root/router/KB.md" KB_DIR "$kb"
fi
if url="$("$root/bin/dispatch-pages" url 2>/dev/null)" && [ -n "$url" ]; then
  echo; render "$root/router/PAGES.md" PAGES_URL "$url"
fi
exit 0
