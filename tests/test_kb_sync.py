"""dispatch-pages kb-sync 的行为测试：在临时知识库 + 临时站点仓库里真实跑一遍。

重点是「不该上站的东西一点都不能漏」：白名单外的目录、命中敏感词的笔记、写了
publish: false 的笔记，它们的标题不允许出现在站点仓库的任何一个文件里。

运行：python3 -m unittest discover -s tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "bin", "dispatch-pages")
SITE = "https://example.test"

PUBLIC_NOTE = """---
title: 公开的回测口径
type: 方案
project: demo
summary: 一句话摘要，讲清楚结论
tags: [回测, 共享标签]
created: 2026-09-01
updated: 2026-09-20
---

# 公开的回测口径

## 结论
- 指向同目录的那篇：[[另一篇公开笔记]]
- 指向不该公开的那篇：[[内部机密笔记|换个说法的别名]]
- 一个表格：

| 列 | 值 |
|---|---:|
| a | 1 |
"""

OTHER_NOTE = """---
title: 另一篇公开笔记
type: 指南
project: demo
summary: 另一篇的摘要
tags: [共享标签]
updated: 2026-09-18
---

# 另一篇公开笔记

正文。
"""

OPTED_OUT = """---
title: 自己退出的笔记
publish: false
updated: 2026-09-10
---

不想上站。
"""

DENY_NOTE = """---
title: 命中公司词的笔记
updated: 2026-09-12
---

这里提到了 DJI 的内部流程。
"""

PRIVATE_NOTE = """---
title: 内部机密笔记
tags: [共享标签, 内部标签]
updated: 2026-09-11
---

