"""markdown_lite：把笔记用到的那部分 Markdown 渲染成 HTML，只用标准库。

覆盖范围按「个人笔记里真实会出现的语法」划定：标题、段落、强调、行内代码、围栏代码块、
引用、有序无序列表（含嵌套和任务项）、GFM 表格、分割线、链接、图片，以及 Obsidian 的
`[[双链]]` 和 `![[嵌入]]`。

安全边界（这些页面会发到公开站点）：
- 原始 HTML 一律转义，不做标签白名单，笔记里的 <script> 只会按文本显示；
- 链接协议只放行 http、https、mailto 和相对路径，`javascript:`、`data:` 会被丢弃；
- `[[双链]]` 交给调用方的 wikilink 钩子决定怎么渲染。钩子返回 None 时，整个链接（包括别名）
  替换成「（未公开）」——别名同样可能是未公开笔记的标题，不能留在页面上；
- 本地图片不可能被内容检查，一律不输出，只留「（图片未公开）」。

用法：
    out = markdown_lite.render(body, shift=1, wikilink=hook)
    out.html        渲染结果
    out.headings    [(层级, 纯文本, 锚点 id)]，给目录用

wikilink 钩子：hook(target, section, alias, embed) -> HTML 字符串或 None。
"""
import html as _html
import re
from typing import NamedTuple


class Rendered(NamedTuple):
    html: str
    headings: list


FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*([^`\s]*)")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
HR = re.compile(r"^\s{0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$")
BULLET = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
TABLE_SEP = re.compile(r"^\s*\|?(?:\s*:?-+:?\s*\|)+\s*:?-*:?\s*\|?\s*$")
TASK = re.compile(r"^\[([ xX])\]\s+(.*)$")
ID_DROP = re.compile(r"[^\w一-鿿-]+")
SAFE_SCHEME = re.compile(r"^(?:https?:|mailto:)", re.I)
BAD_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")

INLINE = re.compile(
    r"(?P<esc>\\[\\`*_\[\]()#+\-.!~|>{}])"
    r"|(?P<fence>`+)(?P<code>[\s\S]+?)(?P=fence)"
    r"|(?P<embed>!\[\[(?P<embedtarget>[^\]\n]+)\]\])"
    r"|(?P<wiki>\[\[(?P<wikitarget>[^\]\n]+)\]\])"
    r"|!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]*)(?:\s+\"[^\"]*\")?\)"
    r"|\[(?P<ltext>[^\]]*)\]\((?P<href>[^)\s]*)(?:\s+\"[^\"]*\")?\)"
    r"|<(?P<auto>https?://[^>\s]+)>"
    r"|\*\*(?P<strong>\S(?:[\s\S]*?\S)?)\*\*"
    r"|__(?P<strong2>\S(?:[\s\S]*?\S)?)__"
    r"|~~(?P<del>\S(?:[\s\S]*?\S)?)~~"
    r"|\*(?P<em>[^*\n]+)\*"
    r"|(?<![A-Za-z0-9_])_(?P<em2>[^_\n]+)_(?![A-Za-z0-9_])"
    r"|(?P<bare>https?://[^\s<>\"'，。；、）】]+)"
)

PRIVATE = '<span class="kb-private">（未公开）</span>'


def esc(s):
    return _html.escape(s, quote=True)


def safe_href(href):
    """只放行 http/https/mailto、锚点和相对路径；其余（javascript:、data: 等）返回 None。"""
    href = href.strip()
    if not href:
        return None
    if SAFE_SCHEME.match(href):
        return href
    if BAD_SCHEME.match(href):
        return None
    return href


def anchor_id(text, used):
    base = ID_DROP.sub("-", text.strip().replace(" ", "-")).strip("-") or "节"
    ident, n = base, 1
    while ident in used:
        n += 1
        ident = f"{base}-{n}"
    used.add(ident)
    return ident


def strip_tags(markup):
    """从渲染好的 HTML 里取纯文本。渲染阶段已经去掉了不能公开的内容，用它做检索文本最安全。"""
    text = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", markup, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def plain_text(md):
    """粗略地把 Markdown 转成纯文本，只用来做锚点之类的内部处理。

    注意：它保留普通 Markdown 链接的文字，而链接文字可能是未公开笔记的标题。要公开出去的
    文本（标题锚点、目录、摘要、检索索引）一律用 strip_tags() 从渲染结果里取，不要用这个函数。
    """
    text = re.sub(r"```[\s\S]*?```", " ", md)
    text = re.sub(r"!?\[\[[^\]\n]*\]\]", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.M)
    text = re.sub(r"^\s*([-*+]|\d{1,9}[.)])\s+", "", text, flags=re.M)
    text = re.sub(r"[`*_~|]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


class _Renderer:
    def __init__(self, shift=0, wikilink=None):
        self.shift = shift
        self.wikilink = wikilink
        self.headings = []
        self.ids = set()

    # ---------- 块 ----------

    def blocks(self, lines):
        out, i, n = [], 0, len(lines)
        while i < n:
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            m = FENCE.match(line)
            if m:
                i, block = self.code_block(lines, i, m)
                out.append(block)
                continue
            if HR.match(line):
                out.append("<hr>")
                i += 1
                continue
            m = HEADING.match(line)
            if m:
                out.append(self.heading(m))
                i += 1
                continue
            if QUOTE.match(line):
                i, block = self.quote(lines, i)
                out.append(block)
                continue
            if "|" in line and i + 1 < n and TABLE_SEP.match(lines[i + 1]):
                i, block = self.table(lines, i)
                out.append(block)
                continue
            if BULLET.match(line):
                i, block = self.list_block(lines, i)
                out.append(block)
                continue
            i, block = self.paragraph(lines, i)
            out.append(block)
        return "\n".join(x for x in out if x)

    def code_block(self, lines, i, m):
        mark, lang = m.group(1), m.group(2)
        close = re.compile(r"^\s{0,3}" + mark[0] + "{" + str(len(mark)) + r",}\s*$")
        i += 1
        buf = []
        while i < len(lines) and not close.match(lines[i]):
            buf.append(lines[i])
            i += 1
        i += 1  # 跳过结束围栏（没有结束围栏时正好越界）
        cls = f' class="language-{esc(lang)}"' if lang else ""
        return i, f"<pre><code{cls}>{esc(chr(10).join(buf))}</code></pre>"

    def heading(self, m):
        level = min(6, len(m.group(1)) + self.shift)
        raw = m.group(2).strip()
        inner = self.inline(raw)
        # 锚点 id 和目录文字都从渲染结果里取，不从原文取：标题里如果有指向未公开笔记的链接，
        # 渲染时已经换成「（未公开）」，从原文取会把链接文字（往往就是那篇笔记的标题）漏进 id 和目录。
        text = strip_tags(inner)
        ident = anchor_id(text, self.ids)
        self.headings.append((level, text, ident))
        return f'<h{level} id="{esc(ident)}">{inner}</h{level}>'

    def quote(self, lines, i):
        buf = []
        while i < len(lines):
            m = QUOTE.match(lines[i])
            if m:
                buf.append(m.group(1))
                i += 1
                continue
            if lines[i].strip() and not BULLET.match(lines[i]) and not HEADING.match(lines[i]):
                buf.append(lines[i].strip())  # 惰性续行
                i += 1
                continue
            break
        return i, f"<blockquote>{self.blocks(buf)}</blockquote>"

    def table(self, lines, i):
        header = split_row(lines[i])
        aligns = [cell_align(c) for c in split_row(lines[i + 1])]
        i += 2
        rows = []
        while i < len(lines) and lines[i].strip() and "|" in lines[i]:
            rows.append(split_row(lines[i]))
            i += 1

        def cells(values, tag):
            out = []
            for k, v in enumerate(values):
                style = f' style="text-align:{aligns[k]}"' if k < len(aligns) and aligns[k] else ""
                out.append(f"<{tag}{style}>{self.inline(v)}</{tag}>")
            return "".join(out)

        body = "".join(f"<tr>{cells(r, 'td')}</tr>" for r in rows)
        return i, (f"<div class=\"kb-table\"><table><thead><tr>{cells(header, 'th')}</tr></thead>"
                   f"<tbody>{body}</tbody></table></div>")

    def list_block(self, lines, i):
        base = BULLET.match(lines[i])
        indent = len(base.group(1))
        ordered = base.group(2)[0].isdigit()
        items, loose = [], False
        while i < len(lines):
            line = lines[i]
            m = BULLET.match(line)
            if m and len(m.group(1)) <= indent + 1:
                if m.group(2)[0].isdigit() != ordered:
                    break
                items.append([m.group(3)])
                i += 1
                continue
            if not line.strip():
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                nxt = BULLET.match(lines[j]) if j < len(lines) else None
                if items and j < len(lines) and (
                    (nxt and len(nxt.group(1)) <= indent + 1) or lines[j].startswith(" " * (indent + 2))
                ):
                    items[-1].append("")
                    loose = True
                    i = j
                    continue
                break
            if items and line.startswith(" " * (indent + 1)):
                items[-1].append(dedent(line, indent + 2))
                i += 1
                continue
            if items and not (HEADING.match(line) or FENCE.match(line) or HR.match(line) or QUOTE.match(line)):
                items[-1].append(line.strip())  # 惰性续行
                i += 1
                continue
            break
        tag = "ol" if ordered else "ul"
        return i, f"<{tag}>{''.join(self.list_item(x, loose) for x in items)}</{tag}>"

    def list_item(self, item_lines, loose):
        first = item_lines[0] if item_lines else ""
        box = ""
        m = TASK.match(first.strip())
        if m:
            checked = " checked" if m.group(1).lower() == "x" else ""
            box = f'<input type="checkbox" disabled{checked}> '
            item_lines = [m.group(2)] + item_lines[1:]
        body = self.blocks(item_lines)
        if not loose:
            body = re.sub(r"^<p>([\s\S]*?)</p>", r"\1", body, count=1)
        return f'<li class="{"task" if box else ""}">{box}{body}</li>' if box else f"<li>{body}</li>"

    def paragraph(self, lines, i):
        buf = []
        while i < len(lines):
            line = lines[i]
            if not line.strip() or HEADING.match(line) or FENCE.match(line) or HR.match(line) \
                    or QUOTE.match(line) or BULLET.match(line):
                break
            if "|" in line and i + 1 < len(lines) and TABLE_SEP.match(lines[i + 1]):
                break
            buf.append(line.strip())
            i += 1
        text = "<br>".join(self.inline(x) for x in buf)
        return i, (f"<p>{text}</p>" if text else "")

    # ---------- 行内 ----------

    def inline(self, text):
        out, pos = [], 0
        for m in INLINE.finditer(text):
            out.append(esc(text[pos:m.start()]))
            out.append(self.inline_token(m))
            pos = m.end()
        out.append(esc(text[pos:]))
        return "".join(out)

    def inline_token(self, m):
        g = m.group
        if g("esc"):
            return esc(g("esc")[1])
        if g("code") is not None:
            return f"<code>{esc(g('code').strip())}</code>"
        if g("embed"):
            return self.link_target(g("embedtarget"), embed=True)
        if g("wiki"):
            return self.link_target(g("wikitarget"), embed=False)
        if g("src") is not None:
            return self.image(g("alt") or "", g("src"))
        if g("href") is not None:
            return self.link(g("ltext") or "", g("href"))
        if g("auto"):
            return f'<a href="{esc(g("auto"))}" rel="nofollow noopener">{esc(g("auto"))}</a>'
        if g("strong") or g("strong2"):
            return f"<strong>{self.inline(g('strong') or g('strong2'))}</strong>"
        if g("del"):
            return f"<del>{self.inline(g('del'))}</del>"
        if g("em") or g("em2"):
            return f"<em>{self.inline(g('em') or g('em2'))}</em>"
        if g("bare"):
            return f'<a href="{esc(g("bare"))}" rel="nofollow noopener">{esc(g("bare"))}</a>'
        return esc(m.group(0))

    def link_target(self, raw, embed):
        """[[目标#小节|别名]]。钩子说了不算数（返回 None）就整体抹掉，别名也不留。"""
        body, _, alias = raw.partition("|")
        target, _, section = body.partition("#")
        target, section, alias = target.strip(), section.strip(), alias.strip()
        if self.wikilink:
            got = self.wikilink(target, section, alias or None, embed)
            if got:
                return got
            return PRIVATE
        return esc(alias or target)

    def link(self, text, href):
        inner = self.inline(text) if text else esc(href)
        url = safe_href(href)
        if url is None:
            return inner
        if not SAFE_SCHEME.match(url) and not url.startswith(("#", "//")):
            section = url.split("#", 1)[1] if "#" in url else ""
            parts = [x for x in url.split("#")[0].split("/") if x not in ("", ".", "..")]
            stem = re.sub(r"\.md$", "", parts[-1], flags=re.I) if parts else ""
            if self.wikilink:
                # 站内的相对链接一律要问过钩子：问不出来（未公开、或根本没这篇）就不留链接文字
                got = self.wikilink(unquote(stem), section, text or None, False) if stem else None
                return got if got else PRIVATE
            return inner
        external = bool(SAFE_SCHEME.match(url)) or url.startswith("//")  # // 是协议相对的站外链接
        rel = ' rel="nofollow noopener"' if external else ""
        return f'<a href="{esc(url)}"{rel}>{inner}</a>'

    def image(self, alt, src):
        url = safe_href(src)
        if url and SAFE_SCHEME.match(url):
            return f'<img src="{esc(url)}" alt="{esc(alt)}" loading="lazy">'
        label = f"（图片未公开：{alt}）" if alt else "（图片未公开）"
        return f'<span class="kb-private">{esc(label)}</span>'


def unquote(s):
    from urllib.parse import unquote as _unq
    return _unq(s)


def dedent(line, width):
    cut = 0
    while cut < width and cut < len(line) and line[cut] == " ":
        cut += 1
    return line[cut:]


def split_row(line):
    line = line.strip()
    line = re.sub(r"^\|", "", line)
    line = re.sub(r"\|$", "", line)
    cells, buf, esc_next = [], "", False
    for ch in line:
        if esc_next:
            buf += ch
            esc_next = False
        elif ch == "\\":
            esc_next = True
        elif ch == "|":
            cells.append(buf.strip())
            buf = ""
        else:
            buf += ch
    cells.append(buf.strip())
    return cells


def cell_align(sep):
    sep = sep.strip()
    if sep.startswith(":") and sep.endswith(":"):
        return "center"
    if sep.endswith(":"):
        return "right"
    return ""


def render(text, shift=0, wikilink=None):
    r = _Renderer(shift=shift, wikilink=wikilink)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return Rendered(r.blocks(lines), r.headings)
