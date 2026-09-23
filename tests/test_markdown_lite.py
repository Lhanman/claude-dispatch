"""lib/markdown_lite.py 的行为测试：只覆盖笔记里真实会用到的语法。

运行：python3 -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

import markdown_lite  # noqa: E402


def html(text, **kw):
    return markdown_lite.render(text, **kw).html


class BlockTest(unittest.TestCase):
    def test_heading_gets_anchor_id(self):
        out = markdown_lite.render("## 结论\n")
        self.assertIn('<h2 id="结论">结论</h2>', out.html)
        self.assertEqual([(2, "结论", "结论")], out.headings)

    def test_heading_shift_keeps_one_h1_on_page(self):
        out = markdown_lite.render("# 标题\n\n## 小节\n", shift=1)
        self.assertIn('<h2 id="标题">标题</h2>', out.html)
        self.assertIn('<h3 id="小节">小节</h3>', out.html)

    def test_duplicate_heading_ids_are_unique(self):
        out = markdown_lite.render("## 结论\n\n## 结论\n")
        self.assertEqual(["结论", "结论-2"], [h[2] for h in out.headings])

    def test_paragraph_keeps_single_newline_as_line_break(self):
        self.assertIn("第一行<br>第二行", html("第一行\n第二行\n"))

    def test_fenced_code_is_escaped_and_tagged(self):
        out = html("```python\nprint('<a>')\n```\n")
        self.assertIn('<pre><code class="language-python">', out)
        self.assertIn("print(&#x27;&lt;a&gt;&#x27;)", out)

    def test_code_fence_content_is_not_parsed_as_markdown(self):
        out = html("```\n- 不是列表 **不是粗体** [[不是链接]]\n```\n")
        self.assertNotIn("<li>", out)
        self.assertNotIn("<strong>", out)
        self.assertIn("[[不是链接]]", out)

    def test_nested_and_task_lists(self):
        out = html("- 一\n  - 一之一\n- [x] 做完了\n- [ ] 没做\n")
        self.assertIn("<ul>", out)
        self.assertEqual(2, out.count("<ul>"))
        self.assertIn("一之一", out)
        self.assertIn('checked', out)

    def test_ordered_list(self):
        out = html("1. 一\n2. 二\n")
        self.assertIn("<ol>", out)
        self.assertEqual(2, out.count("<li>"))

    def test_table_with_alignment(self):
        out = html("| 列 | 值 |\n|---|---:|\n| a | 1 |\n")
        self.assertIn("<table>", out)
        self.assertIn("<th>列</th>", out)
        self.assertIn('<td style="text-align:right">1</td>', out)

    def test_blockquote_and_hr(self):
        out = html("> 引用\n\n---\n")
        self.assertIn("<blockquote>", out)
        self.assertIn("<hr>", out)

    def test_empty_paragraph_does_not_break_rendering(self):
        # 渲染结果为空的段落曾经让整次同步崩溃
        out = html("正常段落\n\n[]()\n\n[](javascript:x)\n")
        self.assertIn("正常段落", out)

    def test_raw_html_is_escaped_not_executed(self):
        out = html("<script>alert(1)</script>\n")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)


class InlineTest(unittest.TestCase):
    def test_emphasis_code_and_strike(self):
        out = html("**粗** *斜* `码` ~~删~~\n")
        for frag in ("<strong>粗</strong>", "<em>斜</em>", "<code>码</code>", "<del>删</del>"):
            self.assertIn(frag, out)

    def test_inline_code_keeps_brackets(self):
        self.assertIn("<code>[[原样]]</code>", html("`[[原样]]`\n"))

    def test_escape_sequence(self):
        self.assertNotIn("<strong>", html(r"\*\*不是粗体\*\*" + "\n"))

    def test_external_link_and_bare_url(self):
        out = html("[站](https://example.test) https://example.test/x\n")
        self.assertIn('<a href="https://example.test"', out)
        self.assertIn('href="https://example.test/x"', out)

    def test_protocol_relative_link_is_treated_as_external(self):
        out = html("[站](//example.test/x)\n")
        self.assertIn('<a href="//example.test/x" rel="nofollow noopener">', out)

    def test_javascript_url_is_not_linked(self):
        out = html("[点我](javascript:alert(1))\n")
        self.assertNotIn("javascript:", out)

    def test_external_image_kept_local_image_dropped(self):
        out = html("![远](https://example.test/a.png)\n\n![近](图.png)\n")
        self.assertIn('<img src="https://example.test/a.png" alt="远"', out)
        self.assertNotIn("图.png", out)
        self.assertIn("图片未公开", out)


class HookTest(unittest.TestCase):
    def resolve(self, target, section, alias, embed):
        if target == "公开笔记":
            return f'<a href="../pub/">{alias or target}</a>'
        return None

    def test_wikilink_uses_hook(self):
        out = html("见 [[公开笔记]] 和 [[私密笔记]]。\n", wikilink=self.resolve)
        self.assertIn('<a href="../pub/">公开笔记</a>', out)
        self.assertNotIn("私密笔记", out)
        self.assertIn("（未公开）", out)

    def test_wikilink_alias_of_private_note_is_not_leaked(self):
        out = html("见 [[私密笔记|机密别名]]。\n", wikilink=self.resolve)
        self.assertNotIn("机密别名", out)
        self.assertNotIn("私密笔记", out)

    def test_relative_md_link_uses_hook(self):
        out = html("见 [说明](./公开笔记.md)。\n", wikilink=self.resolve)
        self.assertIn('<a href="../pub/">说明</a>', out)

    def test_embed_of_private_note_is_not_leaked(self):
        out = html("![[私密笔记]]\n", wikilink=self.resolve)
        self.assertNotIn("私密笔记", out)

    def test_directory_style_relative_link_is_not_leaked(self):
        out = html("见 [私密笔记](../别处/)。\n", wikilink=self.resolve)
        self.assertNotIn("私密笔记", out)
        self.assertIn("（未公开）", out)

    def test_heading_anchor_never_carries_private_link_text(self):
        # 标题里放一个指向未公开笔记的普通 Markdown 链接：正文、锚点 id 和目录都不能留下它的文字
        out = markdown_lite.render("## 背景 [私密笔记](../别处/私密笔记.md)\n", wikilink=self.resolve)
        self.assertNotIn("私密笔记", out.html)
        self.assertNotIn("私密笔记", out.headings[0][1])
        self.assertNotIn("私密笔记", out.headings[0][2])


class PlainTextTest(unittest.TestCase):
    def test_plain_text_drops_markup_for_search_index(self):
        text = markdown_lite.plain_text("# 标题\n\n**粗**体和 `代码`\n\n- 项\n")
        self.assertIn("标题", text)
        self.assertIn("粗体和 代码", text)
        self.assertNotIn("**", text)
        self.assertNotIn("#", text)


if __name__ == "__main__":
    unittest.main()
