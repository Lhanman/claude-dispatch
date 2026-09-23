"""kbsite：把个人知识库里「白名单内、且通过敏感检查」的笔记，渲染成文档站上的笔记页。

被 `dispatch-pages kb-sync` 调用。公开范围的规则（详见 docs/plans/知识库中心-方案.md）：

1. 只有 `kb_public` 列出的顶层目录参与，没配置就什么都不同步；白名单外没有任何放行办法；
2. 单篇可以用 frontmatter `publish: false` 退出；
3. 笔记原文和渲染后的 HTML 各过一遍敏感检查，命中就整篇跳过，不支持 --allow，不做替换；
4. 指向未公开笔记的 `[[链接]]` 整体替换成「（未公开）」，别名也不保留；
5. 本地图片和附件不上传。

每次都是全量同步：算出应发布集合，写入、更新、删除，再重建 kb.json 和图谱页。
"""
import hashlib
import html as _html
import json
import os
import re
from datetime import date

import markdown_lite

KB_DIR_NAME = "知识库"
BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
TYPES = ("方案", "决策", "踩坑", "指南")


# ---------- 读取笔记 ----------

def parse_front(text):
    """解析 frontmatter。支持 `key: 值`、`key: [a, b]` 和 `key:` 加 `- a` 的块状列表。"""
    meta = {}
    m = re.match(r"[\ufeff\s]*---[ \t]*\n([\s\S]*?)\n---[ \t]*\n?", text)
    if not m:
        return meta, text
    key = None
    for line in m.group(1).split("\n"):
        item = re.match(r"\s*-\s+(.*)$", line)
        if item and key:
            meta.setdefault(key, [])
            if isinstance(meta[key], list):
                meta[key].append(unquote_scalar(item.group(1)))
            continue
        kv = re.match(r"([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if not kv:
            continue
        key, raw = kv.group(1).lower(), kv.group(2).strip()
        if raw.startswith("[") and raw.endswith("]"):
            meta[key] = [unquote_scalar(x) for x in raw[1:-1].split(",") if x.strip()]
        elif raw == "":
            meta[key] = []
        else:
            meta[key] = unquote_scalar(raw)
    return meta, text[m.end():]


def unquote_scalar(s):
    return s.strip().strip("\"'").strip()


def as_list(value):
    if isinstance(value, list):
        return [str(x).strip().lstrip("#") for x in value if str(x).strip()]
    if not value:
        return []
    return [x.strip().lstrip("#") for x in re.split(r"[,，;；]|\s{2,}", str(value)) if x.strip()]


def is_off(value):
    return str(value).strip().lower() in ("false", "no", "off", "0", "不公开", "私密")


def first_paragraph(markup):
    """没有 frontmatter summary 的老笔记，用正文第一段兜底。

    只从渲染后的 HTML 里取：原文里指向未公开笔记的链接，渲染时已经换成「（未公开）」，
    从原文取会把链接文字（往往就是那篇笔记的标题）带进摘要、meta 描述和首页检索索引。
    """
    m = re.search(r"<(?:p|li)>([\s\S]*?)</(?:p|li)>", markup)
    text = markdown_lite.strip_tags(m.group(1)) if m else ""
    return text[:80] + "…" if len(text) > 80 else text


def body_hash(body):
    return hashlib.sha1(re.sub(r"\s+", " ", body).strip().encode("utf-8")).hexdigest()


class Note:
    def __init__(self, kb_root, src):
        self.src = src                                   # 相对知识库根目录的路径
        self.path_no_ext = os.path.splitext(src)[0]
        raw = open(os.path.join(kb_root, src), encoding="utf-8-sig", errors="replace").read()
        self.raw = raw
        self.meta, body = parse_front(raw)
        parts = src.split(os.sep)
        self.top = parts[0]
        stem = os.path.splitext(parts[-1])[0]
        title = self.meta.get("title") or heading_title(body) or stem
        self.title = str(title).strip()
        body = strip_leading_title(body, self.title)
        self.body = body
        self.stem = stem
        self.meta_summary = str(self.meta.get("summary") or "").strip()
        self.summary = self.meta_summary  # 没写 summary 的，每次渲染后用正文第一段兜底
        self.type = str(self.meta.get("type") or "").strip()
        self.project = str(self.meta.get("project") or (parts[1] if len(parts) > 2 else self.top)).strip()
        self.tags = as_list(self.meta.get("tags"))
        self.created = str(self.meta.get("created") or "")[:10]
        self.updated = str(self.meta.get("updated") or self.created or "")[:10]
        if not self.updated:
            self.updated = date.fromtimestamp(os.path.getmtime(os.path.join(kb_root, src))).isoformat()
        self.created = self.created or self.updated
        self.hash = body_hash(body)
        self.slug = ""
        self._repo_path = ""
        self.html = ""
        self.headings = []
        self.links = []
        self.text = ""

    @property
    def repo_path(self):
        return self._repo_path or self.base_repo_path()

    def base_repo_path(self):
        parts = [safe_name(p) for p in self.path_no_ext.split(os.sep)]
        return "/".join([KB_DIR_NAME] + parts) + ".html"

    @property
    def url(self):
        return f"kb/{self.slug}/"

    def entry(self):
        return {"slug": self.slug, "title": self.title, "summary": self.summary, "type": self.type,
                "project": self.project, "tags": self.tags, "created": self.created, "updated": self.updated,
                "path": self.repo_path, "src": self.src, "hash": self.hash, "links": self.links,
                "text": self.text[:600]}


def heading_title(body):
    m = re.search(r"^\s{0,3}#\s+(.+?)\s*$", body, re.M)
    return m.group(1).strip() if m else ""


def strip_leading_title(body, title):
    """正文开头那个和标题重复的一级标题去掉：页面上已经有 <h1> 了。"""
    m = re.match(r"\s*#\s+(.+?)\s*\n", body)
    if m and m.group(1).strip() == title:
        return body[m.end():]
    return body


def safe_name(s):
    s = re.sub(r"\s+", " ", BAD_CHARS.sub("-", s)).strip().strip(".")
    return s[:80] or "未命名"


def collect(kb_root, public_dirs, exclude):
    """按白名单收集候选笔记。白名单外的目录根本不会被遍历。"""
    notes, skipped = [], []
    for top in public_dirs:
        if top in exclude:
            skipped.append((top, "在 kb_exclude 里"))
            continue
        base = os.path.join(kb_root, top)
        if not os.path.isdir(base):
            skipped.append((top, "目录不存在"))
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                if not name.endswith(".md") or name == ".md" or name.startswith("."):
                    continue
                full = os.path.join(dirpath, name)
                if os.path.getsize(full) == 0:
                    continue
                notes.append(Note(kb_root, os.path.relpath(full, kb_root)))
    return notes, skipped


# ---------- slug ----------

def ascii_slug(s):
    out = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return out if len(out) >= 4 and re.search(r"[a-z]", out) else ""


def assign_slugs(notes, old_entries):
    """slug 顺序：frontmatter → 上次同一路径用过的 → 内容相同的旧条目（改名保号）→ 标题英文 → 哈希。"""
    by_src = {e["src"]: e["slug"] for e in old_entries if e.get("src")}
    gone = {e["hash"]: e["slug"] for e in old_entries
            if e.get("hash") and e.get("src") not in {n.src for n in notes}}
    def want_of(n):
        return (ascii_slug(str(n.meta.get("slug") or "")), by_src.get(n.src), gone.get(n.hash),
                ascii_slug(n.title), f"note-{n.hash[:6]}")

    def rank(n):
        """写了 slug 的最优先，其次是已经有线上网址的（按路径、按内容认回），最后才是新笔记。
        否则新笔记会抢走老笔记已经公开出去的网址。"""
        explicit, from_src, from_hash, _, _ = want_of(n)
        return (0 if explicit else 1 if from_src else 2 if from_hash else 3, n.src)

    used = {}
    for n in sorted(notes, key=rank):
        explicit, from_src, from_hash, from_title, fallback = want_of(n)
        want = explicit or from_src or from_hash or from_title or fallback
        slug, k = want, 1
        while slug in used:
            k += 1
            slug = f"{want}-{k}"
        used[slug] = n
        n.slug = slug
    return notes


def assign_paths(notes):
    """仓库里的存放路径。safe_name 会把 : * ? 等字符归一、超长截断，不同笔记可能撞到同一个
    路径；撞上就在文件名后加 slug 区分，否则后写的会覆盖先写的，线上两个网址显示同一篇。"""
    used = {}
    for n in sorted(notes, key=lambda x: x.src):
        base = n.base_repo_path()
        path = base
        if path in used:
            path = f"{base[:-5]}（{n.slug}）.html"
        n._repo_path = path
        used[path] = n
    return notes


# ---------- 渲染 ----------

def build_lookup(notes):
    table = {}
    for n in notes:
        for key in (n.stem, n.title, n.path_no_ext, n.path_no_ext.replace(os.sep, "/")):
            table.setdefault(key.lower(), n)
    return table


def render_note(note, lookup, published_slugs):
    """渲染正文，并记下指向其他公开笔记的边。未公开的目标交给 markdown_lite 换成「（未公开）」。"""
    links = []

    def hook(target, section, alias, embed):
        key = target.strip().lower()
        if embed and re.search(r"\.(png|jpe?g|gif|webp|svg|bmp|pdf|mp4|mov|m4a|mp3)$", key):
            label = f"（图片未公开：{alias}）" if alias else "（图片未公开）"
            return f'<span class="kb-private">{_html.escape(label, quote=True)}</span>'  # 附件一律不上传
        hit = lookup.get(key) or lookup.get(re.sub(r"\.md$", "", key))
        if not hit or hit.slug not in published_slugs or hit.slug == note.slug:
            return None
        links.append(hit.slug)
        anchor = f"#{markdown_lite.anchor_id(section, set())}" if section else ""
        text = alias or hit.title
        mark = "内嵌 " if embed else ""
        return (f'<a class="kb-link" href="../{_html.escape(hit.slug, quote=True)}/{anchor}">'
                f'{mark}{_html.escape(text, quote=True)}</a>')

    # 页面上只允许有一个 <h1>（笔记标题）。正文里还留着一级标题时整体降一级，
    # 否则保持原样，免得 ## 变成 h3、页面从 h1 直接跳到 h3。
    shift = 1 if re.search(r"^\s{0,3}#\s+", note.body, re.M) else 0
    out = markdown_lite.render(note.body, shift=shift, wikilink=hook)
    note.html = out.html
    note.headings = out.headings
    # 每轮都重算：某篇笔记被第二遍检查拦下后要重渲染，旧摘要里可能还留着它的标题
    note.summary = note.meta_summary or first_paragraph(out.html)
    note.links = sorted(set(links))
    note.text = " ".join([note.title, note.summary, " ".join(note.tags), note.project, note.type,
                          " ".join(h[1] for h in out.headings),
                          markdown_lite.strip_tags(out.html)])
    return note


# ---------- 图谱 ----------

def graph_data(notes):
    """节点：笔记 + 被 2 篇以上笔记共用的标签 + 有 2 篇以上笔记的项目。

    共同标签和同一项目都通过中间节点连接，不做笔记两两连线：边数随笔记数线性增长，
    笔记多了图也还看得清。没有 frontmatter 的老笔记没有标签，靠项目节点入网。
    """
    slugs = {n.slug for n in notes}
    tag_count, project_count = {}, {}
    for n in notes:
        for t in set(n.tags):
            tag_count[t] = tag_count.get(t, 0) + 1
        if n.project:
            project_count[n.project] = project_count.get(n.project, 0) + 1
    shared = {t for t, c in tag_count.items() if c >= 2}
    projects = {p for p, c in project_count.items() if c >= 2}
    nodes = [{"id": n.slug, "kind": "note", "title": n.title, "project": n.project,
              "type": n.type, "url": f"../kb/{n.slug}/", "tags": [t for t in n.tags if t in shared]}
             for n in notes]
    nodes += [{"id": f"tag:{t}", "kind": "tag", "title": t} for t in sorted(shared)]
    nodes += [{"id": f"project:{p}", "kind": "project", "title": p, "project": p} for p in sorted(projects)]
    edges = []
    for n in notes:
        for target in n.links:
            if target in slugs:
                edges.append({"source": n.slug, "target": target, "kind": "link"})
        for t in sorted(set(n.tags) & shared):
            edges.append({"source": n.slug, "target": f"tag:{t}", "kind": "tag"})
        if n.project in projects:
            edges.append({"source": n.slug, "target": f"project:{n.project}", "kind": "project"})
    return {"nodes": nodes, "edges": edges}


def backlinks(notes):
    table = {n.slug: [] for n in notes}
    for n in notes:
        for target in n.links:
            if target in table and n.slug not in [x["slug"] for x in table[target]]:
                table[target].append({"slug": n.slug, "title": n.title})
    return table


def related(note, notes, limit=4):
    """按共同标签推荐；已经有直接链接的不再重复推荐。"""
    mine, linked = set(note.tags), set(note.links)
    hits = []
    for other in notes:
        if other.slug == note.slug or other.slug in linked:
            continue
        shared = mine & set(other.tags)
        if shared:
            hits.append((len(shared), other.updated, other))
    hits.sort(key=lambda x: (-x[0], x[1]), reverse=False)
    hits.sort(key=lambda x: -x[0])
    return [h[2] for h in hits[:limit]]


# ---------- 页面 ----------

TOKENS = """
:root{--ground:#F3F4F6;--paper:#FFFFFF;--ink:#161A21;--muted:#5B6372;--rule:#DADDE3;--chip:#E4E8F2;--chip-ink:#2E4893;--accent:#4865AA;--mark:#FDF2C7;
--serif:"Noto Serif SC","Songti SC",serif;--sans:"Noto Sans SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,sans-serif;--mono:"JetBrains Mono","SF Mono",Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--ground:#12151B;--paper:#1A1E26;--ink:#E5E8EE;--muted:#9AA2B1;--rule:#2C323D;--chip:#222B3D;--chip-ink:#AFC1EA;--accent:#95ABDB;--mark:#4A421F}}
*{box-sizing:border-box}
html{color-scheme:light dark}
body{margin:0;background:var(--ground);color:var(--ink);font:15.5px/1.75 var(--sans);padding-inline:20px;padding-block:0 80px}
a{color:var(--accent)}
.eyebrow{font:600 11.5px/1 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.chip{font:500 12px/1 var(--mono);padding:4px 8px;border-radius:3px;background:var(--chip);color:var(--chip-ink)}
.kb-private{color:var(--muted);font-style:normal;opacity:.75}
"""

NOTE_CSS = """
main{max-width:820px;margin:0 auto}
.crumb{padding-block:28px 0;font:500 12.5px/1.6 var(--mono);color:var(--muted)}
.crumb a{color:var(--muted);text-decoration:none}
.crumb a:hover{color:var(--accent)}
header.note{padding-block:14px 22px;border-bottom:1px solid var(--rule)}
header.note h1{font:900 clamp(26px,4.4vw,38px)/1.25 var(--serif);margin:6px 0 10px;text-wrap:balance}
header.note .summary{margin:0 0 14px;color:var(--muted)}
.meta{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;font:500 12px/1.4 var(--mono);color:var(--muted)}
.toc{margin:22px 0 0;padding:14px 16px;background:var(--paper);border:1px solid var(--rule);border-radius:8px}
.toc p{margin:0 0 8px;font:600 11.5px/1 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.toc ol{list-style:none;margin:0;padding:0;display:grid;gap:4px}
.toc li.l3{padding-left:16px;font-size:14px}
.toc a{color:var(--ink);text-decoration:none}
.toc a:hover{color:var(--accent)}
article{padding-block:8px 24px}
article h2{font:800 22px/1.4 var(--serif);margin:32px 0 10px;padding-top:6px;border-top:1px solid var(--rule)}
article h3{font:700 17.5px/1.5 var(--sans);margin:22px 0 8px}
article h4{font:700 15.5px/1.5 var(--sans);margin:18px 0 6px;color:var(--muted)}
article p{margin:10px 0}
article ul,article ol{margin:10px 0;padding-left:22px}
article li{margin:4px 0}
article li.task{list-style:none;margin-left:-18px}
article blockquote{margin:14px 0;padding:2px 14px;border-left:3px solid var(--rule);color:var(--muted)}
article code{font:13.5px/1.6 var(--mono);background:var(--chip);color:var(--chip-ink);padding:1px 5px;border-radius:3px}
article pre{margin:14px 0;padding:14px 16px;background:var(--paper);border:1px solid var(--rule);border-radius:8px;overflow:auto}
article pre code{background:none;color:var(--ink);padding:0;font-size:13px;line-height:1.7}
article hr{border:0;border-top:1px solid var(--rule);margin:26px 0}
article img{max-width:100%;border-radius:6px}
.kb-table{overflow-x:auto;margin:14px 0}
article table{border-collapse:collapse;width:100%;font-size:14.5px;background:var(--paper)}
article th,article td{border:1px solid var(--rule);padding:7px 10px;text-align:left;vertical-align:top}
article th{background:var(--chip);color:var(--chip-ink);font-weight:600;white-space:nowrap}
footer.note{border-top:1px solid var(--rule);padding-top:20px;display:grid;gap:18px}
footer.note section{display:grid;gap:6px}
footer.note h2{font:600 11.5px/1 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:0}
footer.note ul{list-style:none;margin:0;padding:0;display:grid;gap:4px}
footer.note a{text-decoration:none}
footer.note a:hover{text-decoration:underline}
.back{display:flex;flex-wrap:wrap;gap:14px;font:500 13px/1.6 var(--mono)}
.stamp{color:var(--muted);font-size:12.5px;margin:0}
@media (max-width:640px){article th{white-space:normal}}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=Noto+Serif+SC:wght@700;800;900&family=Noto+Sans+SC:wght@400;500;700&'
         'family=JetBrains+Mono:wght@500;600&display=swap">')


def e(s):
    return _html.escape(str(s), quote=True)


def json_for_script(data):
    """内联进 <script> 的 JSON：转义 < > &，标题里带 </script> 也闭合不了脚本块。"""
    return (json.dumps(data, ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def note_page(note, site_title, links_in, related_notes):
    toc = ""
    heads = [h for h in note.headings if h[0] in (2, 3)]
    if len(heads) >= 3:
        items = "".join(f'<li class="l{h[0]}"><a href="#{e(h[2])}">{e(h[1])}</a></li>' for h in heads)
        toc = f'<nav class="toc"><p>本篇目录</p><ol>{items}</ol></nav>'
    meta = []
    if note.type:
        meta.append(f'<span class="chip">{e(note.type)}</span>')
    if note.project:
        meta.append(f"<span>{e(note.project)}</span>")
    meta.append(f"<span>更新于 {e(note.updated)}</span>")
    meta += [f'<span class="chip">{e(t)}</span>' for t in note.tags]
    foot = []
    if links_in:
        items = "".join(f'<li><a href="../{e(x["slug"])}/">{e(x["title"])}</a></li>' for x in links_in)
        foot.append(f"<section><h2>被引用</h2><ul>{items}</ul></section>")
    if related_notes:
        items = "".join(f'<li><a href="../{e(x.slug)}/">{e(x.title)}</a>'
                        f'<span class="stamp"> · {e("、".join(x.tags[:3]))}</span></li>' for x in related_notes)
        foot.append(f"<section><h2>相关笔记</h2><ul>{items}</ul></section>")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{e(note.title)} · {e(site_title)}</title>
<meta name="description" content="{e(note.summary)}">
<link rel="index" href="../../index.html">
{FONTS}
<style>{TOKENS}{NOTE_CSS}</style>
</head>
<body>
<main>
<nav class="crumb"><a href="../../index.html">{e(site_title)}</a> / <span>{e(note.project or "笔记")}</span></nav>
<header class="note">
<span class="eyebrow">知识库笔记</span>
<h1>{e(note.title)}</h1>
{f'<p class="summary">{e(note.summary)}</p>' if note.summary else ""}
<div class="meta">{"".join(meta)}</div>
</header>
{toc}
<article>
{note.html}
</article>
<footer class="note">
{"".join(foot)}
<div class="back"><a href="../../index.html">← 全部文档和笔记</a><a href="../../graph/">知识图谱</a></div>
<p class="stamp">这篇笔记由 dispatch 从个人知识库同步，更新于 {e(note.updated)}。</p>
</footer>
</main>
</body>
</html>
"""


GRAPH_CSS = """
main{max-width:1080px;margin:0 auto}
header.graph{padding-block:40px 18px}
header.graph h1{font:900 clamp(26px,4.4vw,38px)/1.2 var(--serif);margin:10px 0 8px}
header.graph p{margin:0;color:var(--muted)}
.bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:18px 0 10px}
#q{flex:1 1 220px;font:15px var(--sans);padding:9px 12px;border:1px solid var(--rule);border-radius:6px;background:var(--paper);color:var(--ink)}
.bar label{font:500 12.5px/1 var(--mono);color:var(--muted);display:flex;gap:6px;align-items:center}
.fit{font:500 12.5px/1 var(--mono);padding:8px 12px;border:1px solid var(--rule);border-radius:6px;background:var(--paper);color:var(--muted);cursor:pointer}
.fit:hover{color:var(--accent);border-color:var(--accent)}
#stage{position:relative;height:min(68vh,620px);background:var(--paper);border:1px solid var(--rule);border-radius:10px;overflow:hidden}
#stage svg{width:100%;height:100%;display:block;touch-action:none}
.node circle,.node rect{stroke:var(--paper);stroke-width:1.5}
.node text{font:12px var(--sans);fill:var(--ink);pointer-events:none}
.node.tag text{fill:var(--muted);font-family:var(--mono);font-size:11px}
.node.project text{font-weight:700}
.node{cursor:pointer}
.edge{stroke:var(--rule)}
.edge.tag{stroke-dasharray:3 3}
.edge.project{stroke-dasharray:1 4}
.dim{opacity:.12}
.legend{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0 0;font:500 12px/1.4 var(--mono);color:var(--muted)}
.legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:baseline}
.fallback{margin-top:26px}
.fallback h2{font:700 16px/1.5 var(--sans);margin:18px 0 6px}
.fallback ul{margin:0;padding-left:20px}
.back{margin-top:26px;font:500 13px/1.6 var(--mono)}
"""

GRAPH_JS = """
const DATA=JSON.parse(document.getElementById('graph-data').textContent);
const stage=document.getElementById('stage'),fallback=document.getElementById('fallback');
if(!window.d3||!DATA.nodes.length){stage.hidden=true;document.getElementById('bar').hidden=true;}
else{
fallback.hidden=true;
const palette=['#4865AA','#2E8B7A','#A8603D','#7A4FA3','#3E7CB1','#8A6D1F','#B0526B','#4F7A28'];
const projects=[...new Set(DATA.nodes.filter(n=>n.kind==='note').map(n=>n.project||'其他'))];
const color=p=>palette[projects.indexOf(p||'其他')%palette.length];
const legend=document.getElementById('legend');
for(const [name,c] of [...projects.map(p=>[p,color(p)]),['标签','#9AA2B1']]){
  const s=document.createElement('span'),i=document.createElement('i');i.style.background=c;
  s.append(i,document.createTextNode(name));legend.append(s);}
const nodes=DATA.nodes.map(n=>({...n})),index=new Map(nodes.map(n=>[n.id,n]));
const links=DATA.edges.filter(e=>index.has(e.source)&&index.has(e.target)).map(e=>({...e}));
const degree=new Map();for(const l of links){degree.set(l.source,(degree.get(l.source)||0)+1);degree.set(l.target,(degree.get(l.target)||0)+1);}
const radius=n=>n.kind==='tag'?4.5:n.kind==='project'?8:5+Math.min(7,(degree.get(n.id)||0)*1.4);
const label=d=>{const t=d.kind==='tag'?'#'+d.title:d.title;return t.length>13?t.slice(0,12)+'…':t};
const svg=d3.select('#stage').append('svg'),root=svg.append('g');
const box=()=>[stage.clientWidth,stage.clientHeight];
const [w0,h0]=box();
const edge=root.append('g').selectAll('line').data(links).join('line').attr('class',d=>'edge '+d.kind).attr('stroke-width',d=>d.kind==='link'?1.6:1);
const node=root.append('g').selectAll('g').data(nodes).join('g').attr('class',d=>'node '+d.kind);
node.each(function(d){const g=d3.select(this);
  if(d.kind==='tag'){g.append('rect').attr('width',9).attr('height',9).attr('x',-4.5).attr('y',-4.5).attr('transform','rotate(45)').attr('fill','#9AA2B1');}
  else if(d.kind==='project'){g.append('rect').attr('width',15).attr('height',15).attr('x',-7.5).attr('y',-7.5).attr('rx',3).attr('fill',color(d.project));}
  else{g.append('circle').attr('r',radius(d)).attr('fill',color(d.project));}
  g.append('text').attr('x',radius(d)+5).attr('dy','0.34em').text(label(d));});
node.append('title').text(d=>d.kind==='tag'?`标签：${d.title}`:d.kind==='project'?`项目：${d.title}`:`${d.title}${d.type?' · '+d.type:''}`);
node.on('click',(ev,d)=>{if(d.kind==='note'){location.href=d.url;}else{highlight(d.id);}});
const sim=d3.forceSimulation(nodes)
  .force('link',d3.forceLink(links).id(d=>d.id).distance(d=>d.kind==='link'?95:d.kind==='project'?110:70).strength(d=>d.kind==='link'?0.7:0.35))
  .force('charge',d3.forceManyBody().strength(-420))
  .force('center',d3.forceCenter(w0/2,h0/2))
  .force('collide',d3.forceCollide().radius(d=>radius(d)+14+label(d).length*4.5))
  .on('tick',()=>{edge.attr('x1',d=>d.source.x).attr('y1',d=>d.source.y).attr('x2',d=>d.target.x).attr('y2',d=>d.target.y);
    node.attr('transform',d=>`translate(${d.x},${d.y})`);});
const zoom=d3.zoom().scaleExtent([0.2,3]).on('zoom',ev=>{root.attr('transform',ev.transform);
  node.selectAll('text').attr('display',ev.transform.k<0.6&&nodes.length>40?'none':null);});
svg.call(zoom);
function fit(){if(!nodes.length)return;const [w,h]=box();
  const minX=Math.min(...nodes.map(n=>n.x))-30,maxX=Math.max(...nodes.map(n=>n.x))+150;
  const minY=Math.min(...nodes.map(n=>n.y))-30,maxY=Math.max(...nodes.map(n=>n.y))+30;
  const k=Math.max(0.2,Math.min(1.6,0.92*Math.min(w/(maxX-minX),h/(maxY-minY))));
  svg.transition().duration(500).call(zoom.transform,
    d3.zoomIdentity.translate((w-k*(minX+maxX))/2,(h-k*(minY+maxY))/2).scale(k));}
sim.on('end',fit);
node.call(d3.drag().on('start',(ev,d)=>{if(!ev.active)sim.alphaTarget(0.25).restart();d.fx=d.x;d.fy=d.y;})
  .on('drag',(ev,d)=>{d.fx=ev.x;d.fy=ev.y;}).on('end',(ev,d)=>{if(!ev.active)sim.alphaTarget(0);d.fx=null;d.fy=null;}));
function neighbours(id){const keep=new Set([id]);for(const l of links){const s=l.source.id||l.source,t=l.target.id||l.target;
  if(s===id)keep.add(t);if(t===id)keep.add(s);}return keep;}
function highlight(id){const keep=id?neighbours(id):null;
  node.classed('dim',d=>keep?!keep.has(d.id):false);
  edge.classed('dim',d=>{const s=d.source.id||d.source,t=d.target.id||d.target;return keep?!(keep.has(s)&&keep.has(t)):false;});}
const q=document.getElementById('q');
q.addEventListener('input',()=>{const s=q.value.trim().toLowerCase();
  if(!s){highlight(null);return;}
  const hit=new Set(nodes.filter(n=>(n.title+' '+(n.tags||[]).join(' ')+' '+(n.project||'')).toLowerCase().includes(s)).map(n=>n.id));
  node.classed('dim',d=>!hit.has(d.id));edge.classed('dim',()=>true);});
for(const kind of ['tag','project'])document.getElementById(kind+'s').addEventListener('change',ev=>{const on=ev.target.checked;
  edge.filter(d=>d.kind===kind).attr('display',on?null:'none');
  node.filter(d=>d.kind===kind).attr('display',on?null:'none');});
svg.on('click',ev=>{if(ev.target.tagName==='svg'){highlight(null);q.value='';}});
addEventListener('resize',()=>{const [w,h]=box();sim.force('center',d3.forceCenter(w/2,h/2)).alpha(0.2).restart();});
document.getElementById('fit').addEventListener('click',fit);
}
"""


def graph_page(notes, data, site_title):
    def group_blocks(groups, prefix):
        out = []
        for key in sorted(groups, key=lambda x: (-len(groups[x]), x)):
            if len(groups[key]) < 2:
                continue
            items = "".join(f'<li><a href="../kb/{e(n.slug)}/">{e(n.title)}</a></li>' for n in groups[key])
            out.append(f"<h2>{prefix}{e(key)}</h2><ul>{items}</ul>")
        return out

    by_project, by_tag = {}, {}
    for n in notes:
        if n.project:
            by_project.setdefault(n.project, []).append(n)
        for t in n.tags:
            by_tag.setdefault(t, []).append(n)
    blocks = group_blocks(by_project, "") + group_blocks(by_tag, "#")
    if not blocks:
        blocks.append("<p>还没有可以连成关系的项目或标签。</p>")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>知识图谱 · {e(site_title)}</title>
<meta name="description" content="{len(notes)} 篇公开笔记之间的链接和共同标签">
<link rel="index" href="../index.html">
{FONTS}
<style>{TOKENS}{GRAPH_CSS}</style>
</head>
<body>
<main>
<header class="graph">
<span class="eyebrow">知识图谱 · {len(notes)} 篇笔记</span>
<h1>笔记之间的关系</h1>
<p>实线是笔记之间的链接，虚线连到共同的标签和所属项目。点笔记进入正文，点标签或项目只看它的邻居。</p>
</header>
<div class="bar" id="bar">
<input id="q" type="search" placeholder="高亮标题、标签或项目" aria-label="在图谱里搜索">
<label><input type="checkbox" id="tags" checked> 标签节点</label>
<label><input type="checkbox" id="projects" checked> 项目节点</label>
<button type="button" id="fit" class="fit">重新排布</button>
</div>
<div id="stage"></div>
<div class="legend" id="legend"></div>
<div class="fallback" id="fallback">
<p>图谱需要 JavaScript。下面按共同标签列出同样的关系：</p>
{"".join(blocks)}
</div>
<p class="back"><a href="../index.html">← 全部文档和笔记</a></p>
</main>
<script id="graph-data" type="application/json">{json_for_script(data)}</script>
<script src="https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js" crossorigin="anonymous"></script>
<script>{GRAPH_JS}</script>
</body>
</html>
"""


# ---------- 同步 ----------

GRAPH_FILE = "知识图谱.html"
KB_JSON = "kb.json"


def load_kb(repo):
    p = os.path.join(repo, KB_JSON)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f).get("notes", [])
        except (OSError, ValueError):
            return []
    return []


class Result:
    def __init__(self):
        self.published = []
        self.blocked = []     # (src, 原因, 命中详情)
        self.opted_out = []
        self.warnings = []    # (src, 提醒)
        self.added = []
        self.updated = []
        self.removed = []
        self.no_images = []


def sync(kb_root, repo, cfg, scan, dry_run=False):
    """全量同步。scan(text, allow) -> (blocks, warns)，由 dispatch-pages 提供。"""
    public_dirs = [x.strip().strip("/") for x in (cfg.get("kb_public") or "").split(",") if x.strip()]
    exclude = {x.strip().strip("/") for x in (cfg.get("kb_exclude") or "").split(",") if x.strip()}
    site_title = cfg.get("pages_title", "文档")
    result = Result()
    notes, _ = collect(kb_root, public_dirs, exclude)

    keep = []
    for n in notes:
        if is_off(n.meta.get("publish", "")) or is_off(n.meta.get("public", "")):
            result.opted_out.append(n.src)
            continue
        blocks, warns = scan("\n".join([n.src, n.title, n.raw]), [])
        if blocks:
            result.blocked.append((n.src, "原文命中", blocks[:3]))
            continue
        if warns:
            result.warnings.append((n.src, warns[:3]))
        keep.append(n)

    assign_slugs(keep, load_kb(repo))
    lookup = build_lookup(keep)
    while True:  # 渲染后再查一次；被查出来的踢掉后全部重渲染，直到没有新的命中为止
        slugs = {n.slug for n in keep}
        for n in keep:
            render_note(n, lookup, slugs)
        bad = []
        for n in keep:
            blocks, _ = scan(n.html, [])
            if blocks:
                bad.append(n)
                result.blocked.append((n.src, "渲染后命中", blocks[:3]))
        if not bad:
            break
        keep = [n for n in keep if n not in bad]  # 每轮至少去掉一篇，一定会停
    result.no_images = [n.src for n in keep if "图片未公开" in n.html]

    keep.sort(key=lambda n: (n.updated, n.slug), reverse=True)
    assign_paths(keep)
    result.published = keep
    if dry_run:
        return result

    old = {e_["src"]: e_ for e_ in load_kb(repo)}
    wanted = {}
    for n in keep:
        page = note_page(n, site_title, backlinks(keep).get(n.slug, []), related(n, keep))
        wanted[n.repo_path] = page
        was = old.get(n.src)
        if not was:
            result.added.append(n)
        elif was.get("hash") != n.hash or was.get("path") != n.repo_path:
            result.updated.append(n)

    kb_root_dir = os.path.join(repo, KB_DIR_NAME)
    existing = set()
    for dirpath, dirnames, filenames in os.walk(kb_root_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.endswith(".html"):
                existing.add(os.path.relpath(os.path.join(dirpath, name), repo).replace(os.sep, "/"))
    for rel in sorted(existing - set(wanted)):
        os.remove(os.path.join(repo, rel))
        prune_empty(repo, rel)
        result.removed.append(rel)
    for rel, page in wanted.items():
        full = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(page)

    with open(os.path.join(repo, KB_JSON), "w", encoding="utf-8") as f:
        json.dump({"notes": [n.entry() for n in keep]}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    write_graph(repo, keep, site_title)
    return result


def write_graph(repo, notes, site_title):
    with open(os.path.join(repo, GRAPH_FILE), "w", encoding="utf-8") as f:
        f.write(graph_page(notes, graph_data(notes), site_title))


def rebuild_graph(repo, site_title):
    """按 kb.json 重新生成图谱页，不重新读知识库。没有笔记时不生成，保持没启用时的原样。"""
    entries = load_kb(repo)
    if not entries:
        return 0
    notes = []
    for item in entries:
        n = _Stub(item)
        notes.append(n)
    with open(os.path.join(repo, GRAPH_FILE), "w", encoding="utf-8") as f:
        f.write(graph_page(notes, graph_data(notes), site_title))
    return len(notes)


class _Stub:
    """给 rebuild_graph 用的轻量笔记：只带图谱和兜底列表需要的字段。"""

    def __init__(self, item):
        self.slug = item["slug"]
        self.title = item["title"]
        self.project = item.get("project", "")
        self.type = item.get("type", "")
        self.tags = item.get("tags", [])
        self.links = item.get("links", [])
        self.updated = item.get("updated", "")


def prune_empty(repo, rel_file):
    d = os.path.dirname(os.path.join(repo, rel_file))
    while os.path.abspath(d) != os.path.abspath(repo) and os.path.isdir(d) and not os.listdir(d):
        os.rmdir(d)
        d = os.path.dirname(d)
