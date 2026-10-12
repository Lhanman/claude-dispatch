"""dispatch-usage 的行为测试：用合成的会话记录验证去重、分模型、子 agent 和多会话对比。

运行：python3 -m unittest discover -s tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "bin", "dispatch-usage")


def assistant(msg_id, model, inp, cw, cr, out, block="text"):
    return {"type": "assistant", "message": {
        "id": msg_id, "model": model, "content": [{"type": block}],
        "usage": {"input_tokens": inp, "cache_creation_input_tokens": cw,
                  "cache_read_input_tokens": cr, "output_tokens": out}}}


def write(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def run(*args):
    return subprocess.run([sys.executable, TOOL, *args], capture_output=True, text=True, encoding="utf-8")


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_split_blocks_of_one_reply_count_once(self):
        # 同一次回复被拆成三行（thinking / text / tool_use），usage 相同，只能算一次
        p = os.path.join(self.dir, "a.jsonl")
        write(p, [assistant("m1", "sonnet", 2, 100, 5000, 40, b) for b in ("thinking", "text", "tool_use")]
              + [assistant("m2", "sonnet", 1, 0, 5100, 60)])
        out = run(p)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("100", out.stdout)
        main_line = [l for l in out.stdout.splitlines() if l.startswith("合计")][0]
        # 两次回复：新输入 3，缓存写 100，缓存读 10,100，输出 100，新增合计 203
        for token in ("   2 ", "10,100", "203"):
            self.assertIn(token, main_line)

    def test_models_and_subagents_are_separate_rows(self):
        p = os.path.join(self.dir, "b.jsonl")
        write(p, [
            assistant("m1", "opus", 1, 10, 100, 20),
            assistant("m2", "sonnet", 1, 10, 100, 20),
            {"type": "user", "toolUseResult": {
                "agentId": "ag1", "description": "审查 L2 改动",
                "usage": {"input_tokens": 3, "cache_creation_input_tokens": 50,
                          "cache_read_input_tokens": 700, "output_tokens": 30}}},
            {"type": "cost-state", "totalCostUSD": 0.5,
             "modelUsage": {"opus": {"inputTokens": 1, "outputTokens": 20, "cacheReadInputTokens": 100,
                                     "cacheCreationInputTokens": 10, "costUSD": 0.5}}},
        ])
        out = run(p).stdout
        self.assertIn("主会话 · opus", out)
        self.assertIn("主会话 · sonnet", out)
        self.assertIn("子 agent · 审查 L2 改动", out)
        self.assertIn("$0.5000", out)

    def test_two_sessions_get_a_comparison_table(self):
        a, b = os.path.join(self.dir, "a.jsonl"), os.path.join(self.dir, "b.jsonl")
        write(a, [assistant("m1", "sonnet", 1, 0, 100, 10)])
        write(b, [assistant("m1", "sonnet", 1, 0, 300, 30)])
        out = run(a, b).stdout
        self.assertIn("对比", out)

    def test_missing_file_and_garbage_lines(self):
        self.assertNotEqual(run(os.path.join(self.dir, "nope.jsonl")).returncode, 0)
        p = os.path.join(self.dir, "c.jsonl")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("不是 json\n")
        self.assertEqual(run(p).returncode, 0)


if __name__ == "__main__":
    unittest.main()
