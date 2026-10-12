"""skill、agent 和路由规则的静态检查（不调用模型）。

守住三件事：
  1. 结构不坏：frontmatter 完整，名字和文件名一致。
  2. 引用不断：规则里写的 dispatch:xxx、dispatch-xxx 都真的存在。
  3. 常驻开销不悄悄变大：ROUTER.md 和各 skill、agent 的描述每个会话都会进上下文。

预算数字故意卡得很紧。要加内容，先改这里的数字，并在提交说明里写清为什么值得每个会话多付这笔钱。

运行：python3 -m unittest discover -s tests
"""
import glob
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROUTER_MAX_BYTES = 4400        # router/ROUTER.md，每个会话必进上下文
DESCRIPTIONS_MAX_CHARS = 1600  # 所有 skill 和 agent 的 description 合计，同样每个会话都在
DESCRIPTION_MAX_CHARS = 300    # 单条描述上限
# Codex 对钩子输出设了 2,500 token 的上限，按 4 字节一个 token 估算（codex-rs/utils/string 的 approx_token_count），
# 约 10,000 字节；超了就整段写进临时文件，只给模型一个预览。SessionStart 在配齐所有可选模块后会输出
# ROUTER + CODEX + KB + PERSONAL + PAGES，所以要给这五个文件的总和留余量。
HOOK_OUTPUT_MAX_BYTES = 9600


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def frontmatter(path):
    text = read(path)
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    fields = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep:
            fields[k.strip()] = v.strip()
    return fields


def skills():
    return sorted(glob.glob(os.path.join(ROOT, "skills", "*", "SKILL.md")))


def agents():
    return sorted(glob.glob(os.path.join(ROOT, "agents", "*.md")))


class StructureTest(unittest.TestCase):
    def test_skill_frontmatter(self):
        for path in skills():
            fm = frontmatter(path)
            rel = os.path.relpath(path, ROOT)
            self.assertIsNotNone(fm, f"{rel} 缺少 frontmatter")
            self.assertEqual(fm.get("name"), os.path.basename(os.path.dirname(path)), f"{rel} 的 name 和目录名不一致")
            self.assertTrue(fm.get("description"), f"{rel} 缺少 description")
            self.assertLessEqual(len(fm["description"]), DESCRIPTION_MAX_CHARS, f"{rel} 的描述太长")

    def test_agent_frontmatter(self):
        for path in agents():
            fm = frontmatter(path)
            rel = os.path.relpath(path, ROOT)
            self.assertIsNotNone(fm, f"{rel} 缺少 frontmatter")
            self.assertEqual(fm.get("name"), os.path.basename(path)[:-3], f"{rel} 的 name 和文件名不一致")
            self.assertTrue(fm.get("description"), f"{rel} 缺少 description")
            self.assertTrue(fm.get("model"), f"{rel} 必须显式写 model，省略会继承主会话的模型")
            self.assertLessEqual(len(fm["description"]), DESCRIPTION_MAX_CHARS, f"{rel} 的描述太长")


class ReferenceTest(unittest.TestCase):
    def sources(self):
        files = glob.glob(os.path.join(ROOT, "router", "*.md")) + skills() + agents() + [os.path.join(ROOT, "README.md")]
        files += glob.glob(os.path.join(ROOT, "skills", "*", "*.md"))
        return sorted(set(files))

    def test_dispatch_references_resolve(self):
        known = {os.path.basename(os.path.dirname(p)) for p in skills()} | {os.path.basename(p)[:-3] for p in agents()}
        for path in self.sources():
            for name in re.findall(r"dispatch:([a-z][a-z0-9-]*)", read(path)):
                self.assertIn(name, known, f"{os.path.relpath(path, ROOT)} 引用了不存在的 dispatch:{name}")

    def test_no_leftover_superpowers_references(self):
        # 从 superpowers 引入的 skill 要把 superpowers:xxx 改成本插件里存在的东西，否则模型会去调一个不存在的 skill
        for path in glob.glob(os.path.join(ROOT, "skills", "**", "*.md"), recursive=True):
            m = re.search(r"superpowers:[a-z][a-z-]*", read(path))
            self.assertIsNone(m, f"{os.path.relpath(path, ROOT)} 里还有 {m and m.group(0)} 引用")

    def test_bin_tools_exist(self):
        for path in self.sources():
            for tool in set(re.findall(r"\bdispatch-([a-z]+)\b", read(path))):
                exe = os.path.join(ROOT, "bin", f"dispatch-{tool}")
                if tool in ("verify", "usage", "kb", "pages"):
                    self.assertTrue(os.access(exe, os.X_OK), f"bin/dispatch-{tool} 不存在或没有可执行权限（{os.path.relpath(path, ROOT)} 引用了它）")


class AlwaysOnBudgetTest(unittest.TestCase):
    def test_router_size(self):
        size = os.path.getsize(os.path.join(ROOT, "router", "ROUTER.md"))
        self.assertLessEqual(size, ROUTER_MAX_BYTES, f"ROUTER.md 有 {size} 字节，超出预算 {ROUTER_MAX_BYTES}：每个会话都要为它付 token")

    def test_all_router_modules_fit_in_codex_hook_output(self):
        total = sum(os.path.getsize(p) for p in glob.glob(os.path.join(ROOT, "router", "*.md")))
        self.assertLessEqual(total, HOOK_OUTPUT_MAX_BYTES,
                             f"router/*.md 合计 {total} 字节，超出 Codex 钩子输出上限的预算 {HOOK_OUTPUT_MAX_BYTES}")

    def test_descriptions_total(self):
        total = sum(len(frontmatter(p)["description"]) for p in skills() + agents())
        self.assertLessEqual(total, DESCRIPTIONS_MAX_CHARS, f"skill 和 agent 的描述合计 {total} 字符，超出预算 {DESCRIPTIONS_MAX_CHARS}")


if __name__ == "__main__":
    unittest.main()