云相册相关的内容。
"""

SECRET_WORDS = ["内部机密笔记", "换个说法的别名", "命中公司词的笔记", "DJI",
                "自己退出的笔记", "云相册", "内部标签", "每日工作计划"]


class KbSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "site")
        self.kb = os.path.join(self.tmp.name, "kb")
        os.makedirs(self.repo)
        for cmd in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@example.com"]):
            subprocess.run(["git", "-C", self.repo, *cmd], check=True)
        self.write("个人项目/demo/公开的回测口径.md", PUBLIC_NOTE)
        self.write("个人项目/demo/另一篇公开笔记.md", OTHER_NOTE)
        self.write("个人项目/demo/自己退出的笔记.md", OPTED_OUT)
        self.write("个人项目/demo/命中公司词的笔记.md", DENY_NOTE)
        self.write("云相册/内部机密笔记.md", PRIVATE_NOTE)
        self.write("每日工作计划/2026-09-01.md", "# 今天做了什么\n\n略。\n")
        self.config = os.path.join(self.tmp.name, "config")
        with open(self.config, "w", encoding="utf-8") as f:
            f.write(f"pages_repo={self.repo}\npages_url={SITE}\npages_title=测试站\n"
                    "pages_deny=DJI,云相册,mimo\n"
                    f"kb_dir={self.kb}\nkb_public=个人项目,技术笔记\n")

    def tearDown(self):
        self.tmp.cleanup()

    # ---- 工具 ----

    def write(self, rel, text):
        path = os.path.join(self.kb, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def run_tool(self, *args, expect=0):
        env = dict(os.environ, DISPATCH_CONFIG=self.config)
        r = subprocess.run([sys.executable, TOOL, *args], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, expect, r.stdout + r.stderr)
        return r.stdout + r.stderr

    def sync(self, *extra):
        return self.run_tool("kb-sync", "--no-push", *extra)

    def read(self, *parts):
        with open(os.path.join(*parts), encoding="utf-8") as f:
            return f.read()

    def repo_files(self):
        out = []
        for dirpath, dirnames, filenames in os.walk(self.repo):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            out += [os.path.join(dirpath, n) for n in filenames]
        return out

    def all_repo_text(self):
        text = []
        for path in self.repo_files():
            try:
                text.append(self.read(path))
            except UnicodeDecodeError:
                continue
        return "\n".join(text)

    def notes(self):
        return json.loads(self.read(self.repo, "kb.json"))["notes"]

    def slug_of(self, title):
        return next(n["slug"] for n in self.notes() if n["title"] == title)

    # ---- 用例 ----

    def test_only_whitelisted_and_clean_notes_are_published(self):
        self.sync()
        self.assertEqual({"公开的回测口径", "另一篇公开笔记"}, {n["title"] for n in self.notes()})

    def test_no_private_title_anywhere_in_site_repo(self):
        self.sync()
        text = self.all_repo_text()
        for word in SECRET_WORDS:
            self.assertNotIn(word, text, f"站点仓库里出现了不该公开的内容：{word}")

    def test_report_names_the_blocked_note_and_the_hit_word(self):
        out = self.sync()
        self.assertIn("命中公司词的笔记.md", out)
        self.assertIn("DJI", out)
        self.assertIn("publish: false", out)

    def test_link_to_published_note_becomes_site_link(self):
        self.sync()
        page = self.read(self.repo, "知识库", "个人项目", "demo", "公开的回测口径.html")
        self.assertIn(f'href="../{self.slug_of("另一篇公开笔记")}/"', page)
        self.assertIn("另一篇公开笔记", page)

    def test_link_to_private_note_becomes_placeholder(self):
        self.sync()
        page = self.read(self.repo, "知识库", "个人项目", "demo", "公开的回测口径.html")
        self.assertIn("（未公开）", page)

    def test_note_page_has_title_summary_tags_and_updated_date(self):
        self.sync()
        page = self.read(self.repo, "知识库", "个人项目", "demo", "公开的回测口径.html")
        self.assertIn("<h1>公开的回测口径</h1>", page)
        self.assertIn("一句话摘要", page)
        self.assertIn("更新于 2026-09-20", page)
        self.assertIn("<table>", page)

    def test_hub_lists_notes_and_documents_together(self):
        self.sync()
        index = self.read(self.repo, "index.html")
        self.assertIn("公开的回测口径", index)
        self.assertIn(f'href="kb/{self.slug_of("公开的回测口径")}/"', index)
        self.assertIn('data-kind="笔记"', index)
        self.assertIn('href="graph/"', index)

    def test_graph_has_shared_tag_node_and_no_private_node(self):
        self.sync()
        graph = self.read(self.repo, "知识图谱.html")
        data = json.loads(graph.split('<script id="graph-data" type="application/json">')[1].split("</script>")[0])
        ids = {n["id"] for n in data["nodes"]}
        self.assertIn("tag:共享标签", ids)
        self.assertNotIn("tag:内部标签", ids)
        self.assertEqual(2, sum(1 for n in data["nodes"] if n["kind"] == "note"))
        kinds = {edge["kind"] for edge in data["edges"]}
        self.assertEqual({"link", "tag", "project"}, kinds)
        self.assertIn("project:demo", ids)

    def test_site_build_serves_notes_and_graph_at_english_paths(self):
        self.sync()
        out = os.path.join(self.tmp.name, "_site")
        subprocess.run([sys.executable, os.path.join(self.repo, ".github", "build-site.py"), out],
                       check=True, cwd=self.repo)
        slug = self.slug_of("公开的回测口径")
        self.assertTrue(os.path.isfile(os.path.join(out, "kb", slug, "index.html")))
        self.assertTrue(os.path.isfile(os.path.join(out, "graph", "index.html")))
        self.assertTrue(os.path.isfile(os.path.join(out, "index.html")))
        page = self.read(out, "kb", slug, "index.html")
        self.assertIn('<link rel="index" href="../../index.html">', page)

    def test_deleted_note_goes_offline_on_next_sync(self):
        self.sync()
        os.remove(os.path.join(self.kb, "个人项目/demo/另一篇公开笔记.md"))
        out = self.sync()
        self.assertIn("下线 1", out)
        self.assertEqual(["公开的回测口径"], [n["title"] for n in self.notes()])
        self.assertFalse(os.path.exists(os.path.join(self.repo, "知识库/个人项目/demo/另一篇公开笔记.html")))
        self.assertNotIn("另一篇公开笔记", self.read(self.repo, "index.html"))

    def test_note_turned_private_goes_offline(self):
        self.sync()
        self.write("个人项目/demo/另一篇公开笔记.md", OTHER_NOTE.replace("type: 指南", "type: 指南\npublish: false"))
        self.sync()
        self.assertEqual(["公开的回测口径"], [n["title"] for n in self.notes()])

    def test_renamed_note_keeps_its_url(self):
        self.sync()
        before = self.slug_of("另一篇公开笔记")
        os.rename(os.path.join(self.kb, "个人项目/demo/另一篇公开笔记.md"),
                  os.path.join(self.kb, "个人项目/demo/换个文件名.md"))
        self.sync()
        self.assertEqual(before, self.slug_of("另一篇公开笔记"))

    def test_frontmatter_slug_is_used_for_the_url(self):
        self.write("个人项目/demo/带 slug 的笔记.md",
                   "---\ntitle: 带 slug 的笔记\nslug: my-note\nupdated: 2026-09-21\n---\n\n正文。\n")
        self.sync()
        self.assertEqual("my-note", self.slug_of("带 slug 的笔记"))

    def test_dry_run_writes_nothing(self):
        out = self.sync("--dry-run")
        self.assertIn("没有写入", out)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "kb.json")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, "知识库")))

    def test_without_whitelist_nothing_is_synced(self):
        with open(self.config, encoding="utf-8") as f:
            text = f.read().replace("kb_public=个人项目,技术笔记\n", "")
        with open(self.config, "w", encoding="utf-8") as f:
            f.write(text)
        out = self.run_tool("kb-sync", "--no-push", expect=1)
        self.assertIn("kb_public", out)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "kb.json")))

    def test_fallback_summary_never_carries_private_link_text(self):
        # 没有 frontmatter summary 的老笔记：第一段里指向未公开笔记的链接，不能漏进摘要和检索索引
        self.write("个人项目/demo/没有摘要的老笔记.md",
                   "# 没有摘要的老笔记\n\n细节见 [内部机密笔记](../别处/内部机密笔记.md) 那一篇。\n")
        self.sync()
        note = next(n for n in self.notes() if n["title"] == "没有摘要的老笔记")
        self.assertNotIn("内部机密笔记", note["summary"] + note["text"])
        self.assertNotIn("内部机密笔记", self.all_repo_text())

    def test_frontmatter_with_bom_still_opts_out(self):
        # 带 BOM 的笔记如果解析不到 frontmatter，publish: false 会被无声忽略
        self.write("个人项目/demo/带BOM的退出笔记.md", "\ufeff" + OPTED_OUT.replace("自己退出的笔记", "带BOM的退出笔记"))
        self.sync()
        self.assertNotIn("带BOM的退出笔记", self.all_repo_text())

    def test_existing_note_keeps_its_slug_when_a_new_note_shares_the_title(self):
        self.write("个人项目/demo/zzz.md", "---\ntitle: Guide\nupdated: 2026-09-15\n---\n\n旧的。\n")
        self.sync()
        before = self.slug_of("Guide")
        self.write("个人项目/demo/aaa.md", "---\ntitle: Guide\nupdated: 2026-09-16\n---\n\n新的。\n")
        self.sync()
        kept = next(n["slug"] for n in self.notes() if n["src"].endswith("zzz.md"))
        self.assertEqual(before, kept)

    def test_two_notes_colliding_on_one_file_name_keep_separate_pages(self):
        # safe_name 会把 : 换成 -，两篇笔记可能撞到同一个仓库路径
        self.write("个人项目/demo/名字:带冒号.md", "---\ntitle: 冒号那篇\nupdated: 2026-09-14\n---\n\n冒号正文。\n")
        self.write("个人项目/demo/名字-带冒号.md", "---\ntitle: 连字符那篇\nupdated: 2026-09-13\n---\n\n连字符正文。\n")
        self.sync()
        paths = [n["path"] for n in self.notes()]
        self.assertEqual(len(paths), len(set(paths)))
        for title, text in (("冒号那篇", "冒号正文"), ("连字符那篇", "连字符正文")):
            path = next(n["path"] for n in self.notes() if n["title"] == title)
            self.assertIn(text, self.read(self.repo, *path.split("/")))

    def test_graph_data_cannot_close_the_script_tag(self):
        self.write("个人项目/demo/注入.md",
                   "---\ntitle: abc</script><img src=x onerror=alert(1)>\ntags: [共享标签]\nupdated: 2026-09-17\n---\n\n正文。\n")
        self.sync()
        graph = self.read(self.repo, "知识图谱.html")
        self.assertNotIn("</script><img", graph)
        self.assertIn("u003c/script", graph)

    def test_attachment_embed_is_reported_as_not_uploaded(self):
        self.write("个人项目/demo/带附件的笔记.md",
                   "---\ntitle: 带附件的笔记\nupdated: 2026-09-19\n---\n\n![[示意图.png]]\n")
        out = self.sync()
        self.assertIn("带附件的笔记.md", out.split("图片没有上传")[1][:200])

    def test_rebuild_without_notes_does_not_create_an_empty_graph(self):
        r = subprocess.run([sys.executable, TOOL, "rebuild", "--no-push"], capture_output=True, text=True,
                           env=dict(os.environ, DISPATCH_CONFIG=self.config))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "知识图谱.html")))

    def test_local_image_is_not_uploaded(self):
        self.write("个人项目/demo/带图片的笔记.md",
                   "---\ntitle: 带图片的笔记\nupdated: 2026-09-22\n---\n\n![示意](本地图.png)\n")
        out = self.sync()
        self.assertIn("图片没有上传", out)
        page = self.read(self.repo, "知识库", "个人项目", "demo", "带图片的笔记.html")
        self.assertNotIn("本地图.png", page)
        self.assertIn("图片未公开", page)

    def test_sync_commits_to_the_site_repo(self):
        self.sync()
        log = subprocess.run(["git", "-C", self.repo, "log", "--oneline"], capture_output=True, text=True)
        self.assertIn("知识库同步", log.stdout)
        status = subprocess.run(["git", "-C", self.repo, "status", "--porcelain"], capture_output=True, text=True)
        self.assertEqual("", status.stdout.strip())


class RenderStateTest(unittest.TestCase):
    """第二遍检查踢掉某篇笔记后要全部重渲染：兜底摘要不能还留着它的标题。"""

    def setUp(self):
        sys.path.insert(0, os.path.join(ROOT, "lib"))
        self.tmp = tempfile.TemporaryDirectory()
        self.kb = self.tmp.name
        for rel, text in (("甲.md", "---\ntitle: 甲\n---\n\n细节见 [[乙]] 那一篇。\n"),
                          ("乙.md", "---\ntitle: 乙\n---\n\n乙的正文。\n")):
            with open(os.path.join(self.kb, rel), "w", encoding="utf-8") as f:
                f.write(text)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fallback_summary_is_recomputed_when_target_drops_out(self):
        import kbsite
        notes, _ = kbsite.collect(self.kb, ["."], set())
        kbsite.assign_slugs(notes, [])
        lookup = kbsite.build_lookup(notes)
        first = next(n for n in notes if n.title == "甲")
        kbsite.render_note(first, lookup, {n.slug for n in notes})
        self.assertIn("乙", first.summary)
        kbsite.render_note(first, lookup, {first.slug})   # 乙被第二遍检查拦下了
        self.assertNotIn("乙", first.summary)
        self.assertIn("（未公开）", first.summary)


if __name__ == "__main__":
    unittest.main()
