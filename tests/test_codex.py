"""Codex 支持的测试：清单、钩子在 Codex 环境下的行为、子 agent 角色文件的生成。

钩子的输入输出格式按 Codex 源码（codex-rs/hooks）核对过：SessionStart 的纯文本 stdout 会成为模型上下文，
UserPromptSubmit 的输入里有 session_id 和 prompt，插件钩子的环境里有 PLUGIN_ROOT 和 CLAUDE_PLUGIN_ROOT。
这些测试不启动 Codex。DISPATCH_TEST_CODEX=1 且装了 codex 命令时，多跑一个用真实 CLI 安装插件的测试
（装的是 git 里已提交的版本，所以要先提交再跑）。

运行：python3 -m unittest discover -s tests
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP = os.path.join(ROOT, "bin", "dispatch-codex-setup")


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items()
           if k not in ("PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT", "DISPATCH_HARNESS", "DISPATCH_KB_DIR",
                        "DISPATCH_PERSONAL_DIR", "CODEX_HOME")}
    env["HOME"] = tempfile.mkdtemp()
    env["USERPROFILE"] = env["HOME"]
    env.update(extra)
    return env


def session_start(**env):
    r = subprocess.run(["bash", os.path.join(ROOT, "hooks", "session-start.sh")], capture_output=True,
                       text=True, encoding="utf-8", env=clean_env(CLAUDE_PLUGIN_ROOT=ROOT, **env))
    assert r.returncode == 0, r.stderr
    return r.stdout


class ManifestTest(unittest.TestCase):
    def load(self, *parts):
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
            return json.load(fh)

    def test_codex_manifest_points_at_real_skills(self):
        m = self.load(".codex-plugin", "plugin.json")
        self.assertEqual(m["name"], "dispatch")
        self.assertTrue(m["skills"].startswith("./"), "Codex 要求清单里的路径以 ./ 开头")
        self.assertTrue(os.path.isdir(os.path.join(ROOT, m["skills"])))
        # 不写 hooks 字段：让 Codex 自动发现 hooks/hooks.json，dispatch 的钩子在 Codex 里是可用的
        self.assertNotIn("hooks", m)

    def test_versions_agree(self):
        self.assertEqual(self.load(".codex-plugin", "plugin.json")["version"],
                         self.load(".claude-plugin", "plugin.json")["version"])

    def test_marketplace_lists_the_plugin(self):
        mk = self.load(".agents", "plugins", "marketplace.json")
        entries = [p for p in mk["plugins"] if p["name"] == "dispatch"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source"], {"source": "url", "url": "./"})


class HookTest(unittest.TestCase):
    def test_codex_section_is_added_with_rendered_bin_dir(self):
        out = session_start(DISPATCH_HARNESS="codex")
        self.assertIn("Codex 适配", out)
        self.assertIn(os.path.join(ROOT, "bin"), out)
        self.assertNotIn("{{BIN_DIR}}", out)

    def test_claude_gets_no_codex_section(self):
        self.assertNotIn("Codex 适配", session_start(DISPATCH_HARNESS="claude"))

    def test_codex_is_detected_from_plugin_root_env(self):
        self.assertIn("Codex 适配", session_start(PLUGIN_ROOT=ROOT))
        self.assertNotIn("Codex 适配", session_start())

    def test_prompt_submit_reads_a_codex_payload(self):
        payload = {"session_id": "019a-test", "turn_id": "t1", "transcript_path": None, "cwd": "/tmp",
                   "hook_event_name": "UserPromptSubmit", "model": "x", "permission_mode": "default",
                   "prompt": "#L2 把导出改成流式"}
        r = subprocess.run(["bash", os.path.join(ROOT, "hooks", "prompt-submit.sh")], input=json.dumps(payload),
                           capture_output=True, text=True, encoding="utf-8", env=clean_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("L2", r.stdout)
        payload["prompt"] = "没有级别标记"
        r = subprocess.run(["bash", os.path.join(ROOT, "hooks", "prompt-submit.sh")], input=json.dumps(payload),
                           capture_output=True, text=True, encoding="utf-8", env=clean_env())
        self.assertEqual(r.stdout, "")


@unittest.skipIf(tomllib is None, "需要 Python 3.11+ 的 tomllib")
class RoleFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(tempfile.mkdtemp(), "agents")

    def run_setup(self, *args):
        return subprocess.run([sys.executable, SETUP, "--dir", self.dir, *args], capture_output=True,
                              text=True, encoding="utf-8")

    def role(self, name):
        with open(os.path.join(self.dir, f"dispatch_{name}.toml"), "rb") as fh:
            return tomllib.load(fh)

    def test_generates_valid_toml_for_every_agent(self):
        r = self.run_setup()
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in ("scout", "reviewer", "builder"):
            role = self.role(name)
            self.assertEqual(role["name"], f"dispatch_{name}")
            self.assertTrue(role["description"])
            self.assertIn("developer_instructions", role)

    def test_sandbox_follows_the_tools_the_agent_declares(self):
        self.run_setup()
        self.assertEqual(self.role("scout")["sandbox_mode"], "read-only")
        self.assertEqual(self.role("reviewer")["sandbox_mode"], "read-only")
        self.assertEqual(self.role("builder")["sandbox_mode"], "workspace-write")

    def test_no_model_is_pinned_unless_asked(self):
        self.run_setup()
        self.assertNotIn("model", self.role("scout"))
        self.run_setup("--model", "scout=my-small-model", "--effort", "scout=low")
        self.assertEqual(self.role("scout")["model"], "my-small-model")
        self.assertEqual(self.role("scout")["model_reasoning_effort"], "low")

    def test_builder_gets_an_absolute_path_for_dispatch_verify(self):
        self.run_setup()
        self.assertIn(os.path.join(ROOT, "bin", "dispatch-verify"), self.role("builder")["developer_instructions"])

    def test_rerun_overwrites_its_own_files_but_not_foreign_ones(self):
        self.run_setup()
        self.assertEqual(self.run_setup().returncode, 0)
        foreign = os.path.join(self.dir, "dispatch_scout.toml")
        with open(foreign, "w", encoding="utf-8") as fh:
            fh.write('name = "dispatch_scout"\ndescription = "我自己写的"\ndeveloper_instructions = "x"\n')
        r = self.run_setup()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.role("scout")["description"], "我自己写的")
        self.assertEqual(self.run_setup("--force").returncode, 0)
        self.assertNotEqual(self.role("scout")["description"], "我自己写的")

    def test_dry_run_writes_nothing_and_uninstall_removes_only_ours(self):
        self.run_setup("--dry-run")
        self.assertFalse(os.path.exists(self.dir))
        self.run_setup()
        other = os.path.join(self.dir, "mine.toml")
        with open(other, "w", encoding="utf-8") as fh:
            fh.write('name = "mine"\n')
        self.run_setup("--uninstall")
        self.assertEqual(os.listdir(self.dir), ["mine.toml"])

    def test_bad_arguments_are_rejected(self):
        self.assertNotEqual(self.run_setup("--model", "nobody=x").returncode, 0)
        self.assertNotEqual(self.run_setup("--effort", "scout=extreme").returncode, 0)


@unittest.skipUnless(os.environ.get("DISPATCH_TEST_CODEX") and shutil.which("codex"),
                     "设置 DISPATCH_TEST_CODEX=1 并安装 codex 命令后才跑")
class RealCodexTest(unittest.TestCase):
    def test_install_and_skills_are_visible(self):
        home = tempfile.mkdtemp()
        env = dict(os.environ, CODEX_HOME=home)

        def codex(*args):
            return subprocess.run(["codex", *args], capture_output=True, text=True, encoding="utf-8", env=env,
                                  cwd=home, timeout=120)

        self.assertEqual(codex("plugin", "marketplace", "add", ROOT).returncode, 0)
        r = codex("plugin", "add", "dispatch@claude-dispatch")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        prompt = codex("debug", "prompt-input", "hi").stdout
        for skill in ("dispatch:code-review", "dispatch:spec-check", "dispatch:l3-execute"):
            self.assertIn(skill, prompt)


if __name__ == "__main__":
    unittest.main()
