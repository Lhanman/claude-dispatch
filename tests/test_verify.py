"""dispatch-verify 的行为测试，重点是 --record：只有验证通过才写账本。

运行：python3 -m unittest discover -s tests
"""
import os
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "bin", "dispatch-verify")


def run(*args, cwd=None):
    env = dict(os.environ, TMPDIR=tempfile.gettempdir())
    return subprocess.run(["bash", TOOL, *args], capture_output=True, text=True, encoding="utf-8", cwd=cwd, env=env)


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ledger = os.path.join(self.dir, "changes", "demo", "progress.md")

    def test_pass_appends_one_line_to_ledger(self):
        r = run("--record", self.ledger, "组 1", "true", cwd=self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.ledger, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("组 1", lines[0])
        self.assertIn("✔ true", lines[0])

    def test_second_pass_appends_not_overwrites(self):
        run("--record", self.ledger, "组 1", "true", cwd=self.dir)
        run("--record", self.ledger, "组 2", "true", cwd=self.dir)
        with open(self.ledger, encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().splitlines()), 2)

    def test_failure_records_nothing_and_keeps_exit_code(self):
        r = run("--record", self.ledger, "组 1", "exit 3", cwd=self.dir)
        self.assertEqual(r.returncode, 3)
        self.assertFalse(os.path.exists(self.ledger))

    def test_without_record_flag_nothing_is_written(self):
        r = run("true", cwd=self.dir)
        self.assertEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(self.ledger))

    def test_usage_errors(self):
        self.assertEqual(run().returncode, 2)
        self.assertEqual(run("--record", self.ledger, "组 1", cwd=self.dir).returncode, 2)


if __name__ == "__main__":
    unittest.main()
