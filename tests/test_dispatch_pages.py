"""dispatch-pages 的行为测试：在临时站点仓库里真实运行命令（--no-push，不碰远端）。

运行：python3 -m unittest discover -s tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "dispatch-pages")
SITE = "https://example.test"
PAGE = "<title>演示文档</title>\n<style>body{color:#111}</style>\n<p>正文</p>\n"


class PagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "site")
        os.makedirs(self.repo)
        for cmd in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@example.com"]):
            subprocess.run(["git", "-C", self.repo, *cmd], check=True)
        self.config = os.path.join(self.tmp.name, "config")
        with open(self.config, "w", encoding="utf-8") as f:
            f.write(f"pages_repo={self.repo}\npages_url={SITE}\npages_title=测试站\n")
        self.src = os.path.join(self.tmp.name, "demo.html")
        with open(self.src, "w", encoding="utf-8") as f:
            f.write(PAGE)

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args, cwd=None):
        env = dict(os.environ, DISPATCH_CONFIG=self.config)
        r = subprocess.run([sys.executable, TOOL, *args], capture_output=True, text=True, env=env, cwd=cwd)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def publish(self):
        return self.run_tool("publish", self.src, "--slug", "demo-page", "--desc", "一句话", "--no-push")

    def read(self, *parts):
        with open(os.path.join(*parts), encoding="utf-8") as f:
            return f.read()

    def test_publish_prints_english_url(self):
        out = self.publish()
        self.assertIn(f"网址：{SITE}/p/demo-page/", out)
        self.assertNotIn("%E", out)

    def test_local_file_keeps_chinese_path(self):
        self.publish()
        self.assertTrue(os.path.isfile(os.path.join(self.repo, "文档", "其他", "演示文档.html")))

    def test_index_links_to_english_url(self):
        self.publish()
        index = self.read(self.repo, "index.html")
        self.assertIn('href="p/demo-page/"', index)
        self.assertNotIn("%E6%96%87%E6%A1%A3", index)

    def test_readme_lists_online_url(self):
        self.publish()
        self.assertIn(f"{SITE}/p/demo-page/", self.read(self.repo, "README.md"))

    def test_publish_writes_pages_workflow(self):
        self.publish()
        workflow = self.read(self.repo, ".github", "workflows", "pages.yml")
        self.assertIn("actions/deploy-pages", workflow)
        self.assertIn(".github/build-site.py", workflow)

    def test_site_build_serves_docs_at_english_paths(self):
        self.publish()
        out = os.path.join(self.tmp.name, "_site")
        subprocess.run([sys.executable, os.path.join(self.repo, ".github", "build-site.py"), out],
                       check=True, cwd=self.repo)
        page = self.read(out, "p", "demo-page", "index.html")
        self.assertIn("<p>正文</p>", page)
        self.assertIn('<link rel="index" href="../../index.html">', page)
        self.assertTrue(os.path.isfile(os.path.join(out, "index.html")))
        self.assertFalse(os.path.exists(os.path.join(out, "文档")), "线上不应再出现中文路径")

    def build_with_catalog_entry(self, extra):
        """发布一篇正常文档，再往 catalog.json 里加一条异常条目，然后构建站点。"""
        self.publish()
        cat_path = os.path.join(self.repo, "catalog.json")
        cat = json.loads(self.read(cat_path))
        cat["pages"].append(extra)
        with open(cat_path, "w", encoding="utf-8") as f:
            json.dump(cat, f, ensure_ascii=False)
        out = os.path.join(self.tmp.name, "_site")
        r = subprocess.run([sys.executable, os.path.join(self.repo, ".github", "build-site.py"), out],
                           capture_output=True, text=True, cwd=self.repo)
        return r, out

    def test_site_build_skips_missing_file_without_failing(self):
        r, out = self.build_with_catalog_entry({"slug": "gone", "title": "已删除", "path": "文档/其他/不存在.html"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("gone", r.stdout + r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(out, "p", "demo-page", "index.html")))
        self.assertTrue(os.path.isfile(os.path.join(out, "index.html")))

    def test_site_build_falls_back_to_legacy_path(self):
        legacy = os.path.join(self.repo, "p", "old-page")
        os.makedirs(legacy)
        with open(os.path.join(legacy, "index.html"), "w", encoding="utf-8") as f:
            f.write("<p>旧结构</p>")
        r, out = self.build_with_catalog_entry({"slug": "old-page", "title": "旧文档"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("<p>旧结构</p>", self.read(out, "p", "old-page", "index.html"))


if __name__ == "__main__":
    unittest.main()
